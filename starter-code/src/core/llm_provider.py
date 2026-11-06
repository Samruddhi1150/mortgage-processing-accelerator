"""
Anatomy of a model call — unchanged from Day 1 (Anvesh), EXCEPT every
call now passes the requested model through incidents.effective_model()
before it reaches the API. That one line is where incident 2 (silent
model drift) actually lives — read it once, then forget it's there, the
same way a real production bug would hide in a one-line helper call.

Still no OpenTelemetry here. Adding tracing to this file is Step 1 of the
companion challenge outline — don't add spans before reading it.

NOTE: .env is loaded explicitly, by path, BEFORE anything reads
OPENAI_API_KEY — a prior repo in this series lost time to a bug where a
correctly-filled .env was silently ignored because nothing called
load_dotenv() before the os.environ.get() lookup.
"""

import os
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

from src.core.pricing import estimate_cost_usd
from src.core.incidents import effective_model
from src.core.otel_setup import get_tracer

ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=ENV_FILE)

DEFAULT_MODEL = "gpt-4o-mini"
_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(f"OPENAI_API_KEY is not set. Check your .env file at: {ENV_FILE}")
        _client = OpenAI(api_key=api_key)
    return _client


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class ModelCallResult:
    content: Optional[str]
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ""
    requested_model: str = ""
    served_model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: float = 0.0
    raw_request: dict = field(default_factory=dict)
    raw_response: object = None


def chat_raw(messages: list[dict], tools: Optional[list] = None,
             model: str = DEFAULT_MODEL, temperature: Optional[float] = None) -> ModelCallResult:
    with get_tracer(__name__).start_as_current_span("model_call") as span:
        result = _chat_raw(messages, tools=tools, model=model, temperature=temperature)
        span.set_attribute("llm.requested_model", result.requested_model)
        span.set_attribute("llm.served_model", result.served_model)
        span.set_attribute("llm.input_tokens", result.input_tokens)
        span.set_attribute("llm.output_tokens", result.output_tokens)
        span.set_attribute("llm.cost_usd", result.cost_usd)
        return result


def _chat_raw(messages: list[dict], tools: Optional[list] = None,
              model: str = DEFAULT_MODEL, temperature: Optional[float] = None) -> ModelCallResult:
    client = _get_client()

    served_model_request = effective_model(model)  # <- incident 2 lives in this one call

    request_kwargs = {"model": served_model_request, "messages": messages}
    if tools:
        request_kwargs["tools"] = tools
    if temperature is not None:
        request_kwargs["temperature"] = temperature

    t0 = time.perf_counter()
    response = client.chat.completions.create(**request_kwargs)
    duration_ms = (time.perf_counter() - t0) * 1000

    choice = response.choices[0]
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
    cost_usd = estimate_cost_usd(response.model, input_tokens, output_tokens)

    tool_calls = [
        ToolCall(id=tc.id, name=tc.function.name, arguments=tc.function.arguments)
        for tc in (choice.message.tool_calls or [])
    ]

    return ModelCallResult(
        content=choice.message.content,
        tool_calls=tool_calls,
        finish_reason=choice.finish_reason,
        requested_model=model,            # what the CALLER asked for — unaffected by the incident
        served_model=response.model,      # what the API actually used — this is where incident 2 shows up
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        duration_ms=duration_ms,
        raw_request=request_kwargs,
        raw_response=response,
    )
