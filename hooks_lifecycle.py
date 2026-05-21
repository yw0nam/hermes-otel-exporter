"""Session, approval, gateway, and subagent lifecycle hooks."""
from __future__ import annotations

import time
from typing import Any

from . import runtime as r
from .tracing import _TRACE_AVAILABLE, set_span_error


# ---- session --------------------------------------------------------------

def on_session_start(*, session_id: str = "", task_id: str = "",
                     platform: str = "", **_: Any) -> None:
    span_ctx = None
    if _TRACE_AVAILABLE:
        from .tracing import start_session_span
        span_ctx = start_session_span(session_id, platform or "cli", task_id=task_id)
        span = span_ctx.__enter__()
        with r.STATE_LOCK:
            r.SESSION_SPANS[session_id] = (span, span_ctx)
    r.init()
    key = r.key_for(task_id, session_id)
    with r.STATE_LOCK:
        r.SESSION_START_TS[key] = time.monotonic()
        r.SESSION_API_CALLS[key] = 0
        r.SESSION_TURNS[key] = 0
    r.add("session_count", 1,
          r.session_attrs(session_id, platform=platform or "cli"))
    event_attrs = {
        "event_name": "session.start",
        "platform": platform or "cli",
    }
    if session_id:
        event_attrs["session_id"] = session_id
    r.event_logger.info("session.start", extra=event_attrs)


def on_session_end(*, session_id: str = "", task_id: str = "",
                   platform: str = "", reason: str = "", **_: Any) -> None:
    key = r.key_for(task_id, session_id)
    span = None
    span_ctx = None
    with r.STATE_LOCK:
        if _TRACE_AVAILABLE:
            span_data = r.SESSION_SPANS.pop(session_id, None)
            if span_data:
                span, span_ctx = span_data
        started = r.SESSION_START_TS.pop(key, None)
        api_calls = r.SESSION_API_CALLS.pop(key, 0)
        turns = r.SESSION_TURNS.pop(key, 0)
        duration_ms = int((time.monotonic() - started) * 1000.0) if started is not None else None
    base = r.session_attrs(
        session_id,
        platform=platform or "cli",
        end_reason=reason or "ok",
    )
    if started is not None:
        r.record("session_duration", (time.monotonic() - started) * 1000.0, base)
    if api_calls:
        r.record("session_api_calls", api_calls, base)
    if turns:
        r.record("session_turns", turns, base)

    reason_lower = reason.lower()
    is_error = any(x in reason_lower for x in ("error", "crash", "timeout", "exception", "fail"))

    if is_error:
        event_attrs = {
            "event_name": "session.error",
            "reason": reason,
        }
        if session_id:
            event_attrs["session_id"] = session_id
        r.event_logger.error("session.error", extra=event_attrs)
    else:
        event_attrs = {
            "event_name": "session.end",
            "reason": reason or "ok",
        }
        if duration_ms is not None:
            event_attrs["duration_ms"] = duration_ms
        if api_calls:
            event_attrs["api_calls"] = api_calls
        if turns:
            event_attrs["turns"] = turns
        if session_id:
            event_attrs["session_id"] = session_id
        r.event_logger.info("session.end", extra=event_attrs)

    if span:
        try:
            span.set_attribute("end_reason", reason or "ok")
            if duration_ms is not None:
                span.set_attribute("duration_ms", duration_ms)
            if api_calls:
                span.set_attribute("api_calls", api_calls)
            if turns:
                span.set_attribute("turns", turns)
            if is_error:
                set_span_error(span, Exception(reason))
        except Exception:
            pass
        span_ctx.__exit__(None, None, None)


# ---- approval -------------------------------------------------------------

def on_pre_approval_request(*, command: str = "", pattern_key: str = "",
                            session_key: str = "", surface: str = "",
                            **_: Any) -> None:
    fallback = f"approval::{session_key}::{pattern_key}"
    unique = f"{fallback}::{time.time_ns()}"
    now = time.monotonic()
    with r.STATE_LOCK:
        r.APPROVAL_START_TS[unique] = now
        r.APPROVAL_START_TS[fallback] = now
    r.add("approval_requests", 1, {
        "pattern_key": pattern_key or "unknown",
        "surface": surface or "cli",
    })


def on_post_approval_response(*, choice: str = "", pattern_key: str = "",
                              session_key: str = "", surface: str = "",
                              **_: Any) -> None:
    fallback = f"approval::{session_key}::{pattern_key}"
    with r.STATE_LOCK:
        started = r.APPROVAL_START_TS.pop(fallback, None)
        for k in list(r.APPROVAL_START_TS):
            if k.startswith(fallback + "::"):
                r.APPROVAL_START_TS.pop(k, None)

    attrs = {
        "choice": choice or "unknown",
        "pattern_key": pattern_key or "unknown",
        "surface": surface or "cli",
    }
    r.add("approval_responses", 1, attrs)
    if started is not None:
        r.record("approval_wait", (time.monotonic() - started) * 1000.0, attrs)


# ---- gateway / subagent ---------------------------------------------------

def on_pre_gateway_dispatch(*, event: Any = None, **_: Any) -> None:
    surface = "unknown"
    try:
        surface = (
            getattr(event, "platform", None)
            or getattr(event, "surface", None)
            or getattr(getattr(event, "context", None), "platform", None)
            or "unknown"
        )
    except Exception:
        pass
    r.add("gateway_dispatch", 1, {"surface": str(surface)})


def on_subagent_stop(*, agent_name: str = "", reason: str = "",
                     success: bool = True, **_: Any) -> None:
    r.add("subagent_stop", 1, {
        "agent_name": agent_name or "unknown",
        "reason": reason or "ok",
        "success": str(bool(success)).lower(),
    })
