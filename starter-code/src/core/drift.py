"""Online drift tracking for SAR narratives and investigation tool usage."""

import math
import os
import threading
from collections import Counter, deque
from statistics import mean
from typing import Optional, Sequence

from src.core.llm_provider import _get_client


def _positive_int_setting(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


_BASELINE_SIZE = _positive_int_setting("DRIFT_BASELINE_SIZE", 5)
_ROLLING_WINDOW_SIZE = _positive_int_setting("DRIFT_ROLLING_WINDOW_SIZE", 10)
_EMBEDDING_MODEL = os.getenv("DRIFT_EMBEDDING_MODEL", "text-embedding-3-small")
_lock = threading.RLock()

_baseline_embeddings: list[list[float]] = []
_baseline_tool_counts: Counter[str] = Counter()
_centroid: Optional[list[float]] = None
_recent_narrative_distances: deque[float] = deque(maxlen=_ROLLING_WINDOW_SIZE)
_recent_tool_sequences: deque[tuple[str, ...]] = deque(maxlen=_ROLLING_WINDOW_SIZE)
_latest_narrative_distance: Optional[float] = None
_latest_tool_usage_tvd: Optional[float] = None
_total_observations = 0
_last_embedding_error: Optional[str] = None


def _embed(narrative: str) -> list[float]:
    response = _get_client().embeddings.create(
        model=_EMBEDDING_MODEL,
        input=narrative,
    )
    return list(response.data[0].embedding)


def _cosine_distance(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("Embedding dimensions changed from the baseline")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    similarity = sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)
    return 1.0 - max(-1.0, min(1.0, similarity))


def _mean_embedding(embeddings: list[list[float]]) -> list[float]:
    return [mean(dimensions) for dimensions in zip(*embeddings)]


def _tool_usage_tvd() -> float:
    rolling_counts = Counter(
        tool_name
        for sequence in _recent_tool_sequences
        for tool_name in sequence
    )
    baseline_total = sum(_baseline_tool_counts.values())
    rolling_total = sum(rolling_counts.values())
    if not baseline_total and not rolling_total:
        return 0.0
    if not baseline_total or not rolling_total:
        return 1.0

    tools = _baseline_tool_counts.keys() | rolling_counts.keys()
    return 0.5 * sum(
        abs(_baseline_tool_counts[tool] / baseline_total - rolling_counts[tool] / rolling_total)
        for tool in tools
    )


def _rounded(value: Optional[float]) -> Optional[float]:
    return round(value, 6) if value is not None else None


def _status_unlocked() -> dict:
    return {
        "baseline_ready": _centroid is not None,
        "baseline_size": _BASELINE_SIZE,
        "baseline_count": len(_baseline_embeddings),
        "total_observations": _total_observations,
        "rolling_window_size": len(_recent_tool_sequences),
        "rolling_window_capacity": _ROLLING_WINDOW_SIZE,
        "narrative_drift_score": _rounded(
            mean(_recent_narrative_distances) if _recent_narrative_distances else None
        ),
        "latest_narrative_cosine_distance": _rounded(_latest_narrative_distance),
        "tool_usage_tvd": _rounded(_latest_tool_usage_tvd),
        "last_embedding_error": _last_embedding_error,
    }


def observe(narrative: str, tool_sequence: Sequence[str]) -> dict:
    """Record one investigation and update drift scores after the baseline."""
    global _centroid, _latest_narrative_distance, _latest_tool_usage_tvd
    global _total_observations, _last_embedding_error

    try:
        embedding = _embed(narrative or "")
    except Exception as exc:  # noqa: BLE001
        with _lock:
            _total_observations += 1
            _last_embedding_error = f"{type(exc).__name__}: {exc}"
            if _centroid is not None:
                _recent_tool_sequences.append(tuple(tool_sequence))
                _latest_tool_usage_tvd = _tool_usage_tvd()
            return _status_unlocked()

    with _lock:
        _total_observations += 1
        _last_embedding_error = None
        tools = tuple(tool_sequence)

        if _centroid is None:
            _baseline_embeddings.append(embedding)
            _baseline_tool_counts.update(tools)
            if len(_baseline_embeddings) == _BASELINE_SIZE:
                _centroid = _mean_embedding(_baseline_embeddings)
            return _status_unlocked()

        _latest_narrative_distance = _cosine_distance(embedding, _centroid)
        _recent_narrative_distances.append(_latest_narrative_distance)
        _recent_tool_sequences.append(tools)
        _latest_tool_usage_tvd = _tool_usage_tvd()
        return _status_unlocked()


def status() -> dict:
    """Return baseline readiness and the latest rolling drift scores."""
    with _lock:
        return _status_unlocked()


def _reset_state() -> None:
    """Reset module state for deterministic tests."""
    global _centroid, _recent_narrative_distances, _recent_tool_sequences
    global _latest_narrative_distance, _latest_tool_usage_tvd
    global _total_observations, _last_embedding_error

    with _lock:
        _baseline_embeddings.clear()
        _baseline_tool_counts.clear()
        _centroid = None
        _recent_narrative_distances = deque(maxlen=_ROLLING_WINDOW_SIZE)
        _recent_tool_sequences = deque(maxlen=_ROLLING_WINDOW_SIZE)
        _latest_narrative_distance = None
        _latest_tool_usage_tvd = None
        _total_observations = 0
        _last_embedding_error = None