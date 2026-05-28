from __future__ import annotations

import atexit
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.trace.status import StatusCode
    _TRACE_AVAILABLE = True
except Exception:
    _TRACE_AVAILABLE = False

_tracer: Optional[Any] = None

def init_tracing(resource: Any, endpoint: str, insecure: bool) -> None:
    global _tracer
    if not _TRACE_AVAILABLE:
        return

    try:
        provider = TracerProvider(resource=resource)
        processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=insecure))
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)

        atexit.register(provider.shutdown)
        _tracer = trace.get_tracer("hermes.agent")
    except Exception as exc:
        logger.warning(f"hermes-otel-exporter: tracing init failed: {exc}")


# Spans below are created with start_span (NOT start_as_current_span) because
# their lifecycle spans across hook invocations that may run in different
# contextvars.Context instances. start_as_current_span would attach a token to
# the pre-hook's context and fail to detach it from a different post-hook context.
def start_session_span(session_id: str, platform: str, **attrs: Any) -> Optional[Any]:
    if not _tracer:
        return None
    span_attrs = {"session_id": session_id, "platform": platform, **attrs}
    return _tracer.start_span("hermes.session", attributes=span_attrs)


def start_llm_span(model: str, provider: str, parent: Optional[Any] = None, **attrs: Any) -> Optional[Any]:
    if not _tracer:
        return None
    span_attrs = {
        "gen_ai.system": provider,
        "gen_ai.request.model": model,
        "gen_ai.operation.name": "chat",
        **attrs,
    }
    ctx = trace.set_span_in_context(parent) if parent else None
    return _tracer.start_span("ai.chat", context=ctx, attributes=span_attrs)


def start_tool_span(tool_name: str, parent: Optional[Any] = None, **attrs: Any) -> Optional[Any]:
    if not _tracer:
        return None
    span_attrs = {
        "name": tool_name,
        "gen_ai.tool.name": tool_name,
        "gen_ai.operation.name": "execute_tool",
        **attrs,
    }
    ctx = trace.set_span_in_context(parent) if parent else None
    return _tracer.start_span("claude_code.tool", context=ctx, attributes=span_attrs)


def set_span_error(span: Any, exc: BaseException) -> None:
    if not span or not _TRACE_AVAILABLE:
        return
    try:
        span.record_exception(exc)
        span.set_status(StatusCode.ERROR)
        error_type = type(exc).__name__ if isinstance(exc, BaseException) else str(exc)
        span.set_attribute("error.type", error_type)
    except Exception:
        pass
