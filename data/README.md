# Synthetic Mortgage Test Data

All records are fictional and intended only for local development and observability demonstrations.

## Scenarios
- MORT-1001: healthy flow
- MORT-1002: slow valuation stage
- MORT-1003: fast but stale cached valuation
- MORT-1004: missing applicant income evidence; exclude waiting time from SLO
- MORT-1005: incomplete debt-tool response
- MORT-1006: valuation timeout

Use `application_id` to join applications, income, debts, and expected results. Use `property_id` to join applications to valuations.
