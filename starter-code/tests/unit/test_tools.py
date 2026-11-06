"""
Unit tests for the tool functions only — no OPENAI_API_KEY required, since
these test the deterministic Python logic the model calls INTO, not the
model call itself. Run with: pytest tests/unit -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, for `src.` imports

from src.tools.investigation_tools import (
    lookup_customer_profile, get_transaction_history,
    check_aml_typology, screen_counterparties,
)


def test_lookup_customer_profile_known_customer():
    profile = lookup_customer_profile("CUST-10587")
    assert profile["name"] == "S. Okafor"
    assert profile["kyc_risk_rating"] == "high"


def test_lookup_customer_profile_unknown_customer():
    result = lookup_customer_profile("CUST-NOPE")
    assert "error" in result


def test_get_transaction_history_respects_lookback_window():
    wide = get_transaction_history("CUST-10587", lookback_days=10)
    narrow = get_transaction_history("CUST-10587", lookback_days=1)
    assert len(narrow["transactions"]) <= len(wide["transactions"])


def test_structuring_typology_flags_the_designed_pattern():
    result = check_aml_typology("CUST-10587", typology="structuring")
    assert result["flagged"] is True
    assert result["matching_transaction_count"] >= 3


def test_structuring_typology_does_not_flag_clean_customer():
    result = check_aml_typology("CUST-10234", typology="structuring")
    assert result["flagged"] is False


def test_screen_counterparties_finds_watchlist_hit():
    result = screen_counterparties("CUST-10587")
    hit_names = {hit["entity_name"] for hit in result["watchlist_hits"]}
    assert "Orion Trading FZE" in hit_names


def test_screen_counterparties_clean_customer_has_no_hits():
    result = screen_counterparties("CUST-10234")
    assert result["watchlist_hits"] == []
