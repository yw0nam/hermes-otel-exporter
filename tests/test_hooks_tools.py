"""Tests for hooks_tools.py — tool span lifecycle.

Critical regression: pre_tool_call and post_tool_call can run in different
asyncio tasks. The fix uses ``span.end()`` instead of ``__exit__``.
"""
from __future__ import annotations

import asyncio
import logging

from hermes_otel_exporter import hooks_lifecycle as L
from hermes_otel_exporter import hooks_tools as T
from hermes_otel_exporter import runtime_helpers as rh


def test_pre_then_post_creates_one_tool_span(exporter):
    # Plugin matches lowercase "bash" or "InteractiveBash" for the
    # full_command attribute (see hooks_tools.py).
    T.on_pre_tool_call(
        tool_name="bash", args={"command": "ls"},
        task_id="t-1", session_id="sid-1", tool_call_id="call-1",
    )
    assert "call-1" in rh.TOOL_SPANS
    T.on_post_tool_call(
        tool_name="bash", result="ok",
        task_id="t-1", session_id="sid-1", tool_call_id="call-1",
    )
    assert "call-1" not in rh.TOOL_SPANS

    finished = exporter.get_finished_spans()
    assert len(finished) == 1
    s = finished[0]
    assert s.name == "claude_code.tool"
    assert s.attributes["gen_ai.tool.name"] == "bash"
    assert s.attributes["gen_ai.tool.call.id"] == "call-1"
    assert s.attributes["full_command"] == "ls"


def test_tool_span_records_error_on_failure(exporter):
    T.on_pre_tool_call(
        tool_name="Bash", args={"command": "false"},
        session_id="sid-1", tool_call_id="call-2",
    )
    T.on_post_tool_call(
        tool_name="Bash", result=None, error=RuntimeError("nonzero exit"),
        session_id="sid-1", tool_call_id="call-2",
    )
    s = exporter.get_finished_spans()[0]
    assert s.status.status_code.name == "ERROR"
    assert s.attributes["error.type"] == "RuntimeError"


def test_post_without_pre_is_noop(exporter):
    # Must not raise; just records metrics with no span.
    T.on_post_tool_call(
        tool_name="Bash", result="ok",
        session_id="sid-1", tool_call_id="ghost",
    )
    assert len(exporter.get_finished_spans()) == 0


def test_tool_span_links_to_session_parent(exporter):
    L.on_session_start(session_id="sid-1", task_id="t-1", platform="cli")
    T.on_pre_tool_call(
        tool_name="Read", args={"path": "/x"},
        task_id="t-1", session_id="sid-1", tool_call_id="call-3",
    )
    T.on_post_tool_call(
        tool_name="Read", result="content",
        task_id="t-1", session_id="sid-1", tool_call_id="call-3",
    )
    L.on_session_end(session_id="sid-1", task_id="t-1", reason="ok")

    by_name = {s.name: s for s in exporter.get_finished_spans()}
    tool_span = by_name["claude_code.tool"]
    session_span = by_name["hermes.session"]
    assert tool_span.parent is not None
    assert tool_span.parent.trace_id == session_span.context.trace_id
    assert tool_span.parent.span_id == session_span.context.span_id


def test_cross_asyncio_task_tool_lifecycle(exporter, caplog):
    """REGRESSION: pre in task A, post in task B — no 'different Context' error.

    This is the exact scenario that produced the production errors:
        File "tracing.py", line 81, in start_tool_span
            yield span
        GeneratorExit
        ValueError: <Token ...> was created in a different Context
    """
    async def pre():
        T.on_pre_tool_call(
            tool_name="Bash", args={"command": "echo"},
            session_id="sid-x", tool_call_id="call-xc",
        )

    async def post():
        T.on_post_tool_call(
            tool_name="Bash", result="echo\n",
            session_id="sid-x", tool_call_id="call-xc",
        )

    async def driver():
        await asyncio.create_task(pre())
        await asyncio.create_task(post())

    with caplog.at_level(logging.ERROR, logger="opentelemetry.context"):
        asyncio.run(driver())

    detach_errors = [r for r in caplog.records if "detach context" in r.getMessage()]
    assert detach_errors == [], f"unexpected detach errors: {detach_errors}"
    assert len(exporter.get_finished_spans()) == 1


def test_tool_span_truncates_large_args(exporter):
    huge = {"command": "x" * 100_000}
    T.on_pre_tool_call(
        tool_name="Bash", args=huge,
        session_id="sid-1", tool_call_id="call-big",
    )
    T.on_post_tool_call(
        tool_name="Bash", result="ok",
        session_id="sid-1", tool_call_id="call-big",
    )
    s = exporter.get_finished_spans()[0]
    arg_json = s.attributes["gen_ai.tool.call.arguments"]
    assert len(arg_json) <= 32768 + len("...(truncated)")
    assert arg_json.endswith("...(truncated)")
