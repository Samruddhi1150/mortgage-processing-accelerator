from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from time import perf_counter
from typing import Any, Callable, Protocol

from opentelemetry.trace import Status, StatusCode

from src.core.otel_setup import get_meter, get_tracer
from src.mortgage.decisioning import (
    DeterministicValidationGate,
    PolicyAssessment,
    ValidationEvidence,
)


REQUIRED_DOCUMENTS = ("income", "valuation", "debt")
STAGE_NAMES = {
    "income": "income_check",
    "valuation": "valuation_check",
    "debt": "debt_check",
}
_TERMINAL_DECISIONS = {"automated_offer", "underwriter_review", "validated_decline"}

_meter = get_meter(__name__)
_document_counter = _meter.create_counter(
    "mortgage.documents.received", unit="{document}", description="Mortgage evidence documents received"
)
_stage_duration = _meter.create_histogram(
    "mortgage.stage.duration", unit="ms", description="Duration of mortgage evidence stages"
)
_stage_failure_counter = _meter.create_counter(
    "mortgage.stage.failures", unit="{failure}", description="Mortgage evidence stage failures"
)
_stage_alert_counter = _meter.create_counter(
    "mortgage.stage.alerts", unit="{alert}", description="Mortgage evidence freshness and latency alerts"
)
_decision_duration = _meter.create_histogram(
    "mortgage.time_to_decision", unit="s", description="Time from final evidence receipt to decision route"
)


@dataclass(frozen=True)
class StageOutcome:
    status: str
    conditions: tuple[str, ...] = ()


@dataclass
class ApplicationState:
    documents: dict[str, dict[str, Any]] = field(default_factory=dict)
    received_at: dict[str, datetime] = field(default_factory=dict)
    stage_outcomes: dict[str, StageOutcome] = field(default_factory=dict)
    latest_decision: dict[str, Any] = field(default_factory=dict)


class PolicyDecisionEngine(Protocol):
    def assess(
        self,
        evidence: dict[str, dict[str, Any]],
        policy_version: str,
        approved_policy_rules: dict[str, str],
        approved_reason_descriptions: dict[str, str],
    ) -> PolicyAssessment: ...


class ReviewOnlyPolicyEngine:
    def assess(
        self,
        evidence: dict[str, dict[str, Any]],
        policy_version: str,
        approved_policy_rules: dict[str, str],
        approved_reason_descriptions: dict[str, str],
    ) -> PolicyAssessment:
        return PolicyAssessment(
            recommendation="underwriter_review",
            policy_version=policy_version,
            rule_results={},
            explanation="OpenAI policy decision engine is not configured.",
        )


class StateAggregator:
    def evaluate(self, application: ApplicationState) -> dict[str, Any]:
        missing = [doc for doc in REQUIRED_DOCUMENTS if doc not in application.documents]
        conditions = [f"Awaiting {doc} documentation" for doc in missing]
        for document_type in REQUIRED_DOCUMENTS:
            outcome = application.stage_outcomes.get(document_type)
            if outcome is not None:
                conditions.extend(outcome.conditions)

        if missing or any(
            application.stage_outcomes.get(doc, StageOutcome("incomplete")).status
            in {"incomplete", "tool_error"}
            for doc in REQUIRED_DOCUMENTS
        ):
            return {"status": "pending", "outstanding_conditions": conditions}
        if any(
            application.stage_outcomes[doc].status != "complete"
            for doc in REQUIRED_DOCUMENTS
        ):
            return {
                "status": "underwriter_review",
                "outstanding_conditions": conditions or ["Evidence requires human review"],
            }
        return {"status": "ready"}


class MortgageOrchestrator:
    def __init__(
        self,
        policy_engine: PolicyDecisionEngine | None = None,
        validation_evidence_provider: Callable[
            [str, dict[str, dict[str, Any]]], ValidationEvidence
        ]
        | None = None,
        stage_tools: dict[str, Callable[[dict[str, Any]], StageOutcome]] | None = None,
        valuation_max_age: timedelta = timedelta(days=30),
        slow_stage_threshold_ms: float = 2000.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.policy_engine = policy_engine or ReviewOnlyPolicyEngine()
        self.validation_evidence_provider = (
            validation_evidence_provider or self._unconfigured_validation_evidence
        )
        self.valuation_max_age = valuation_max_age
        self.slow_stage_threshold_ms = slow_stage_threshold_ms
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.stage_tools = stage_tools or {
            "income": self._check_income,
            "valuation": self._check_valuation,
            "debt": self._check_debt,
        }
        self.aggregator = StateAggregator()
        self.validation_gate = DeterministicValidationGate()
        self.applications: dict[str, ApplicationState] = {}
        self.tracer = get_tracer(__name__)

    def process_document(
        self,
        application_id: str,
        document_type: str,
        evidence: dict[str, Any],
        received_at: datetime | None = None,
    ) -> dict[str, Any]:
        if document_type not in REQUIRED_DOCUMENTS:
            raise ValueError(f"Unsupported document type: {document_type}")
        if not isinstance(evidence, dict):
            raise TypeError("Evidence must be an object")

        state = self.applications.setdefault(application_id, ApplicationState())
        state.documents[document_type] = evidence
        state.received_at[document_type] = self._normalize_time(received_at or self.clock())
        _document_counter.add(1, {"document_type": document_type})

        with self.tracer.start_as_current_span("mortgage.document_ingest") as root_span:
            root_span.set_attribute("document.type", document_type)
            root_span.set_attribute("evidence.source", str(evidence.get("source", "unknown")))
            root_span.set_attribute("evidence.cache_hit", bool(evidence.get("cache_hit", False)))
            outcome = self._run_stage(application_id, document_type, evidence)
            state.stage_outcomes[document_type] = outcome
            with self.tracer.start_as_current_span("mortgage.state_aggregator") as aggregate_span:
                decision = self.aggregator.evaluate(state)
                aggregate_span.set_attribute("application.state", decision["status"])

            if decision["status"] == "ready":
                decision = self._run_decisioning(application_id, state)
            state.latest_decision = decision

            if decision.get("status") in _TERMINAL_DECISIONS:
                last_evidence_at = max(state.received_at.values())
                elapsed = max(0.0, (self._normalize_time(self.clock()) - last_evidence_at).total_seconds())
                decision["processing_seconds"] = elapsed
                _decision_duration.record(
                    elapsed,
                    {"outcome": decision["status"], "excludes_applicant_wait": "true"},
                )
                state.latest_decision = decision

        return {"application_id": application_id, **decision}

    def get_application(self, application_id: str) -> dict[str, Any] | None:
        state = self.applications.get(application_id)
        if state is None:
            return None
        return {
            "application_id": application_id,
            "received_documents": sorted(state.documents),
            "stage_status": {
                document_type: outcome.status
                for document_type, outcome in state.stage_outcomes.items()
            },
            **state.latest_decision,
        }

    def _run_stage(
        self, application_id: str, document_type: str, evidence: dict[str, Any]
    ) -> StageOutcome:
        stage_name = STAGE_NAMES[document_type]
        started = perf_counter()
        stage_status = "tool_error"
        with self.tracer.start_as_current_span(stage_name) as span:
            span.set_attribute("document.type", document_type)
            span.set_attribute("evidence.source", str(evidence.get("source", "unknown")))
            span.set_attribute("evidence.cache_hit", bool(evidence.get("cache_hit", False)))
            try:
                outcome = self.stage_tools[document_type](evidence)
                stage_status = outcome.status
                span.set_attribute("stage.status", outcome.status)
                if outcome.conditions:
                    span.set_attribute("stage.conditions", list(outcome.conditions))
                if outcome.status in {"stale", "incomplete"}:
                    alert_name = "stale_valuation" if outcome.status == "stale" else "incomplete_stage_data"
                    _stage_alert_counter.add(
                        1, {"stage": stage_name, "alert_name": alert_name}
                    )
                return outcome
            except TimeoutError as error:
                span.record_exception(error)
                span.set_status(Status(StatusCode.ERROR, "stage timeout"))
                stage_status = "tool_error"
                _stage_failure_counter.add(1, {"stage": stage_name, "failure": "timeout"})
                _stage_alert_counter.add(1, {"stage": stage_name, "alert_name": "stage_timeout"})
                return StageOutcome("tool_error", (f"{stage_name} timed out; retry required",))
            except Exception as error:
                span.record_exception(error)
                span.set_status(Status(StatusCode.ERROR, "stage tool error"))
                stage_status = "tool_error"
                _stage_failure_counter.add(1, {"stage": stage_name, "failure": "tool_error"})
                _stage_alert_counter.add(1, {"stage": stage_name, "alert_name": "stage_tool_error"})
                return StageOutcome(
                    "tool_error",
                    (f"{stage_name} failed ({type(error).__name__}); retry required",),
                )
            finally:
                elapsed_ms = (perf_counter() - started) * 1000
                _stage_duration.record(
                    elapsed_ms, {"stage": stage_name, "status": stage_status}
                )
                if elapsed_ms > self.slow_stage_threshold_ms:
                    span.set_attribute("stage.slow", True)
                    _stage_alert_counter.add(
                        1, {"stage": stage_name, "alert_name": "stage_latency_high"}
                    )

    def _run_decisioning(
        self, application_id: str, state: ApplicationState
    ) -> dict[str, Any]:
        with self.tracer.start_as_current_span("mortgage.conditional_decision") as policy_span:
            policy_span.set_attribute("policy.engine", type(self.policy_engine).__name__)
            try:
                validation = self.validation_evidence_provider(application_id, state.documents)
                assessment = self.policy_engine.assess(
                    state.documents,
                    validation.policy_version,
                    validation.approved_policy_rules,
                    validation.approved_reason_descriptions,
                )
            except Exception as error:
                policy_span.record_exception(error)
                policy_span.set_status(Status(StatusCode.ERROR, "policy assessment failed"))
                return {
                    "status": "underwriter_review",
                    "auto_explainer": "Policy assessment failed; human review is required.",
                    "outstanding_conditions": ["Retry policy assessment after the incident is resolved"],
                }

        with self.tracer.start_as_current_span("mortgage.deterministic_validation") as gate_span:
            try:
                decision = self.validation_gate.validate(assessment, validation)
                gate_span.set_attribute("validation.outcome", str(decision["status"]))
                return decision
            except Exception as error:
                gate_span.record_exception(error)
                gate_span.set_status(Status(StatusCode.ERROR, "deterministic validation failed"))
                return {
                    "status": "underwriter_review",
                    "auto_explainer": "Deterministic validation failed; human review is required.",
                    "outstanding_conditions": ["Retry validation after the incident is resolved"],
                }

    def _check_income(self, evidence: dict[str, Any]) -> StageOutcome:
        if not isinstance(evidence.get("verified"), bool) or not self._positive_number(
            evidence.get("annual_income")
        ):
            return StageOutcome(
                "incomplete", ("Income evidence needs verified and positive annual_income",)
            )
        if not evidence["verified"]:
            return StageOutcome("refer", ("Income evidence requires underwriter review",))
        return StageOutcome("complete")

    def _check_valuation(self, evidence: dict[str, Any]) -> StageOutcome:
        valuation_date = self._parse_date(evidence.get("valuation_date"))
        if not self._positive_number(evidence.get("value")) or valuation_date is None:
            return StageOutcome(
                "incomplete", ("Valuation evidence needs positive value and valuation_date",)
            )
        age = self._normalize_time(self.clock()).date() - valuation_date
        if age.days < 0:
            return StageOutcome("incomplete", ("Valuation date cannot be in the future",))
        if age > self.valuation_max_age:
            return StageOutcome(
                "stale", (f"Valuation is {age.days} days old; obtain a current report",)
            )
        return StageOutcome("complete")

    def _check_debt(self, evidence: dict[str, Any]) -> StageOutcome:
        if not isinstance(evidence.get("verified"), bool) or not self._nonnegative_number(
            evidence.get("monthly_debt")
        ):
            return StageOutcome(
                "incomplete", ("Debt evidence needs verified and nonnegative monthly_debt",)
            )
        if not evidence["verified"]:
            return StageOutcome("refer", ("Debt evidence requires underwriter review",))
        return StageOutcome("complete")

    @staticmethod
    def _unconfigured_validation_evidence(
        application_id: str, documents: dict[str, dict[str, Any]]
    ) -> ValidationEvidence:
        return ValidationEvidence(policy_version="", authoritative_rule_results={})

    @staticmethod
    def _positive_number(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0

    @staticmethod
    def _nonnegative_number(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0

    @staticmethod
    def _parse_date(value: Any) -> date | None:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError:
                return None
        return None

    @staticmethod
    def _normalize_time(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
