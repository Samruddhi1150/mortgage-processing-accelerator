# Anvesh Challenge — Starter Kit

*This starter kit includes OpenTelemetry tracing for investigations, model
calls, tools, and SAR drafting. Read the companion document,
**Anvesh_Observability_Challenge_Outline.docx**, before writing any code —
it shows the complete target architecture first, names all three
inconsistencies seeded in this repo on purpose, and gives a step-by-step
plan (with suggested GitHub Copilot prompts) to build OpenTelemetry +
Jaeger tracing AND the full metrics/eval/drift/alerting/feedback layer on
top of it.*

## What this is

The Anvesh fraud/AML transaction-pattern investigation agent (same
scenario as the Day-1 repo), extended with one more real step: once the
main tool loop finishes gathering evidence, it **delegates to a second,
separate model call** — a SAR-drafting sub-agent (`src/core/sub_agent.py`)
— to produce the final narrative a human reviewer would read.

Built on the new folder structure (`src/core/`, `src/tools/`, `src/data/`,
`tests/`, `scripts/`) used by every repo in this series from Anvesh
onward.

## What this is NOT (yet)

Tracing is instrumented and exported over OTLP/HTTP to a Collector. The
default endpoint is `http://localhost:4318/v1/traces`; configure
`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` to override it, or set
`OTEL_EXPORTER_OTLP_ENDPOINT` to a Collector base URL. Start the bundled
Jaeger and Collector with `docker compose up -d` from this directory. The
Jaeger UI is available at `http://localhost:16686`, Prometheus at
`http://localhost:9090`, and Grafana at `http://localhost:3000`. Grafana
provisions the Anvesh dashboard automatically. The Collector exports
metrics to Prometheus and its debug log every three seconds by default;
configure `OTEL_METRIC_EXPORT_INTERVAL` in milliseconds to change the
interval. Online evaluation, drift detection, alerting, and human feedback
are not included.

## The three inconsistencies — seeded, not described

All three are **already live in the code**, every time you run it — they
are not something you need to "turn on" to encounter them, only something
you can `seed_incident()` on demand to study one at a time in isolation.
None of them raise an error, log a warning, or show up as a failed HTTP
call. All three were written so that **reading a single trace once you've
added tracing will not, by itself, make them obvious** — that gap is the
entire reason the later steps (metrics, eval, drift, alerting) exist.

| # | Name | What's actually wrong | Where it lives |
|---|---|---|---|
| 1 | Tool call issue | `check_aml_typology()` is silently rerouted to always run the `rapid_fund_rotation` rule, no matter which typology was requested — CUST-10587's structuring pattern stops being flagged | `src/core/incidents.py` → `effective_typology()`, called from `src/tools/investigation_tools.py` |
| 2 | Model drift | Every `gpt-4o-mini` request is silently served by `gpt-4o` instead — no error, higher cost, and the caller's own "requested model" value is unaffected | `src/core/incidents.py` → `effective_model()`, called from `src/core/llm_provider.py` |
| 3 | Sub-agent call issue | The SAR-drafting sub-agent delegation drops all of the investigation evidence — it still returns a confident, fluent SAR narrative, just one that reflects nothing that was actually found | `src/core/incidents.py` → `sub_agent_context_enabled()`, called from `src/core/sub_agent.py` |

Use `POST /seed-incident/{1,2,3}`, `POST /clear-incident`, and
`GET /incident-status` (which only ever says `true`/`false`, never which
one) to control these — the same honesty convention used across this
entire training series. `GET /reveal-incident/{n}` is the answer key; look
at it only after trying to diagnose the incident yourself.

## Setup

1. `cp .env.example .env` and fill in `OPENAI_API_KEY`.
2. `python -m venv .venv && source .venv/bin/activate`
3. `pip install -r requirements.txt`
4. Sanity-check the mock data (no API key needed):
   `python scripts/list_mock_customers.py`
5. Run the deterministic tests (no API key needed):
   `pytest tests/unit -v`
6. Start Jaeger, the Collector, Prometheus, and Grafana:
   `docker compose up -d`
7. Run the demo (needs `OPENAI_API_KEY`) — this runs clean, then seeds and
   clears each incident in turn so you can see all three once by eye
   before you have any instrumentation at all: `python agent.py`
8. Or run the API: `uvicorn app:app --reload --port 8000`
9. Open Jaeger at `http://localhost:16686` and select the `anvesh-agent`
   service to find traces. Open the provisioned Grafana dashboard at
   `http://localhost:3000` for request rate, latency, cost, and tool
   failures. Prometheus is available at `http://localhost:9090`. Stop the
   services with `docker compose down`.

## Where to go next

Open **Anvesh_Observability_Challenge_Outline.docx**. Section 1 shows the
complete target architecture. Section 2 names these three inconsistencies
again, in the context of what will eventually catch each one. Section 3 is
the step-by-step build plan — tracing first, then the five files
(`metrics.py`, `online_eval.py`, `drift.py`, `alerting.py`, `feedback.py`)
one at a time, each with a suggested Copilot prompt.

## File map

| Path | Status |
|---|---|
| `src/core/llm_provider.py` | Traced raw model-call primitive, routed through `incidents.effective_model()` |
| `src/core/agent_loop.py` | Traced investigation loop + hand-off to the SAR sub-agent |
| `src/core/sub_agent.py` | Traced second model call drafting the SAR narrative |
| `src/core/incidents.py` | Working — all 3 inconsistencies, seed/clear/reveal |
| `src/core/pricing.py` | Prices both `gpt-4o-mini` and `gpt-4o` |
| `src/tools/investigation_tools.py` | Traced 4 tools, one routed through `incidents.effective_typology()` |
| `src/data/mock_store.py` | Mock customers, transactions, watchlist, typology rules |
| `tests/unit/test_tools.py`, `test_incidents.py` | Deterministic tests, no API key needed |
| `src/core/otel_setup.py` | OTLP tracer provider and `get_tracer()` helper |
| `metrics.py`, `online_eval.py`, `drift.py`, `alerting.py`, `feedback.py` | **Do not exist yet** — these are what you build |
| `docker-compose.yml`, `otel-collector-config.yaml` | Jaeger, OTLP Collector, Prometheus, and Grafana stack |
| `prometheus.yml`, `grafana/` | Prometheus scraping and provisioned observability dashboard |

## Mortgage Architecture Slice

The mortgage workflow is isolated in `src/mortgage/` and mounted under `/mortgage`, leaving the AML investigation flow intact. The event-bridge boundary is represented by document intake; each POST runs only the matching `income_check`, `valuation_check`, or `debt_check`. `StateAggregator` holds the application pending until all three evidence types are present and structurally usable. A ready application enters `conditional_decision`, which uses the OpenAI Responses API for a schema-constrained, non-binding policy assessment, then passes that assessment to `DeterministicValidationGate`.

The gate compares policy version and every extracted rule result with independent validation evidence. Automated offers require all configured rules to pass, two distinct control reviewers, and a passed fair-lending audit. A decline requires a verified hard-rule breach and an approved reason code. Mismatch, missing validation, model refusal, or tool failure routes to underwriter review. Offers and adverse-action notices are drafts only; there is no offer release or customer notification path.

The development API accepts document events at `POST /mortgage/applications/{application_id}/documents` with `document_type`, `evidence`, and optional trusted `received_at`; current state is available at `GET /mortgage/applications/{application_id}`. Example document types are `income`, `valuation`, and `debt`. This starter's default validation provider is intentionally unconfigured and therefore fails closed to review. Supply an approved policy repository plus independent dual-control and fair-lending providers to the `MortgageOrchestrator` before enabling any automated route; do not invent threshold rules in the LLM prompt.

The OpenAI adapter uses `OPENAI_API_KEY` and optional `OPENAI_MODEL` (default `gpt-4o-mini`) with strict JSON Schema output. It sends only allowlisted normalized fields: verification state and income, valuation amount/date, and verified monthly debt. Do not send real applicant data until privacy, legal, retention, and provider processing approvals are in place. Copy `.env.example` to `.env` and set your own key locally; `.env` is ignored by git.

Mortgage spans (`income_check`, `valuation_check`, `debt_check`, `state_aggregator`, `conditional_decision`, and `deterministic_validation`) and metrics (`mortgage.stage.duration`, `mortgage.stage.alerts`, `mortgage.stage.failures`, and `mortgage.time_to_decision`) use the existing OTLP setup. The decision-time measurement starts at the receipt timestamp of the last required document, excluding applicant wait. Set `slow_stage_threshold_ms` and `valuation_max_age` on `MortgageOrchestrator` for the deployment.
