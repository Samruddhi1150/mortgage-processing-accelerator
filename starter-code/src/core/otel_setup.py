import os

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def _otlp_endpoint(signal: str) -> str:
    endpoint = os.getenv(f"OTEL_EXPORTER_OTLP_{signal.upper()}_ENDPOINT")
    if endpoint:
        return endpoint

    collector_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if collector_endpoint:
        return f"{collector_endpoint.rstrip('/')}/v1/{signal}"
    return f"http://localhost:4318/v1/{signal}"


_resource = Resource.create({"service.name": os.getenv("OTEL_SERVICE_NAME", "anvesh-agent")})
_provider = TracerProvider(resource=_resource)
_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=_otlp_endpoint("traces")))
)
trace.set_tracer_provider(_provider)

_metric_reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(endpoint=_otlp_endpoint("metrics")),
    export_interval_millis=int(os.getenv("OTEL_METRIC_EXPORT_INTERVAL", "3000")),
)
_meter_provider = MeterProvider(resource=_resource, metric_readers=[_metric_reader])
metrics.set_meter_provider(_meter_provider)


def get_tracer(name: str):
    return trace.get_tracer(name)


def get_meter(name: str):
    return metrics.get_meter(name)