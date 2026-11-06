"""
Demo runner. Run clean first, then seed each incident and run again — with
no observability built yet, the only way to notice anything is reading the
printed output by eye. That's the point: by the end of the challenge, you
should be catching these from a dashboard and an alert feed instead.

Run: python agent.py
"""

from src.core.agent_loop import run_investigation
from src.core.incidents import seed_incident, clear_incident


def run_clean():
    print("\n=== Clean run — CUST-10587 (should flag structuring) ===")
    outcome = run_investigation("CUST-10587", verbose=True)
    print("\n--- Internal summary ---")
    print(outcome["internal_summary"])
    print("\n--- SAR narrative ---")
    print(outcome["sar"]["sar_narrative"])
    print(f"\n(total cost: ${outcome['total_cost_usd']})")


def run_with_incident(n: int, customer_id: str = "CUST-10587"):
    print(f"\n=== Incident {n} seeded — {customer_id} ===")
    seed_incident(n)
    outcome = run_investigation(customer_id, verbose=True)
    print("\n--- SAR narrative ---")
    print(outcome["sar"]["sar_narrative"])
    print(f"\n(total cost: ${outcome['total_cost_usd']})")
    clear_incident()


if __name__ == "__main__":
    run_clean()
    run_with_incident(1)  # tool misrouting
    run_with_incident(2)  # silent model drift
    run_with_incident(3)  # sub-agent context loss
