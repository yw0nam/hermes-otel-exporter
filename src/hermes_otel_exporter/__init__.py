"""hermes-otel-exporter — emit Hermes telemetry to the local OTel Collector.

Pipeline:
  Hermes hooks
    -> OpenTelemetry SDK (metrics + logs)
    -> OTLP gRPC -> 127.0.0.1:4317
    -> obs-otel-collector
    -> Prometheus (metrics) + Loki (logs)
    -> Grafana

See README.md for activation, env vars, and emitted metrics.

Module split:
  runtime.py         - OTel SDK init, meters, shared state, helpers
  hooks_llm.py       - LLM / API request metrics
  hooks_tools.py     - Tool call metrics
  hooks_lifecycle.py - Session, approval, gateway, subagent metrics
"""
from __future__ import annotations

from . import hooks_lifecycle as L
from . import hooks_llm as M
from . import hooks_tools as T
from . import runtime as r


def register(ctx) -> None:
    r.init()
    ctx.register_hook("on_session_start", L.on_session_start)
    ctx.register_hook("on_session_end", L.on_session_end)
    ctx.register_hook("pre_llm_call", M.on_pre_llm_call)
    ctx.register_hook("post_llm_call", M.on_post_llm_call)
    ctx.register_hook("pre_api_request", M.on_pre_api_request)
    ctx.register_hook("post_api_request", M.on_post_api_request)
    ctx.register_hook("pre_tool_call", T.on_pre_tool_call)
    ctx.register_hook("post_tool_call", T.on_post_tool_call)
    ctx.register_hook("transform_tool_result", T.on_transform_tool_result)
    ctx.register_hook("pre_approval_request", L.on_pre_approval_request)
    ctx.register_hook("post_approval_response", L.on_post_approval_response)
    ctx.register_hook("pre_gateway_dispatch", L.on_pre_gateway_dispatch)
    ctx.register_hook("subagent_stop", L.on_subagent_stop)
