import sys
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.core import online_eval


def setup_function():
    online_eval._recent_history.clear()


def test_maybe_grade_passes_evidence_and_narrative_and_flags_low_agreement(monkeypatch):
    monkeypatch.setenv("ONLINE_EVAL_SAMPLE_RATE", "1")
    evidence = {"check_aml_typology": {"flagged": True, "matching_transaction_count": 5}}
    narrative = "No suspicious activity was identified."
    response = SimpleNamespace(
        content='{"score": 3, "reason": "The narrative omits the flagged structuring findings."}',
        cost_usd=0.002,
    )

    with patch.object(online_eval.random, "random", return_value=0.0), patch.object(
        online_eval, "chat_raw", return_value=response
    ) as chat:
        evaluation = online_eval.maybe_grade(evidence, narrative)

    user_message = chat.call_args.kwargs["messages"][1]["content"]
    assert '"flagged": true' in user_message
    assert narrative in user_message
    assert evaluation["score"] == 3
    assert evaluation["low_agreement"] is True
    assert online_eval.rolling_average_score() == 3


def test_sample_rate_can_disable_grading(monkeypatch):
    monkeypatch.setenv("ONLINE_EVAL_SAMPLE_RATE", "0")

    with patch.object(online_eval, "chat_raw") as chat:
        assert online_eval.maybe_grade({}, "narrative") is None

    chat.assert_not_called()


def test_recent_history_is_capped_and_average_uses_latest_window(monkeypatch):
    monkeypatch.setenv("ONLINE_EVAL_SAMPLE_RATE", "1")
    online_eval._recent_history = deque(maxlen=2)
    responses = [
        SimpleNamespace(content=f'{{"score": {score}, "reason": "Reason {score}."}}', cost_usd=0)
        for score in (1, 3, 5)
    ]

    with patch.object(online_eval.random, "random", return_value=0.0), patch.object(
        online_eval, "chat_raw", side_effect=responses
    ):
        for score in (1, 3, 5):
            online_eval.maybe_grade({}, f"narrative {score}")

    assert [item["score"] for item in online_eval.recent_evaluations()] == [3, 5]
    assert online_eval.rolling_average_score(window=2) == 4