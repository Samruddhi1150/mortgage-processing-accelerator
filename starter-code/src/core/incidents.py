"""
Three seeded inconsistencies in the Anvesh fraud/AML investigation agent.

Each one is "live" in the code already — nothing here is a toggle the
agent checks for honesty. Calling seed_incident(n) just turns on a
specific, realistic bug class that a production agent could genuinely
ship with. The whole point of this repo is that NONE of them are visible
without building the observability stack described in the companion
outline document — there is no logging, no tracing, no dashboard here yet.

Call seed_incident(n) / clear_incident() from app.py's incident endpoints.
reveal_incident(n) is the answer key — look at it only after you've tried
to diagnose the incident yourself using whatever you've built so far.
"""

CURRENT_INCIDENT = {"n": 0}


def seed_incident(n: int) -> dict:
    if n not in (1, 2, 3):
        return {"error": f"Unknown incident {n}. Known: 1, 2, 3."}
    CURRENT_INCIDENT["n"] = n
    return {"seeded": n}


def clear_incident() -> dict:
    CURRENT_INCIDENT["n"] = 0
    return {"cleared": True}


def incident_status() -> dict:
    # Deliberately doesn't say WHICH incident — same honesty rule as the
    # rest of this training series: you have to find it, not be told it.
    return {"incident_active": CURRENT_INCIDENT["n"] != 0}


def effective_model(requested_model: str) -> str:
    """
    Incident 2 — silent model drift. When active, every call that asks
    for gpt-4o-mini is actually served by gpt-4o instead, with no error,
    no log line, and no attribute that looks obviously wrong on its own —
    the caller's OWN requested-model value is unaffected, only what
    actually gets sent to the API changes.
    """
    if CURRENT_INCIDENT["n"] == 2 and requested_model == "gpt-4o-mini":
        return "gpt-4o"
    return requested_model


def effective_typology(requested_typology: str) -> str:
    """
    Incident 1 — tool misrouting. When active, every call to
    check_aml_typology silently runs the 'rapid_fund_rotation' rule
    instead of whatever typology was actually requested. The function
    call still looks correct — same tool name, same arguments logged by
    the model — only the rule actually executed is wrong. This is exactly
    the kind of bug that single-trace inspection of "which tool was
    called" alone will miss, because the tool WAS called correctly; only
    its internal routing is broken.
    """
    if CURRENT_INCIDENT["n"] == 1:
        return "rapid_fund_rotation"
    return requested_typology


def sub_agent_context_enabled() -> bool:
    """
    Incident 3 — sub-agent context loss. When active, the SAR-drafting
    sub-agent (src/core/sub_agent.py) is NOT given the investigation
    evidence gathered by the main loop — only the bare customer_id. It
    still returns a confident, well-formatted SAR narrative; the narrative
    just doesn't reflect any of the actual findings. On a single trace the
    sub-agent call looks like a normal, successful delegation.
    """
    return CURRENT_INCIDENT["n"] != 3  # True = pass context through normally


REVEAL = {
    1: {
        "name": "tool_misrouting",
        "root_cause": "check_aml_typology() is silently routed to always run the "
                       "'rapid_fund_rotation' rule, regardless of the typology argument "
                       "the model actually requested — most visibly, it never flags "
                       "CUST-10587's structuring pattern anymore.",
        "why_hard_to_catch_from_one_trace": "The tool-call span still shows the correct "
                       "tool name AND the correct 'typology': 'structuring' argument — "
                       "the mismatch is entirely inside the function body, invisible to "
                       "anything that only inspects what the model asked for.",
        "what_catches_it": "An outcome-eval / trajectory check comparing the typology "
                            "argument requested against the typology actually evaluated "
                            "inside check_aml_typology's own return value — or simply "
                            "noticing CUST-10587 stops getting flagged.",
    },
    2: {
        "name": "silent_model_drift",
        "root_cause": "incidents.effective_model() swaps every gpt-4o-mini request for "
                       "gpt-4o before the API call is made.",
        "why_hard_to_catch_from_one_trace": "Whatever attribute records the REQUESTED "
                       "model will still say gpt-4o-mini; only the attribute recording "
                       "the model the API actually RESPONDED with will disagree — and "
                       "nothing captures that distinction until you instrument it.",
        "what_catches_it": "A model-version-mismatch alert comparing requested vs. served "
                            "model, or a cost-spike alert (gpt-4o costs ~17x more per "
                            "token than gpt-4o-mini).",
    },
    3: {
        "name": "sub_agent_context_loss",
        "root_cause": "run_sar_drafting_subagent() is called with only customer_id — the "
                       "typology findings, watchlist hits, and transaction evidence from "
                       "the main investigation loop are never passed into the sub-agent's "
                       "prompt.",
        "why_hard_to_catch_from_one_trace": "The sub-agent call succeeds, returns "
                       "finish_reason='stop', and produces a fluent, well-formatted SAR "
                       "narrative — it just doesn't mention any evidence that was actually "
                       "found, because it was never told. Nothing about the SPAN SHAPE is "
                       "wrong; only the narrative's content is.",
        "what_catches_it": "A sampled online-eval judge comparing the SAR narrative "
                            "against the evidence actually gathered, or a human reviewer's "
                            "thumbs-down feeding the annotation queue.",
    },
}


def reveal_incident(n: int) -> dict:
    info = REVEAL.get(n)
    if info is None:
        return {"error": f"Unknown incident {n}. Known: 1, 2, 3."}
    return info
