"""
Tool implementations for the fraud/AML transaction-pattern investigation agent.

Each tool is a plain Python function plus a matching OpenAI function-calling
schema entry in TOOL_SCHEMAS. This is the "tool loop" half of Day 1 — the
model decides WHICH of these to call and in WHAT order; none of the
investigation logic lives in the prompt.
"""

from datetime import datetime, timedelta

from src.data.mock_store import CUSTOMERS, TRANSACTIONS, WATCHLIST, TYPOLOGIES
from src.core.incidents import effective_typology
from src.core.otel_setup import get_tracer
from functools import wraps


def _traced_tool(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        with get_tracer(__name__).start_as_current_span(function.__name__):
            return function(*args, **kwargs)

    return wrapper


@_traced_tool
def lookup_customer_profile(customer_id: str) -> dict:
    """Return KYC profile fields for a customer_id."""
    profile = CUSTOMERS.get(customer_id)
    if profile is None:
        return {"error": f"No customer found with id {customer_id}"}
    return profile


@_traced_tool
def get_transaction_history(customer_id: str, lookback_days: int = 7) -> dict:
    """Return this customer's transactions within the last `lookback_days` days."""
    txns = TRANSACTIONS.get(customer_id, [])
    cutoff = datetime(2026, 10, 20, 9, 0, 0) - timedelta(days=lookback_days)
    recent = [t for t in txns if datetime.fromisoformat(t["timestamp"]) >= cutoff]
    return {"customer_id": customer_id, "lookback_days": lookback_days, "transactions": recent}


@_traced_tool
def check_aml_typology(customer_id: str, typology: str = "structuring") -> dict:
    """
    Run a simple rule check for a named AML typology ('structuring' or
    'rapid_fund_rotation') against this customer's recent transactions.
    """
    requested_typology = typology
    typology = effective_typology(typology)  # <- incident 1 lives in this one call

    rule = TYPOLOGIES.get(typology)
    if rule is None:
        return {"error": f"Unknown typology '{typology}'. Known: {list(TYPOLOGIES.keys())}"}

    txns = TRANSACTIONS.get(customer_id, [])

    if typology == "structuring":
        lookback = timedelta(days=rule["lookback_days"])
        cutoff = datetime(2026, 10, 20, 9, 0, 0) - lookback
        candidates = [
            t for t in txns
            if t["type"] == "debit"
            and datetime.fromisoformat(t["timestamp"]) >= cutoff
            and t["amount_gbp"] < rule["threshold_gbp"]
        ]
        flagged = len(candidates) >= rule["min_transaction_count"]
        return {
            "requested_typology": requested_typology,
            "typology": "structuring",
            "flagged": flagged,
            "matching_transaction_count": len(candidates),
            "threshold_gbp": rule["threshold_gbp"],
            "lookback_days": rule["lookback_days"],
            "matching_transactions": candidates,
        }

    if typology == "rapid_fund_rotation":
        lookback = timedelta(hours=rule["lookback_hours"])
        cutoff = datetime(2026, 10, 20, 9, 0, 0) - lookback
        candidates = [t for t in txns if datetime.fromisoformat(t["timestamp"]) >= cutoff]
        return {
            "requested_typology": requested_typology,
            "typology": "rapid_fund_rotation",
            "flagged": len(candidates) >= 3,
            "matching_transaction_count": len(candidates),
            "lookback_hours": rule["lookback_hours"],
            "matching_transactions": candidates,
        }

    return {"error": "unhandled typology"}


@_traced_tool
def screen_counterparties(customer_id: str) -> dict:
    """Fuzzy-match this customer's transaction counterparties against the mock watchlist."""
    txns = TRANSACTIONS.get(customer_id, [])
    counterparties = {t["counterparty"] for t in txns}
    hits = [w for w in WATCHLIST if w["entity_name"] in counterparties]
    return {"customer_id": customer_id, "counterparties_checked": sorted(counterparties), "watchlist_hits": hits}


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_customer_profile",
            "description": "Look up a customer's KYC profile (name, account type, risk rating, country, account age) by customer_id.",
            "parameters": {
                "type": "object",
                "properties": {"customer_id": {"type": "string", "description": "e.g. CUST-10587"}},
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_transaction_history",
            "description": "Get a customer's transaction history for a given lookback window in days.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string"},
                    "lookback_days": {"type": "integer", "description": "Default 7"},
                },
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_aml_typology",
            "description": "Run a rule-based AML typology check ('structuring' or 'rapid_fund_rotation') against a customer's recent transactions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string"},
                    "typology": {"type": "string", "enum": ["structuring", "rapid_fund_rotation"]},
                },
                "required": ["customer_id", "typology"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screen_counterparties",
            "description": "Screen a customer's transaction counterparties against the sanctions/adverse-media watchlist.",
            "parameters": {
                "type": "object",
                "properties": {"customer_id": {"type": "string"}},
                "required": ["customer_id"],
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "lookup_customer_profile": lookup_customer_profile,
    "get_transaction_history": get_transaction_history,
    "check_aml_typology": check_aml_typology,
    "screen_counterparties": screen_counterparties,
}
