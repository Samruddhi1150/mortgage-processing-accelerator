from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.mortgage.decisioning import PolicyAssessment, ValidationEvidence
from src.mortgage.openai_policy import OpenAIPolicyDecisionEngine
from src.mortgage.workflow import MortgageOrchestrator, StageOutcome


NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
ALL_PASS = {"income_verified": True, "valuation_current": True, "debt_verified": True}


def complete_evidence():
    return [
        ("income", {"verified": True, "annual_income": 72000}),
        ("valuation", {"value": 340000, "valuation_date": NOW.date().isoformat()}),
        ("debt", {"verified": True, "monthly_debt": 300}),
    ]


def passed_validation(**changes):
    values = {
        "policy_version": "test-v1",
        "authoritative_rule_results": ALL_PASS,
        "approved_policy_rules": {rule_id: "Configured synthetic test rule" for rule_id in ALL_PASS},
        "dual_control_reviewers": ("reviewer-a", "reviewer-b"),
        "fair_lending_passed": True,
        "fair_lending_audit_id": "audit-test-1",
        "approved_offer_conditions": ("Final underwriter release",),
    }
    values.update(changes)
    return ValidationEvidence(**values)


class StaticDecisionEngine:
    def __init__(self, assessment):
        self.assessment = assessment
        self.calls = 0

    def assess(self, evidence, policy_version, approved_policy_rules, approved_reason_descriptions):
        self.calls += 1
        return self.assessment


def process_all(orchestrator, application_id="app-test"):
    result = None
    for document_type, evidence in complete_evidence():
        result = orchestrator.process_document(
            application_id, document_type, evidence, NOW - timedelta(seconds=5)
        )
    return result


def test_aggregator_waits_for_each_document_without_replaying_stages():
    orchestrator = MortgageOrchestrator(clock=lambda: NOW)
    first = orchestrator.process_document(
        "app-pending", "income", {"verified": True, "annual_income": 72000}
    )
    second = orchestrator.process_document(
        "app-pending",
        "valuation",
        {"value": 340000, "valuation_date": NOW.date().isoformat()},
    )

    assert first["status"] == "pending"
    assert second["status"] == "pending"
    assert set(orchestrator.applications["app-pending"].stage_outcomes) == {"income", "valuation"}
    assert "debt" in second["outstanding_conditions"][0]


def test_all_passed_policy_and_validation_create_draft_offer():
    engine = StaticDecisionEngine(
        PolicyAssessment("automated_offer", "test-v1", ALL_PASS)
    )
    orchestrator = MortgageOrchestrator(
        policy_engine=engine,
        validation_evidence_provider=lambda _app, _docs: passed_validation(),
        clock=lambda: NOW,
    )

    result = process_all(orchestrator)

    assert result["status"] == "automated_offer"
    assert result["offer"]["status"] == "draft"
    assert result["offer"]["conditions"] == ["Final underwriter release"]
    assert result["processing_seconds"] == 5
    assert engine.calls == 1


def test_rule_mismatch_fails_closed_to_underwriter_review():
    engine = StaticDecisionEngine(
        PolicyAssessment("automated_offer", "test-v1", {**ALL_PASS, "income_verified": False})
    )
    orchestrator = MortgageOrchestrator(
        policy_engine=engine,
        validation_evidence_provider=lambda _app, _docs: passed_validation(),
        clock=lambda: NOW,
    )

    result = process_all(orchestrator)

    assert result["status"] == "underwriter_review"
    assert "do not match" in result["auto_explainer"]


def test_decline_requires_verified_hard_rule_and_approved_reason():
    results = {"income_verified": True, "valuation_current": True, "debt_verified": False}
    validation = passed_validation(
        authoritative_rule_results=results,
        hard_rule_ids=frozenset({"debt_verified"}),
        approved_reason_descriptions={"DEBT_RULE": "Verified policy rule failed"},
        reason_code_rule_ids={"DEBT_RULE": "debt_verified"},
    )
    engine = StaticDecisionEngine(
        PolicyAssessment(
            "validated_decline", "test-v1", results, reason_codes=("DEBT_RULE",)
        )
    )
    orchestrator = MortgageOrchestrator(
        policy_engine=engine,
        validation_evidence_provider=lambda _app, _docs: validation,
        clock=lambda: NOW,
    )

    result = process_all(orchestrator)

    assert result["status"] == "validated_decline"
    assert result["adverse_action_notice"]["status"] == "draft_requires_compliance_review"
    assert result["validated_rule_breaches"] == ["debt_verified"]


def test_decline_requires_a_reason_for_every_hard_rule_breach():
    results = {"income_verified": True, "valuation_current": False, "debt_verified": False}
    validation = passed_validation(
        authoritative_rule_results=results,
        hard_rule_ids=frozenset({"valuation_current", "debt_verified"}),
        approved_reason_descriptions={"DEBT_RULE": "Verified debt rule failed"},
        reason_code_rule_ids={"DEBT_RULE": "debt_verified"},
    )
    engine = StaticDecisionEngine(
        PolicyAssessment(
            "validated_decline", "test-v1", results, reason_codes=("DEBT_RULE",)
        )
    )
    orchestrator = MortgageOrchestrator(
        policy_engine=engine,
        validation_evidence_provider=lambda _app, _docs: validation,
        clock=lambda: NOW,
    )

    result = process_all(orchestrator)

    assert result["status"] == "underwriter_review"
    assert "Every verified hard-rule breach" in result["auto_explainer"]


def test_missing_dual_control_or_fair_lending_routes_to_review():
    engine = StaticDecisionEngine(
        PolicyAssessment("automated_offer", "test-v1", ALL_PASS)
    )
    validation = passed_validation(dual_control_reviewers=("same-reviewer", "same-reviewer"))
    orchestrator = MortgageOrchestrator(
        policy_engine=engine,
        validation_evidence_provider=lambda _app, _docs: validation,
        clock=lambda: NOW,
    )

    result = process_all(orchestrator)

    assert result["status"] == "underwriter_review"
    assert "Two distinct reviewers" in result["auto_explainer"]
    assert "draft" not in result


def test_openai_adapter_uses_strict_schema_and_sanitizes_evidence():
    output = {
        "recommendation": "underwriter_review",
        "policy_version": "test-v1",
        "rule_results": [{"rule_id": "income_verified", "passed": True}],
        "reason_codes": [],
        "explanation": "Review requested",
    }
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status="completed", output=[], output_text=json.dumps(output))

    fake_client = SimpleNamespace(responses=SimpleNamespace(create=create))
    engine = OpenAIPolicyDecisionEngine(client=fake_client, model="test-model")
    assessment = engine.assess(
        {
            "income": {"verified": True, "annual_income": 72000, "name": "Private Name"},
            "valuation": {"value": 340000, "valuation_date": NOW.date().isoformat()},
            "debt": {"verified": True, "monthly_debt": 300, "account_number": "private"},
        },
        "test-v1",
        {"income_verified": "Synthetic rule"},
        {},
    )

    sent = json.loads(captured["input"][1]["content"])
    assert captured["model"] == "test-model"
    assert captured["text"]["format"]["strict"] is True
    assert assessment.rule_results == {"income_verified": True}
    assert "name" not in sent["evidence"]["income"]
    assert "account_number" not in sent["evidence"]["debt"]


def test_document_hub_api_accepts_incremental_evidence():
    import app as application
    from src.mortgage import api

    previous_orchestrator = api._orchestrator
    api._orchestrator = MortgageOrchestrator(clock=lambda: NOW)
    try:
        client = TestClient(application.app)
        response = client.post(
            "/mortgage/applications/api-app/documents",
            json={"document_type": "income", "evidence": {"verified": True, "annual_income": 72000}},
        )
        status = client.get("/mortgage/applications/api-app")
    finally:
        api._orchestrator = previous_orchestrator

    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert status.status_code == 200
    assert status.json()["received_documents"] == ["income"]
