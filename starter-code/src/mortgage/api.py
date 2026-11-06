from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.mortgage.decisioning import ValidationEvidence
from src.mortgage.workflow import MortgageOrchestrator, ReviewOnlyPolicyEngine


router = APIRouter(prefix="/mortgage", tags=["mortgage"])
_orchestrator: MortgageOrchestrator | None = None


class DocumentSubmission(BaseModel):
    document_type: Literal["income", "valuation", "debt"]
    evidence: dict[str, Any]
    received_at: datetime | None = None


def _build_orchestrator() -> MortgageOrchestrator:
    policy_engine = ReviewOnlyPolicyEngine()
    if os.getenv("OPENAI_API_KEY"):
        from src.mortgage.openai_policy import OpenAIPolicyDecisionEngine

        policy_engine = OpenAIPolicyDecisionEngine()
    return MortgageOrchestrator(
        policy_engine=policy_engine,
        validation_evidence_provider=lambda _application_id, _documents: ValidationEvidence(
            policy_version="",
            authoritative_rule_results={},
        ),
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
