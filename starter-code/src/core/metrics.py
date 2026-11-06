from src.core.otel_setup import get_meter


_meter = get_meter(__name__)

investigation_request_counter = _meter.create_counter(
    "investigation.requests",
    unit="{request}",
    description="Number of completed investigations",
)
investigation_duration_histogram = _meter.create_histogram(
    "investigation.duration",
    unit="ms",
    description="Duration of completed investigations",
)
investigation_cost_histogram = _meter.create_histogram(
    "investigation.cost",
    unit="USD",
    description="Estimated model cost of completed investigations",
)
tool_failure_counter = _meter.create_counter(
    "investigation.tool_failures",
    unit="{failure}",
    description="Tool calls that returned or raised an error",
)


def record_investigation_turn(
    duration_ms: float,
    cost_usd: float,
    tool_failures: int,
) -> None:
    investigation_request_counter.add(1)
    investigation_duration_histogram.record(duration_ms)
    investigation_cost_histogram.record(cost_usd)
    if tool_failures:
        tool_failure_counter.add(tool_failures)