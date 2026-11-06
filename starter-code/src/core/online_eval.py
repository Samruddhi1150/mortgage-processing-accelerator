"""Sampled online evaluation of SAR narratives against gathered evidence."""

import json
import os
import random
from collections import deque
from datetime import datetime, timezone
from statistics import mean
from typing import Optional

from src.core.llm_provider import chat_raw

_DEFAULT_HISTORY_LIMIT = 100

JUDGE_SYSTEM_PROMPT = """You are an independent quality judge for AML investigation SARs.
Compare the SAR narrative against the gathered_evidence dictionary specifically.
Score agreement from 1 to 5: 5 means all material findings are accurately
represented; 3 means important findings are missing or unclear; 1 means the
narrative omits or contradicts most material findings. Evidence includes tool
results such as flagged typologies, matching transactions, and watchlist hits.
When any of those material findings appear in gathered_evidence but not in the
narrative, lower the score and name the omitted finding in one concise sentence.
Return only a JSON object with an integer score from 1 to 5 and a one-line reason,
using exactly these keys: {"score": 1, "reason": "..."}."""


def _history_limit() -> int:
    try:
        return max(1, int(os.getenv("ONLINE_EVAL_HISTORY_LIMIT", str(_DEFAULT_HISTORY_LIMIT))))
    except ValueError:
        return _DEFAULT_HISTORY_LIMIT


_recent_history = deque(maxlen=_history_limit())


def _sample_rate() -> float:
    try:
        rate = float(os.getenv("ONLINE_EVAL_SAMPLE_RATE", "1.0"))
    except ValueError:
        return 0.0
    return min(1.0, max(0.0, rate))


def maybe_grade(gathered_evidence: dict, sar_narrative: Optional[str]) -> Optional[dict]:
    """Grade this investigation when selected by the configured sample rate."""
    if random.random() >= _sample_rate():
        return None

    try:
        result = chat_raw(
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "gathered_evidence:\n"
                        f"{json.dumps(gathered_evidence, ensure_ascii=True, default=str)}\n\n"
                        "sar_narrative:\n"
                        f"{sar_narrative or ''}"
                    ),
                },
            ],
            temperature=0,
        )
        parsed = json.loads(result.content or "")
        score = parsed["score"]
        reason = " ".join(str(parsed["reason"]).split())
        if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5 or not reason:
            return None
    except Exception:
        return None

    evaluation = {
        "score": score,
        "reason": reason,
        "low_agreement": score <= 3,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "cost_usd": result.cost_usd,
    }
    _recent_history.append(evaluation)
    return evaluation.copy()


def recent_evaluations() -> list[dict]:
    return [evaluation.copy() for evaluation in _recent_history]


def rolling_average_score(window: int = 20) -> Optional[float]:
    if window <= 0 or not _recent_history:
        return None
    scores = [evaluation["score"] for evaluation in list(_recent_history)[-window:]]
    return round(mean(scores), 2)