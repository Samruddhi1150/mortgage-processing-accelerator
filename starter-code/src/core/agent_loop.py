"""
The tool loop, extended with one more step: once the model has finished
gathering evidence (no more tool calls requested), delegate to the
SAR-drafting sub-agent (src/core/sub_agent.py) to produce the final
reviewer-facing narrative. Two separate model calls make up one
investigation: the tool-calling loop, then the hand-off.
"""

import json
import time

from src.core.llm_provider import chat_raw, DEFAULT_MODEL
from src.core.drift import observe
from src.core.metrics import record_investigation_turn
from src.core.online_eval import maybe_grade
from src.core.sub_agent import run_sar_drafting_subagent
from src.tools.investigation_tools import TOOL_SCHEMAS, TOOL_FUNCTIONS
from src.core.otel_setup import get_tracer

SYSTEM_PROMPT = """You are Anvesh, a fraud/AML transaction-pattern investigation
assistant for Lloyds Financial (training scenario). Given a customer_id to
investigate, use the available tools to: (1) look up the customer's KYC
profile, (2) pull their recent transaction history, (3) run at least one AML
typology check relevant to what the transaction history shows, and (4)
screen their counterparties against the watchlist. Once you have gathered
that evidence, summarize your findings in a short internal note — you do
not need to write the formal SAR yourself, a specialist will draft that
from your findings.
"""

MAX_TURNS = 6


def run_investigation(customer_id: str, model: str = DEFAULT_MODEL, verbose: bool = True) -> dict:
    with get_tracer(__name__).start_as_current_span("investigation"):
        return _run_investigation(customer_id, model=model, verbose=verbose)


def _run_investigation(customer_id: str, model: str = DEFAULT_MODEL, verbose: bool = True) -> dict:
    started_at = time.perf_counter()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Investigate customer_id: {customer_id}"},
    ]

    call_log = []
    final_summary = None
    gathered_evidence = {}
    tool_failure_count = 0

    for turn in range(1, MAX_TURNS + 1):
        result = chat_raw(messages, tools=TOOL_SCHEMAS, model=model)

        call_log.append({
            "turn": turn,
            "finish_reason": result.finish_reason,
            "requested_model": result.requested_model,
            "served_model": result.served_model,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "cost_usd": round(result.cost_usd, 6),
            "duration_ms": round(result.duration_ms, 1),
            "tool_calls_requested": [tc.name for tc in result.tool_calls],
        })

        if verbose:
            print(f"[turn {turn}] finish_reason={result.finish_reason} "
                  f"tool_calls={[tc.name for tc in result.tool_calls]} "
                  f"requested={result.requested_model} served={result.served_model} "
                  f"cost_usd={result.cost_usd:.6f}")

        if result.finish_reason == "tool_calls" and result.tool_calls:
            messages.append({
                "role": "assistant",
                "content": result.content,
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.name, "arguments": tc.arguments}}
                    for tc in result.tool_calls
                ],
            })
            for tc in result.tool_calls:
                fn = TOOL_FUNCTIONS.get(tc.name)
                try:
                    args = json.loads(tc.arguments)
                    tool_result = fn(**args) if fn else {"error": f"unknown tool {tc.name}"}
                except Exception as exc:  # noqa: BLE001
                    tool_result = {"error": str(exc)}

                if isinstance(tool_result, dict) and "error" in tool_result:
                    tool_failure_count += 1

                gathered_evidence[tc.name] = tool_result

                if verbose:
                    print(f"    -> {tc.name}({args}) = {json.dumps(tool_result)[:200]}")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(tool_result),
                })
            continue

        final_summary = result.content
        break

    if verbose:
        print("[delegation] handing off to SAR-drafting sub-agent...")
    sar = run_sar_drafting_subagent(customer_id, investigation_evidence=gathered_evidence)
    online_eval = maybe_grade(gathered_evidence, sar["sar_narrative"])
    drift_status = observe(
        sar["sar_narrative"],
        [tool_name for call in call_log for tool_name in call["tool_calls_requested"]],
    )

    total_cost_usd = (
        sum(c["cost_usd"] for c in call_log)
        + sar["cost_usd"]
        + (online_eval["cost_usd"] if online_eval else 0)
    )
    record_investigation_turn(
        duration_ms=(time.perf_counter() - started_at) * 1000,
        cost_usd=total_cost_usd,
        tool_failures=tool_failure_count,
    )

    return {
        "customer_id": customer_id,
        "internal_summary": final_summary,
        "gathered_evidence": gathered_evidence,
        "sar": sar,
        "online_eval": online_eval,
        "drift": drift_status,
        "turns_used": len(call_log),
        "total_cost_usd": round(total_cost_usd, 6),
        "call_log": call_log,
    }
