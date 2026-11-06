import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.core import agent_loop
from src.core.llm_provider import ModelCallResult, ToolCall
from src.core.pricing import estimate_cost_usd


def test_dated_model_id_uses_configured_pricing():
    assert estimate_cost_usd("gpt-4o-mini-2024-07-18", 1000, 500) == pytest.approx(0.00045)


def test_completed_investigation_records_aggregates_once():
    model_results = [
        ModelCallResult(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call-1",
                    name="lookup_customer_profile",
                    arguments='{"customer_id":"CUST-NOPE"}',
                )
            ],
            finish_reason="tool_calls",
            cost_usd=0.1,
        ),
        ModelCallResult(content="Summary", finish_reason="stop", cost_usd=0.2),
    ]

    with (
        patch.object(agent_loop, "chat_raw", side_effect=model_results),
        patch.object(
            agent_loop,
            "run_sar_drafting_subagent",
            return_value={"cost_usd": 0.03, "sar_narrative": "Summary"},
        ),
        patch.object(agent_loop, "maybe_grade", return_value=None) as maybe_grade,
        patch.object(agent_loop, "observe", return_value={"baseline_ready": False}) as observe,
        patch.object(agent_loop, "record_investigation_turn") as record_turn,
    ):
        agent_loop.run_investigation("CUST-NOPE", verbose=False)

    record_turn.assert_called_once()
    maybe_grade.assert_called_once()
    assert maybe_grade.call_args.args[0]["lookup_customer_profile"]["error"] == (
        "No customer found with id CUST-NOPE"
    )
    assert maybe_grade.call_args.args[1] == "Summary"
    observe.assert_called_once_with("Summary", ["lookup_customer_profile"])
    recorded = record_turn.call_args.kwargs
    assert recorded["duration_ms"] > 0
    assert recorded["cost_usd"] == pytest.approx(0.33)
    assert recorded["tool_failures"] == 1
