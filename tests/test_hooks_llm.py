"""Tests for hooks_llm.py — LLM/API span lifecycle.

Critical regression: pre_api_request and post_api_request can run in
different asyncio tasks. The fix uses ``span.end()`` instead of ``__exit__``.
"""
from __future__ import annotations

import asyncio
import logging

from hermes_otel_exporter import hooks_lifecycle as L
from hermes_otel_exporter import hooks_llm as M
from hermes_otel_exporter import runtime_helpers as rh


def _key(task_id: str, session_id: str, n: int) -> str:
    return f"{rh.key_for(task_id, session_id)}::{n}"


def test_pre_then_post_api_creates_one_span(exporter):
    M.on_pre_api_request(
        task_id="t-1", session_id="sid-1", api_call_count=0,
        message_count=3, tool_count=2, approx_input_tokens=100,
        provider="anthropic", model="claude-opus", api_mode="messages",
    )
    key = _key("t-1", "sid-1", 0)
    assert key in rh.LLM_SPANS

    M.on_post_api_request(
        task_id="t-1", session_id="sid-1", api_call_count=0,
        api_duration=0.5, finish_reason="end_turn",
        usage={"input_tokens": 100, "output_tokens": 50},
        provider="anthropic", model="claude-opus",
    )
    assert key not in rh.LLM_SPANS

    finished = exporter.get_finished_spans()
    assert len(finished) == 1
    s = finished[0]
    assert s.name == "ai.chat"
    assert s.attributes["gen_ai.system"] == "anthropic"
    assert s.attributes["gen_ai.request.model"] == "claude-opus"
    assert s.attributes["gen_ai.usage.input_tokens"] == 100
    assert s.attributes["gen_ai.usage.output_tokens"] == 50
    assert s.attributes["gen_ai.usage.total_tokens"] == 150


def test_llm_span_handles_usage_object(exporter):
    class Usage:
        prompt_tokens = 10
        completion_tokens = 5

    M.on_pre_api_request(
        task_id="t-1", session_id="sid-1", api_call_count=0,
        provider="openai", model="gpt-5",
    )
    M.on_post_api_request(
        task_id="t-1", session_id="sid-1", api_call_count=0,
        api_duration=0.1, usage=Usage(),
        provider="openai", model="gpt-5",
    )
    s = exporter.get_finished_spans()[0]
    assert s.attributes["gen_ai.usage.input_tokens"] == 10
    assert s.attributes["gen_ai.usage.output_tokens"] == 5


def test_llm_span_records_error(exporter):
    M.on_pre_api_request(
        task_id="t-1", session_id="sid-1", api_call_count=0,
        provider="anthropic", model="claude-opus",
    )
    M.on_post_api_request(
        task_id="t-1", session_id="sid-1", api_call_count=0,
        api_duration=0.1, error=TimeoutError("upstream timeout"),
        provider="anthropic", model="claude-opus",
    )
    s = exporter.get_finished_spans()[0]
    assert s.status.status_code.name == "ERROR"
    assert s.attributes["error.type"] == "TimeoutError"


def test_llm_post_without_pre_is_noop(exporter):
    M.on_post_api_request(
        task_id="t-1", session_id="sid-1", api_call_count=99,
        api_duration=0.1, provider="x", model="y",
    )
    assert len(exporter.get_finished_spans()) == 0


def test_llm_span_links_to_session_parent(exporter):
    L.on_session_start(session_id="sid-1", task_id="t-1", platform="cli")
    M.on_pre_api_request(
        task_id="t-1", session_id="sid-1", api_call_count=0,
        provider="anthropic", model="claude-opus",
    )
    M.on_post_api_request(
        task_id="t-1", session_id="sid-1", api_call_count=0,
        api_duration=0.1, provider="anthropic", model="claude-opus",
    )
    L.on_session_end(session_id="sid-1", task_id="t-1", reason="ok")

    by_name = {s.name: s for s in exporter.get_finished_spans()}
    llm = by_name["ai.chat"]
    session = by_name["hermes.session"]
    assert llm.parent is not None
    assert llm.parent.trace_id == session.context.trace_id
    assert llm.parent.span_id == session.context.span_id


def test_cross_asyncio_task_llm_lifecycle(exporter, caplog):
    """REGRESSION: pre in task A, post in task B — no 'different Context' error."""
    async def pre():
        M.on_pre_api_request(
            task_id="t-x", session_id="sid-x", api_call_count=0,
            provider="anthropic", model="claude-opus",
        )

    async def post():
        M.on_post_api_request(
            task_id="t-x", session_id="sid-x", api_call_count=0,
            api_duration=0.1, provider="anthropic", model="claude-opus",
        )

    async def driver():
        await asyncio.create_task(pre())
        await asyncio.create_task(post())

    with caplog.at_level(logging.ERROR, logger="opentelemetry.context"):
        asyncio.run(driver())

    detach_errors = [r for r in caplog.records if "detach context" in r.getMessage()]
    assert detach_errors == [], f"unexpected detach errors: {detach_errors}"
    assert len(exporter.get_finished_spans()) == 1
