import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.core import drift


def setup_function():
    drift._BASELINE_SIZE = 2
    drift._ROLLING_WINDOW_SIZE = 2
    drift._reset_state()


def teardown_function():
    drift._BASELINE_SIZE = 5
    drift._ROLLING_WINDOW_SIZE = 10
    drift._reset_state()


def test_baseline_freezes_and_rolling_scores_update_after_it():
    embeddings = {
        "baseline one": [1.0, 0.0],
        "baseline two": [1.0, 0.0],
        "drift one": [0.0, 1.0],
        "drift two": [-1.0, 0.0],
    }

    with patch.object(drift, "_embed", side_effect=lambda text: embeddings[text]):
        assert drift.observe("baseline one", ["lookup", "history"])["baseline_ready"] is False
        baseline_status = drift.observe("baseline two", ["lookup", "history"])
        assert baseline_status["baseline_ready"] is True
        assert baseline_status["narrative_drift_score"] is None

        first_drift = drift.observe("drift one", ["history"])
        assert first_drift["latest_narrative_cosine_distance"] == 1.0
        assert first_drift["tool_usage_tvd"] == 0.5

        second_drift = drift.observe("drift two", ["lookup"])

    assert second_drift["latest_narrative_cosine_distance"] == 2.0
    assert second_drift["narrative_drift_score"] == 1.5
    assert second_drift["tool_usage_tvd"] == 0.0
    assert second_drift["rolling_window_size"] == 2


def test_embedding_failure_does_not_break_investigation_or_status():
    with patch.object(drift, "_embed", side_effect=RuntimeError("embedding unavailable")):
        current_status = drift.observe("narrative", ["lookup"])

    assert current_status["baseline_ready"] is False
    assert current_status["last_embedding_error"] == "RuntimeError: embedding unavailable"