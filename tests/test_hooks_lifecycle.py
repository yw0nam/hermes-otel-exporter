"""Tests for hooks_lifecycle.py — session span lifecycle.

The critical regression covered here: the pre-hook (``on_session_start``) and
post-hook (``on_session_end``) may execute in different asyncio tasks or
threads. The previous implementation stored an OpenTelemetry context manager
and called ``__exit__`` from the post-hook, which raised
``ValueError: Token was created in a different Context``. The fix uses
``span.end()`` directly, which is safe across contexts.
"""
from __future__ import annotations

import asyncio
import logging

from hermes_otel_exporter import hooks_lifecycle as L
from hermes_otel_exporter import runtime_helpers as rh


def test_session_start_creates_and_stores_span(exporter):
    L.on_session_start(session_id="sid-1", task_id="t-1", platform="cli")
    assert "sid-1" in rh.SESSION_SPANS
    # Span is stored as a bare span object, not a (span, span_ctx) tuple.
    assert not isinstance(rh.SESSION_SPANS["sid-1"], tuple)


def test_session_end_finishes_span(exporter):
    L.on_session_start(session_id="sid-1", task_id="t-1", platform="cli")
    L.on_session_end(session_id="sid-1", task_id="t-1", reason="ok")

    assert "sid-1" not in rh.SESSION_SPANS
    finished = exporter.get_finished_spans()
    assert len(finished) == 1
    assert finished[0].name == "hermes.session"
    assert finished[0].attributes["end_reason"] == "ok"


def test_session_end_marks_error_reason(exporter):
    L.on_session_start(session_id="sid-1", task_id="t-1", platform="cli")
    L.on_session_end(session_id="sid-1", task_id="t-1", reason="crash")
    s = exporter.get_finished_spans()[0]
    assert s.status.status_code.name == "ERROR"


def test_session_end_without_start_does_not_crash(exporter):
    # Should be a no-op — must not raise even with no prior start.
    L.on_session_end(session_id="orphan", task_id="t-0", reason="ok")
    assert len(exporter.get_finished_spans()) == 0


def test_cross_asyncio_task_session_lifecycle(exporter, caplog):
    """REGRESSION: start in task A, end in task B — no 'different Context' error."""
    async def pre():
        L.on_session_start(session_id="sid-x", task_id="t-x", platform="cli")

    async def post():
        L.on_session_end(session_id="sid-x", task_id="t-x", reason="ok")

    async def driver():
        await asyncio.create_task(pre())
        await asyncio.create_task(post())

    with caplog.at_level(logging.ERROR, logger="opentelemetry.context"):
        asyncio.run(driver())

    detach_errors = [r for r in caplog.records if "detach context" in r.getMessage()]
    assert detach_errors == [], f"unexpected detach errors: {detach_errors}"
    assert len(exporter.get_finished_spans()) == 1


def test_session_start_noop_when_tracer_disabled(no_tracer):
    L.on_session_start(session_id="sid-1", task_id="t-1", platform="cli")
    # Nothing stored because start_session_span returned None.
    assert "sid-1" not in rh.SESSION_SPANS
    # End is also safe — must not raise on missing span.
    L.on_session_end(session_id="sid-1", task_id="t-1", reason="ok")
