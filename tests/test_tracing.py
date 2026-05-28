"""Unit tests for tracing.py — the span factories."""
from __future__ import annotations

from opentelemetry.trace import SpanContext

from hermes_otel_exporter import tracing


def test_start_session_span_returns_none_without_tracer(no_tracer):
    assert tracing.start_session_span("sid", "cli") is None


def test_start_llm_span_returns_none_without_tracer(no_tracer):
    assert tracing.start_llm_span("gpt-5", "openai") is None


def test_start_tool_span_returns_none_without_tracer(no_tracer):
    assert tracing.start_tool_span("Bash") is None


def test_start_session_span_records_attrs(exporter):
    span = tracing.start_session_span("sid-1", "cli", task_id="t-1")
    assert span is not None
    span.end()

    finished = exporter.get_finished_spans()
    assert len(finished) == 1
    s = finished[0]
    assert s.name == "hermes.session"
    assert s.attributes["session_id"] == "sid-1"
    assert s.attributes["platform"] == "cli"
    assert s.attributes["task_id"] == "t-1"


def test_start_llm_span_records_attrs(exporter):
    span = tracing.start_llm_span("claude-opus", "anthropic", foo="bar")
    span.end()
    s = exporter.get_finished_spans()[0]
    assert s.name == "ai.chat"
    assert s.attributes["gen_ai.system"] == "anthropic"
    assert s.attributes["gen_ai.request.model"] == "claude-opus"
    assert s.attributes["gen_ai.operation.name"] == "chat"
    assert s.attributes["foo"] == "bar"


def test_start_tool_span_records_attrs(exporter):
    span = tracing.start_tool_span("Read", file_path="/x")
    span.end()
    s = exporter.get_finished_spans()[0]
    assert s.name == "claude_code.tool"
    assert s.attributes["name"] == "Read"
    assert s.attributes["gen_ai.tool.name"] == "Read"
    assert s.attributes["gen_ai.operation.name"] == "execute_tool"
    assert s.attributes["file_path"] == "/x"


def test_child_span_links_to_parent(exporter):
    """Tool spans should reference the session span as their parent."""
    parent = tracing.start_session_span("sid-1", "cli")
    child = tracing.start_tool_span("Bash", parent=parent)
    child.end()
    parent.end()

    finished = {s.name: s for s in exporter.get_finished_spans()}
    parent_ctx: SpanContext = finished["hermes.session"].context
    child_parent = finished["claude_code.tool"].parent
    assert child_parent is not None
    assert child_parent.trace_id == parent_ctx.trace_id
    assert child_parent.span_id == parent_ctx.span_id


def test_set_span_error_sets_status_and_attr(exporter):
    span = tracing.start_tool_span("Bash")
    tracing.set_span_error(span, RuntimeError("boom"))
    span.end()
    s = exporter.get_finished_spans()[0]
    assert s.status.status_code.name == "ERROR"
    assert s.attributes["error.type"] == "RuntimeError"


def test_set_span_error_no_op_on_none():
    # Must not raise when span is None (tracing disabled).
    tracing.set_span_error(None, RuntimeError("x"))
