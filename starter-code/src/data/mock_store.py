"""
Mock data for the fraud/AML transaction-pattern investigation scenario.
Lloyds Financial (training scenario) — three customers, their recent
transaction history, and a mock sanctions/watchlist table. No real data.
"""

from datetime import datetime, timedelta

_NOW = datetime(2026, 10, 20, 9, 0, 0)

CUSTOMERS = {
    "CUST-10234": {
        "customer_id": "CUST-10234",
        "name": "R. Mehta",
        "account_type": "Premier Current Account",
        "kyc_risk_rating": "medium",
        "country_of_residence": "UK",
        "account_opened": "2021-03-14",
    },
    "CUST-10587": {
        "customer_id": "CUST-10587",
        "name": "S. Okafor",
        "account_type": "Business Current Account",
        "kyc_risk_rating": "high",
        "country_of_residence": "UK",
        "account_opened": "2024-11-02",
    },
    "CUST-10842": {
        "customer_id": "CUST-10842",
        "name": "A. Lindqvist",
        "account_type": "Standard Current Account",
        "kyc_risk_rating": "low",
        "country_of_residence": "UK",
        "account_opened": "2018-06-30",
    },
}

# Deliberately shaped so CUST-10587 looks like a structuring pattern
# (many sub-threshold transfers, just under the 10,000 GBP reporting line,
# to a small rotating set of counterparties over a few days).
TRANSACTIONS = {
    "CUST-10234": [
        {"txn_id": "TXN-88291", "timestamp": (_NOW - timedelta(days=12)).isoformat(), "amount_gbp": 1450.00, "type": "debit", "counterparty": "John Lewis", "channel": "card"},
        {"txn_id": "TXN-88340", "timestamp": (_NOW - timedelta(days=9)).isoformat(), "amount_gbp": 3200.00, "type": "credit", "counterparty": "Payroll - Acme Ltd", "channel": "bacs"},
        {"txn_id": "TXN-88401", "timestamp": (_NOW - timedelta(days=4)).isoformat(), "amount_gbp": 220.00, "type": "debit", "counterparty": "Tesco", "channel": "card"},
    ],
    "CUST-10587": [
        {"txn_id": "TXN-91002", "timestamp": (_NOW - timedelta(days=3, hours=6)).isoformat(), "amount_gbp": 9400.00, "type": "debit", "counterparty": "Orion Trading FZE", "channel": "wire"},
        {"txn_id": "TXN-91015", "timestamp": (_NOW - timedelta(days=3, hours=2)).isoformat(), "amount_gbp": 9650.00, "type": "debit", "counterparty": "Orion Trading FZE", "channel": "wire"},
        {"txn_id": "TXN-91048", "timestamp": (_NOW - timedelta(days=2, hours=5)).isoformat(), "amount_gbp": 9800.00, "type": "debit", "counterparty": "Meridian Supplies LLC", "channel": "wire"},
        {"txn_id": "TXN-91077", "timestamp": (_NOW - timedelta(days=2, hours=1)).isoformat(), "amount_gbp": 9300.00, "type": "debit", "counterparty": "Orion Trading FZE", "channel": "wire"},
        {"txn_id": "TXN-91120", "timestamp": (_NOW - timedelta(days=1, hours=4)).isoformat(), "amount_gbp": 9700.00, "type": "debit", "counterparty": "Meridian Supplies LLC", "channel": "wire"},
        {"txn_id": "TXN-91156", "timestamp": (_NOW - timedelta(hours=14)).isoformat(), "amount_gbp": 9550.00, "type": "debit", "counterparty": "Orion Trading FZE", "channel": "wire"},
    ],
    "CUST-10842": [
        {"txn_id": "TXN-77210", "timestamp": (_NOW - timedelta(days=20)).isoformat(), "amount_gbp": 850.00, "type": "debit", "counterparty": "British Gas", "channel": "direct_debit"},
        {"txn_id": "TXN-77350", "timestamp": (_NOW - timedelta(days=6)).isoformat(), "amount_gbp": 2100.00, "type": "credit", "counterparty": "Payroll - Northgate PLC", "channel": "bacs"},
    ],
}

# Mock sanctions / adverse-media watchlist — fuzzy-matched by counterparty name only.
WATCHLIST = [
    {"entity_name": "Orion Trading FZE", "list_source": "Internal Adverse Media Watch", "reason": "Flagged in prior internal SAR (unrelated case) for rapid fund rotation", "risk_level": "high"},
    {"entity_name": "Meridian Supplies LLC", "list_source": "Internal Adverse Media Watch", "reason": "Shares registered agent with a previously sanctioned shell entity", "risk_level": "medium"},
]

# AML typology reference — used by the aml_typology_check tool, not by the model directly.
TYPOLOGIES = {
    "structuring": {
        "description": "Multiple transactions kept just under a reporting threshold to avoid triggering mandatory reporting.",
        "threshold_gbp": 10000.00,
        "lookback_days": 5,
        "min_transaction_count": 3,
    },
    "rapid_fund_rotation": {
        "description": "Funds moved in and out of an account in quick succession with little economic rationale.",
        "lookback_hours": 48,
    },
}
