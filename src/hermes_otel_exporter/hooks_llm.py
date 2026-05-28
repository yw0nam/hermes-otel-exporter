"""LLM / API request hooks: timing, tokens, finish_reason, errors, cost."""
from __future__ import annotations

import time
from typing import Any, Optional

from . import runtime as r
from .tracing import _TRACE_AVAILABLE, start_llm_span, set_span_error


def on_pre_llm_call(*, task_id: str = "", session_id: str = "",
                    api_call_count: int = 0, turn_type: str = "",
                    **_: Any) -> None:
    key = f"{r.key_for(task_id, session_id)}::{api_call_count}"
    with r.STATE_LOCK:
        r.LLM_START_TS[key] = time.monotonic()
        if turn_type == "user":
            r.SESSION_TURNS[r.key_for(task_id, session_id)] += 1


def on_pre_api_request(*, task_id: str = "", session_id: str = "",
                       api_call_count: int = 0, message_count: int = 0,
                       tool_count: int = 0, approx_input_tokens: int = 0,
                       provider: str = "", model: str = "", api_mode: str = "",
                       **_: Any) -> None:
    key = f"{r.key_for(task_id, session_id)}::{api_call_count}"
    parent_span = None
    with r.STATE_LOCK:
        if _TRACE_AVAILABLE and session_id in r.SESSION_SPANS:
            parent_span = r.SESSION_SPANS[session_id]
        r.LLM_START_TS[key] = time.monotonic()
        r.SESSION_API_CALLS[r.key_for(task_id, session_id)] += 1

    if _TRACE_AVAILABLE:
        span = start_llm_span(
            model=model or "unknown",
            provider=provider or "unknown",
            parent=parent_span,
            **{
                "hermes.api_call_count": api_call_count,
                "ai.prompt.messages": approx_input_tokens or message_count,
            }
        )
        if span is not None:
            with r.STATE_LOCK:
                r.LLM_SPANS[key] = span

    attrs = r.session_attrs(
        session_id,
        model=model or "unknown",
        provider=provider or "unknown",
        api_mode=api_mode or "unknown",
    )
    if message_count:
        r.record("llm_message_count", message_count, attrs)
    if tool_count:
        r.record("llm_tool_count", tool_count, attrs)
    if approx_input_tokens:
        r.record("llm_input_tokens", approx_input_tokens, attrs)


def _token(usage: Any, name_keys: tuple[str, ...]) -> int:
    if isinstance(usage, dict):
        for k in name_keys:
            v = usage.get(k)
            if isinstance(v, (int, float)) and v:
                return int(v)
    elif usage is not None:
        for k in name_keys:
            v = getattr(usage, k, None)
            if isinstance(v, (int, float)) and v:
                return int(v)
    return 0


def _estimate_cost(model: str, provider: str, input_tokens: int,
                   output_tokens: int, cache_read: int, cache_write: int,
                   reasoning: int) -> Optional[float]:
    try:
        from agent.usage_pricing import CanonicalUsage, estimate_usage_cost
        cu = CanonicalUsage(
            input_tokens=input_tokens, output_tokens=output_tokens,
            cache_read_tokens=cache_read, cache_write_tokens=cache_write,
            reasoning_tokens=reasoning,
        )
        cost = estimate_usage_cost(
            model or "", cu, provider=provider or "", base_url="", api_key="",
        )
        if cost.amount_usd is not None:
            return float(cost.amount_usd)
    except Exception as exc:
        r.debug(f"pricing lookup failed: {exc}")

    try:
        in_rate = float(r.env("HERMES_OTEL_COST_INPUT_PER_M") or 0)
        out_rate = float(r.env("HERMES_OTEL_COST_OUTPUT_PER_M") or 0)
        if in_rate or out_rate:
            return (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000.0
    except Exception:
        pass
    return None


def _record_llm(*, task_id: str = "", session_id: str = "",
                api_call_count: int = 0, provider: str = "",
                model: str = "", api_mode: str = "",
                api_duration: float = 0.0, finish_reason: str = "",
                usage: Any = None, error: Any = None,
                retry_count: int = 0, assistant_content_chars: int = 0,
                **_: Any) -> None:
    key = f"{r.key_for(task_id, session_id)}::{api_call_count}"
    span = None
    with r.STATE_LOCK:
        if _TRACE_AVAILABLE:
            span = r.LLM_SPANS.pop(key, None)
        started = r.LLM_START_TS.pop(key, None)

    attrs = r.session_attrs(
        session_id,
        model=model or "unknown",
        provider=provider or "unknown",
        api_mode=api_mode or "unknown",
    )
    r.add("llm_call_count", 1, attrs)

    duration_ms = api_duration * 1000.0 if api_duration else (
        (time.monotonic() - started) * 1000.0 if started else None
    )
    if duration_ms is not None:
        r.record("llm_call_duration", duration_ms, attrs)

    if finish_reason:
        r.add("finish_reason", 1, {**attrs, "reason": finish_reason})
    if assistant_content_chars:
        r.record("assistant_content_chars", assistant_content_chars, attrs)
    if retry_count:
        r.add("retries", retry_count, {**attrs, "reason": "api_retry"})
    if error is not None:
        r.add("errors", 1, {
            **attrs, "component": "llm",
            "error_type": r.classify_error(error),
        })

    input_tokens = _token(usage, ("input_tokens", "prompt_tokens"))
    output_tokens = _token(usage, ("output_tokens", "completion_tokens"))
    cache_read = _token(usage, ("cache_read_tokens", "cache_read_input_tokens"))
    cache_write = _token(usage, ("cache_write_tokens", "cache_creation_input_tokens"))
    reasoning = _token(usage, ("reasoning_tokens",))

    if input_tokens:
        r.add("tokens", input_tokens, {**attrs, "type": "input"})
    if output_tokens:
        r.add("tokens", output_tokens, {**attrs, "type": "output"})
    if cache_read:
        r.add("tokens", cache_read, {**attrs, "type": "cache_read"})
    if cache_write:
        r.add("tokens", cache_write, {**attrs, "type": "cache_write"})
    if reasoning:
        r.add("tokens", reasoning, {**attrs, "type": "reasoning"})

    cost = _estimate_cost(model, provider, input_tokens, output_tokens,
                          cache_read, cache_write, reasoning)
    if cost:
        r.add("cost_usd", cost, attrs)

    if error is not None:
        err_attrs = {
            "event_name": "api_error",
            "model": model or "unknown",
            "provider": provider or "unknown",
            "error_type": r.classify_error(error),
        }
        if session_id:
            err_attrs["session_id"] = session_id
        r.event_logger.error("api_error", extra=err_attrs)
    elif duration_ms is not None:
        evt_attrs = {
            "event_name": "api_request",
            "model": model or "unknown",
            "provider": provider or "unknown",
            "duration_ms": int(duration_ms),
        }
        if session_id:
            evt_attrs["session_id"] = session_id
        if finish_reason:
            evt_attrs["finish_reason"] = finish_reason
        r.event_logger.info("api_request", extra=evt_attrs)

    if span:
        try:
            span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
            span.set_attribute("gen_ai.usage.total_tokens", input_tokens + output_tokens)
            if finish_reason:
                span.set_attribute("gen_ai.response.finish_reasons", [finish_reason])
            usage_json = {}
            if cache_read:
                usage_json["cache_read"] = cache_read
            if cache_write:
                usage_json["cache_write"] = cache_write
            if reasoning:
                usage_json["reasoning"] = reasoning
            if usage_json:
                import json
                span.set_attribute("ai.response.usage", json.dumps(usage_json))
            if error is not None:
                set_span_error(span, error if isinstance(error, BaseException) else Exception(str(error)))
        except Exception:
            pass
        try:
            span.end()
        except Exception:
            pass


def on_post_llm_call(**kwargs: Any) -> None:
    _record_llm(**kwargs)


def on_post_api_request(**kwargs: Any) -> None:
    _record_llm(**kwargs)
