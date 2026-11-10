"""FastAPI entrypoint for the instrumented investigation agent."""

from fastapi import FastAPI, HTTPException

from src.core.agent_loop import run_investigation
from src.core.llm_provider import chat_raw
from src.core.online_eval import recent_evaluations, rolling_average_score
from src.core.drift import status as drift_status
from src.core.incidents import seed_incident, clear_incident, incident_status, reveal_incident
from src.data.mock_store import CUSTOMERS
from src.mortgage.api import router as mortgage_router

app = FastAPI(title="Mortgage Investigation Agent", version="0.1.0")
app.include_router(mortgage_router)


@app.get("/customers")
def list_customers():
    return {"customers": list(CUSTOMERS.keys())}


@app.get("/investigate")
def investigate(customer_id: str):
    if customer_id not in CUSTOMERS:
        raise HTTPException(status_code=404, detail=f"Unknown customer_id {customer_id}")
    return run_investigation(customer_id, verbose=False)


@app.get("/eval/recent")
def recent_eval():
    return {
        "recent": recent_evaluations(),
        "rolling_average_score": rolling_average_score(),
    }


@app.get("/drift/status")
def drift_status_endpoint():
    return drift_status()


@app.get("/raw-call-demo")
def raw_call_demo(question: str = "What does AML structuring mean?"):
    result = chat_raw(
        messages=[
            {"role": "system", "content": "You are a concise AML compliance assistant."},
            {"role": "user", "content": question},
        ],
    )
    return {
        "requested_model": result.requested_model,
        "served_model": result.served_model,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "cost_usd": result.cost_usd,
        "content": result.content,
    }


@app.post("/seed-incident/{n}")
def seed_incident_endpoint(n: int):
    return seed_incident(n)


@app.post("/clear-incident")
def clear_incident_endpoint():
    return clear_incident()


@app.get("/incident-status")
def incident_status_endpoint():
    return incident_status()


@app.get("/reveal-incident/{n}")
def reveal_incident_endpoint(n: int):
    return reveal_incident(n)
