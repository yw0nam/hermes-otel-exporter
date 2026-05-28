"""Shared fixtures for hermes-otel-exporter tests.

The plugin package lives at ``src/hermes_otel_exporter`` and is on
``sys.path`` via ``pythonpath = ["src"]`` in ``pyproject.toml``.
"""
from __future__ import annotations

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from hermes_otel_exporter import runtime_helpers as rh
from hermes_otel_exporter import tracing as tracing_mod


@pytest.fixture
def exporter() -> InMemorySpanExporter:
    """Fresh in-memory exporter wired into the plugin's tracer slot."""
    exp = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exp))
    # We patch only the plugin's _tracer reference, not the global OTel
    # provider, so concurrent test runs don't collide on the global state.
    saved = tracing_mod._tracer
    tracing_mod._tracer = provider.get_tracer("test")
    yield exp
    tracing_mod._tracer = saved
    provider.shutdown()


@pytest.fixture(autouse=True)
def _clean_state():
    """Reset module-level state dicts before and after every test."""
    _state_dicts = (
        rh.SESSION_START_TS, rh.LLM_START_TS, rh.TOOL_START_TS,
        rh.APPROVAL_START_TS, rh.SESSION_API_CALLS, rh.SESSION_TURNS,
        rh.SESSION_SPANS, rh.LLM_SPANS, rh.TOOL_SPANS,
    )
    for d in _state_dicts:
        d.clear()
    yield
    for d in _state_dicts:
        d.clear()


@pytest.fixture
def no_tracer():
    """Force ``tracing._tracer`` to None to exercise the disabled-tracing path."""
    saved = tracing_mod._tracer
    tracing_mod._tracer = None
    yield
    tracing_mod._tracer = saved
