"""Tool call hooks: timing, success, payload sizes."""
from __future__ import annotations

import time
from typing import Any

from . import runtime as r
from .tracing import _TRACE_AVAILABLE, start_tool_span, set_span_error


def on_pre_tool_call(*, tool_name: str = "", args: Any = None, task_id: str = "",
                     session_id: str = "", tool_call_id: str = "",
                     **_: Any) -> None:
    base = r.key_for(task_id, session_id)
    now = time.monotonic()
    parent_span = None
    with r.STATE_LOCK:
        if _TRACE_AVAILABLE and session_id in r.SESSION_SPANS:
            parent_span = r.SESSION_SPANS[session_id]
        if tool_call_id:
            r.TOOL_START_TS[f"{base}::{tool_call_id}"] = now
        else:
            r.TOOL_START_TS[f"{base}::{tool_name}::{time.time_ns()}"] = now

    if _TRACE_AVAILABLE:
        arg_json = ""
        try:
            import json
            arg_json = json.dumps(args, default=str)
            if len(arg_json) > 32768:
                arg_json = arg_json[:32768] + "...(truncated)"
        except Exception:
            arg_json = str(args)[:32768]

        span_attrs = {
            "gen_ai.tool.call.id": tool_call_id,
            "gen_ai.tool.call.arguments": arg_json,
        }
        
        if tool_name in ("bash", "InteractiveBash"):
            span_attrs["full_command"] = str(args.get("command", ""))[:8192] if isinstance(args, dict) else ""
        elif tool_name in ("Write", "Edit", "Read", "Glob", "Grep"):
            span_attrs["file_path"] = str(args.get("filePath", args.get("path", "")))[:8192] if isinstance(args, dict) else ""

        span = start_tool_span(tool_name, parent=parent_span, **span_attrs)
        if span is not None:
            with r.STATE_LOCK:
                r.TOOL_SPANS[tool_call_id or f"{base}::{tool_name}"] = span

    arg_size = r.payload_size(args)
    if arg_size:
        r.record("tool_arg_bytes", arg_size,
                 r.session_attrs(session_id, tool_name=tool_name or "unknown"))


def on_post_tool_call(*, tool_name: str = "", result: Any = None,
                      task_id: str = "", session_id: str = "",
                      tool_call_id: str = "", error: Any = None,
                      **_: Any) -> None:
    base = r.key_for(task_id, session_id)
    started = None
    span = None
    with r.STATE_LOCK:
        if _TRACE_AVAILABLE:
            span_key = tool_call_id or f"{base}::{tool_name}"
            span = r.TOOL_SPANS.pop(span_key, None)
            if span is None and not tool_call_id:
                for k in list(r.TOOL_SPANS):
                    if k.startswith(f"{base}::") and tool_name in k:
                        span = r.TOOL_SPANS.pop(k)
                        break


        if tool_call_id:
            started = r.TOOL_START_TS.pop(f"{base}::{tool_call_id}", None)
        if started is None:
            for k in list(r.TOOL_START_TS):
                if k.startswith(f"{base}::") and (tool_name in k or not tool_name):
                    started = r.TOOL_START_TS.pop(k)
                    break

    success = error is None
    err_type = ""
    if error is not None:
        success = False
        err_type = r.classify_error(error)
    elif isinstance(result, dict) and result.get("error"):
        success = False
        err_type = "tool_error"
    elif isinstance(result, str) and result.startswith("Error:"):
        success = False
        err_type = "tool_error"

    attrs = r.session_attrs(
        session_id,
        tool_name=tool_name or "unknown",
        success=str(success).lower(),
    )
    r.add("tool_call_count", 1, attrs)

    duration_ms = (
        (time.monotonic() - started) * 1000.0 if started is not None else None
    )
    if duration_ms is not None:
        r.record("tool_call_duration", duration_ms, attrs)

    result_size = r.payload_size(result)
    if result_size:
        r.record("tool_result_bytes", result_size,
                 r.session_attrs(session_id, tool_name=tool_name or "unknown"))

    if not success:
        r.add("errors", 1, {
            **r.session_attrs(session_id),
            "component": "tool",
            "tool_name": tool_name or "unknown",
            "error_type": err_type or "tool_error",
        })

    event_attrs = {
        "event_name": "tool_result",
        "tool_name": tool_name or "unknown",
        "success": str(success).lower(),
    }
    if duration_ms is not None:
        event_attrs["duration_ms"] = int(duration_ms)
    if session_id:
        event_attrs["session_id"] = session_id
    if result_size:
        event_attrs["tool_result_size_bytes"] = result_size
    if err_type:
        event_attrs["error_type"] = err_type
    r.event_logger.info("tool_result", extra=event_attrs)

    if span:
        try:
            out_str = str(result)
            if len(out_str) > 32768:
                out_str = out_str[:32768] + "...(truncated)"
            span.add_event("tool.output", {"output": out_str})
            if duration_ms is not None:
                span.set_attribute("gen_ai.tool.call.duration_ms", duration_ms)
            if error is not None:
                set_span_error(span, error if isinstance(error, BaseException) else Exception(str(error)))
        except Exception:
            pass
        try:
            span.end()
        except Exception:
            pass


def on_transform_tool_result(*, tool_name: str = "", result: Any = None,
                             session_id: str = "", **_: Any) -> Any:
    """Observer-only: record post-transform result size. Returns result
    unchanged so other plugins' transforms aren't disturbed."""
    size = r.payload_size(result)
    if size:
        r.record("tool_result_bytes", size, r.session_attrs(
            session_id,
            tool_name=tool_name or "unknown",
            stage="transformed",
        ))
    return result
