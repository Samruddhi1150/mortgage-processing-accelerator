"""Quick sanity-check script — prints the mock data without needing an API key.
Run: python scripts/list_mock_customers.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.mock_store import CUSTOMERS, TRANSACTIONS

if __name__ == "__main__":
    for cid, profile in CUSTOMERS.items():
        txns = TRANSACTIONS.get(cid, [])
        print(f"{cid}: {profile['name']} ({profile['kyc_risk_rating']} risk) — {len(txns)} transactions on file")
