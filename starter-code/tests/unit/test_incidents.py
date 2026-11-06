"""
Confirms each seeded inconsistency actually does what README.md/the outline
doc claims — these are the tests a facilitator runs before handing this
repo to participants, not something participants are expected to run
(though they're free to). No OPENAI_API_KEY required.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.core.incidents import seed_incident, clear_incident, effective_model, effective_typology
from src.tools.investigation_tools import check_aml_typology


def test_no_incident_by_default():
    clear_incident()
    assert effective_model("gpt-4o-mini") == "gpt-4o-mini"
    assert effective_typology("structuring") == "structuring"


def test_incident_1_tool_misrouting_reroutes_typology():
    seed_incident(1)
    result = check_aml_typology("CUST-10587", typology="structuring")
    assert result["requested_typology"] == "structuring"
    assert result["typology"] == "rapid_fund_rotation"  # silently rerouted
    clear_incident()


def test_incident_1_hides_the_structuring_pattern():
    seed_incident(1)
    result = check_aml_typology("CUST-10587", typology="structuring")
    # The structuring flag never gets evaluated at all while this incident is active —
    # whatever comes back is the rapid_fund_rotation check instead.
    assert result["typology"] != "structuring"
    clear_incident()


def test_incident_2_silent_model_drift():
    seed_incident(2)
    assert effective_model("gpt-4o-mini") == "gpt-4o"
    clear_incident()
    assert effective_model("gpt-4o-mini") == "gpt-4o-mini"


def test_incidents_are_mutually_exclusive_by_number():
    seed_incident(2)
    # incident 1's effect should NOT be active while incident 2 is seeded
    assert effective_typology("structuring") == "structuring"
    clear_incident()
