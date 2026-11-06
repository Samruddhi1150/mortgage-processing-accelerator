"""
A delegated sub-agent call — the main investigation loop (agent_loop.py)
hands off to this one once it has gathered evidence, asking it to draft a
formal SAR (Suspicious Activity Report) narrative for a human reviewer.

This is a SEPARATE model call with its OWN system prompt and its own
conversation history — not a continuation of the main loop's messages
list. That separateness is exactly what makes incident 3 possible: the
sub-agent only knows what it's explicitly told in its own prompt.
"""

from typing import Optional

from src.core.llm_provider import chat_raw
from src.core.incidents import sub_agent_context_enabled
from src.core.otel_setup import get_tracer

SAR_SYSTEM_PROMPT = """You are a SAR (Suspicious Activity Report) drafting
assistant for Lloyds Financial (training scenario). Given the evidence
provided, write a short, formal SAR narrative suitable for a human
compliance reviewer: what was found, which typology was flagged (if any),
whether any counterparty is on the watchlist, and a recommended next
action. If no evidence is provided, say plainly that no findings were
supplied rather than inventing any.
"""


def run_sar_drafting_subagent(customer_id: str, investigation_evidence: Optional[dict] = None) -> dict:
    with get_tracer(__name__).start_as_current_span("sar_drafting_subagent"):
        return _run_sar_drafting_subagent(customer_id, investigation_evidence)


def _run_sar_drafting_subagent(customer_id: str, investigation_evidence: Optional[dict] = None) -> dict:
    """
    Delegate SAR drafting to a second model call.

    investigation_evidence should be the typology-check and watchlist
    results gathered by the main loop. Incident 3 (sub_agent_context_loss)
    silently drops it before it reaches the sub-agent's prompt — the call
    still succeeds and returns a fluent narrative either way.
    """
    if sub_agent_context_enabled():
        evidence_text = (
            f"Evidence gathered by the investigation:\n{investigation_evidence}"
            if investigation_evidence else
            "No evidence was supplied to this sub-agent."
        )
    else:
        # Incident 3: the evidence argument is accepted but never used.
        evidence_text = "No evidence was supplied to this sub-agent."

    result = chat_raw(
        messages=[
            {"role": "system", "content": SAR_SYSTEM_PROMPT},
            {"role": "user", "content": f"customer_id: {customer_id}\n\n{evidence_text}"},
        ],
    )

    return {
        "customer_id": customer_id,
        "sar_narrative": result.content,
        "requested_model": result.requested_model,
        "served_model": result.served_model,
        "cost_usd": result.cost_usd,
        "evidence_was_passed": investigation_evidence is not None and sub_agent_context_enabled(),
    }
