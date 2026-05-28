# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- OpenTelemetry span context-detach `ValueError`
  (`"Token was created in a different Context"`) that fired whenever a tool /
  LLM / session pre-hook and its post-hook ran in different asyncio tasks or
  threads. The plugin previously stored a `@contextmanager` returned by
  `start_as_current_span()` and called `__exit__()` from the post-hook, which
  violates the contract that a `contextvars.Token` must be reset in the same
  `Context` where it was created. `tracing.start_*_span` now uses the
  lower-level `tracer.start_span()` and hooks call `span.end()` directly —
  safe across any execution context.

### Added
- `src/` layout — package now lives at `src/hermes_otel_exporter/` (PEP 8
  underscore name). A thin shim `__init__.py` at the plugin root re-exports
  `register` so the hermes-agent plugin loader continues to work unchanged.
- `pyproject.toml` with hatchling build backend and uv-managed dependencies
  + `uv.lock`. Develop with `uv sync` / `uv run pytest`.
- Pytest suite with 27 tests covering span factories, the three hook
  lifecycles, parent-child span linking, error paths, and **cross-context
  regression tests** that fail loudly if the original context-detach
  anti-pattern is reintroduced.
- `runtime_core.event_logger` — a structured logger that bridges hook output
  into OTel log records via the standard `logging` module.

### Changed
- `tracing.start_session_span` / `start_llm_span` / `start_tool_span` no
  longer yield via `@contextlib.contextmanager`; they return the raw span
  (or `None` when tracing is disabled). Internal-only — the plugin's
  external `register(ctx)` API is unchanged.
- `SESSION_SPANS` / `LLM_SPANS` / `TOOL_SPANS` now store the bare span
  object instead of the `(span, span_ctx)` tuple.

## [0.1.0] — 2026-05-21

### Added
- Initial release. Exports Hermes session / LLM / tool metrics, logs, and
  traces to a local OpenTelemetry Collector (Prometheus + Loki + Tempo /
  Grafana stack). Opt-in via `hermes plugins enable hermes-otel-exporter`.
- Hooks: `on_session_start`, `on_session_end`, `pre_llm_call`,
  `post_llm_call`, `pre_api_request`, `post_api_request`, `pre_tool_call`,
  `post_tool_call`, `transform_tool_result`, `pre_approval_request`,
  `post_approval_response`, `pre_gateway_dispatch`, `subagent_stop`.

[Unreleased]: https://github.com/yw0nam/hermes-otel-exporter/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/yw0nam/hermes-otel-exporter/releases/tag/v0.1.0
