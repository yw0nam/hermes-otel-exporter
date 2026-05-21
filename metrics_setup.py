"""Metric definitions and buckets."""
from typing import Any, Dict

try:
    from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
except Exception:
    pass

_METERS: Dict[str, Any] = {}

LATENCY_BUCKETS_MS = [
    5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000,
    10000, 30000, 60000, 120000, 300000,
]
TOKEN_BUCKETS = [
    100, 500, 1000, 2500, 5000, 10000, 25000, 50000,
    100000, 200000, 500000, 1000000,
]
BYTE_BUCKETS = [
    256, 1024, 4096, 16384, 65536, 262144, 1048576, 4194304,
]
COUNT_BUCKETS = [1, 2, 5, 10, 20, 50, 100, 200, 500]

def _hist_view(name: str, buckets: list[float]) -> Any:
    return View(
        instrument_name=name,
        aggregation=ExplicitBucketHistogramAggregation(boundaries=buckets),
    )

def _get_views() -> list[Any]:
    return [
        _hist_view("hermes.session.duration", LATENCY_BUCKETS_MS),
        _hist_view("hermes.llm.duration", LATENCY_BUCKETS_MS),
        _hist_view("hermes.llm.input_tokens", TOKEN_BUCKETS),
        _hist_view("hermes.tool.duration", LATENCY_BUCKETS_MS),
        _hist_view("hermes.tool.result_bytes", BYTE_BUCKETS),
        _hist_view("hermes.tool.arg_bytes", BYTE_BUCKETS),
        _hist_view("hermes.assistant.content_chars", BYTE_BUCKETS),
        _hist_view("hermes.session.api_calls", COUNT_BUCKETS),
        _hist_view("hermes.session.turns", COUNT_BUCKETS),
        _hist_view("hermes.llm.message_count", COUNT_BUCKETS),
        _hist_view("hermes.llm.tool_count", COUNT_BUCKETS),
        _hist_view("hermes.approval.wait_ms", LATENCY_BUCKETS_MS),
    ]

def _build_meters(meter: Any) -> None:
    M = _METERS

    M["session_count"] = meter.create_counter("hermes.session.count", description="Sessions started", unit="1")
    M["session_duration"] = meter.create_histogram("hermes.session.duration", description="Session duration", unit="ms")
    M["session_api_calls"] = meter.create_histogram("hermes.session.api_calls", description="LLM API calls per session", unit="1")
    M["session_turns"] = meter.create_histogram("hermes.session.turns", description="User turns per session", unit="1")

    M["llm_call_count"] = meter.create_counter("hermes.llm.calls", description="LLM API calls", unit="1")
    M["llm_call_duration"] = meter.create_histogram("hermes.llm.duration", description="LLM API call duration", unit="ms")
    M["llm_input_tokens"] = meter.create_histogram("hermes.llm.input_tokens", description="Input tokens per LLM call (context fill)", unit="1")
    M["llm_message_count"] = meter.create_histogram("hermes.llm.message_count", description="Messages per LLM call", unit="1")
    M["llm_tool_count"] = meter.create_histogram("hermes.llm.tool_count", description="Tool definitions per LLM call", unit="1")
    M["finish_reason"] = meter.create_counter("hermes.llm.finish_reason", description="finish_reason classification", unit="1")
    M["assistant_content_chars"] = meter.create_histogram("hermes.assistant.content_chars", description="Assistant text response length", unit="By")

    M["tokens"] = meter.create_counter("hermes.token_usage", description="Token usage by type", unit="tokens")
    M["cost_usd"] = meter.create_counter("hermes.cost_usage", description="Estimated USD cost", unit="USD")

    M["tool_call_count"] = meter.create_counter("hermes.tool.calls", description="Tool invocations", unit="1")
    M["tool_call_duration"] = meter.create_histogram("hermes.tool.duration", description="Tool execution duration", unit="ms")
    M["tool_result_bytes"] = meter.create_histogram("hermes.tool.result_bytes", description="Tool result payload size", unit="By")
    M["tool_arg_bytes"] = meter.create_histogram("hermes.tool.arg_bytes", description="Tool argument payload size", unit="By")

    M["errors"] = meter.create_counter("hermes.errors", description="Errors by component and type", unit="1")
    M["retries"] = meter.create_counter("hermes.retry.count", description="API retry attempts", unit="1")

    M["approval_requests"] = meter.create_counter("hermes.approval.requests", description="Dangerous-command approval prompts", unit="1")
    M["approval_responses"] = meter.create_counter("hermes.approval.responses", description="Approval prompt responses by choice", unit="1")
    M["approval_wait"] = meter.create_histogram("hermes.approval.wait_ms", description="Time waiting for approval response", unit="ms")
    M["gateway_dispatch"] = meter.create_counter("hermes.gateway.dispatch", description="Gateway message dispatch by surface", unit="1")
    M["subagent_stop"] = meter.create_counter("hermes.subagent.stop", description="Subagent termination events", unit="1")
