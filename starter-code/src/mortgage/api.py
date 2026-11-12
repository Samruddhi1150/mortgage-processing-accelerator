from __future__ import annotations

import os
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.mortgage.decisioning import ValidationEvidence
from src.mortgage.workflow import MortgageOrchestrator, ReviewOnlyPolicyEngine


router = APIRouter(prefix="/mortgage", tags=["mortgage"])
_orchestrator: MortgageOrchestrator | None = None
DATA_DIR = Path(__file__).resolve().parents[3] / "data"


class DocumentSubmission(BaseModel):
    document_type: Literal["income", "valuation", "debt"]
    evidence: dict[str, Any]
    received_at: datetime | None = None


def _build_orchestrator() -> MortgageOrchestrator:
    policy_engine = ReviewOnlyPolicyEngine()
    if os.getenv("OPENAI_API_KEY"):
        from src.mortgage.openai_policy import OpenAIPolicyDecisionEngine

        policy_engine = OpenAIPolicyDecisionEngine()
    orchestrator = MortgageOrchestrator(
        policy_engine=policy_engine,
        validation_evidence_provider=lambda _application_id, _documents: ValidationEvidence(
            policy_version="",
            authoritative_rule_results={},
        ),
    )
    _load_seed_applications(orchestrator)
    return orchestrator


def _load_seed_applications(
    orchestrator: MortgageOrchestrator, data_dir: Path = DATA_DIR
) -> None:
    def read_records(filename: str) -> list[dict[str, Any]]:
        with (data_dir / filename).open(encoding="utf-8") as source:
            return json.load(source)

    applications = read_records("applications.json")
    incomes = {item["application_id"]: item for item in read_records("income_data.json")}
    debts = {item["application_id"]: item for item in read_records("debts.json")}
    valuations = {item["property_id"]: item for item in read_records("valuations.json")}

    for application in applications:
        application_id = application["application_id"]
        received_at_value = application.get("documents_present_at")
        received_at = (
            datetime.fromisoformat(received_at_value.replace("Z", "+00:00"))
            if received_at_value
            else None
        )

        income = incomes.get(application_id)
        if income is not None:
            verification_status = income.get("verification_status")
            verified = (
                True if verification_status == "verified"
                else False if verification_status == "rejected"
                else None
            )
            orchestrator.process_document(
                application_id,
                "income",
                {"verified": verified, "annual_income": application.get("annual_income")},
                received_at,
            )

        valuation = valuations.get(application.get("property_id"))
        if valuation is not None:
            valuation_date = valuation.get("valuation_date")
            orchestrator.process_document(
                application_id,
                "valuation",
                {
                    "value": valuation.get("estimated_value"),
                    "valuation_date": valuation_date[:10] if valuation_date else None,
                    "source": valuation.get("source", "unknown"),
                    "cache_hit": bool(valuation.get("cached", False)),
                },
                received_at,
            )

        debt = debts.get(application_id)
        if debt is not None:
            verified = True if debt.get("credit_check_status") == "complete" else None
            orchestrator.process_document(
                application_id,
                "debt",
                {"verified": verified, "monthly_debt": debt.get("monthly_debt_payment")},
                received_at,
            )


def get_orchestrator() -> MortgageOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = _build_orchestrator()
    return _orchestrator


@router.post("/applications/{application_id}/documents")
def receive_document(application_id: str, submission: DocumentSubmission) -> dict[str, Any]:
    try:
        return get_orchestrator().process_document(
            application_id,
            submission.document_type,
            submission.evidence,
            submission.received_at,
        )
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/applications/{application_id}")
def application_status(application_id: str) -> dict[str, Any]:
    result = get_orchestrator().get_application(application_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return result
