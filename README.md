# hermes-otel-exporter

Exports Hermes telemetry (sessions, LLM calls, tokens, cost, tool calls, errors,
and existing log lines) to the local OTel Collector at `127.0.0.1:4317`, which
already routes:

- **Metrics** → Prometheus (`obs-prometheus`)
- **Logs**    → Loki (`obs-loki`)
- **Traces**  → Langfuse (separate plugin handles this)

All visualized in Grafana (`http://localhost:3002`).

## Install

```bash
pip install opentelemetry-api opentelemetry-sdk \
            opentelemetry-exporter-otlp-proto-grpc

hermes plugins enable hermes-otel-exporter
```

The plugin **fails open**: if the SDK is not installed or the collector is
unreachable, hooks no-op silently — Hermes keeps running.

## Verify

After running a Hermes session:

```bash
# Prometheus — should return non-empty
curl -s 'http://127.0.0.1:9090/api/v1/query?query=hermes_session_count_total' | jq

# Loki — should return log lines
curl -sG 'http://127.0.0.1:3110/loki/api/v1/query_range' \
  --data-urlencode 'query={service_name="hermes-agent"}' | jq '.data.result | length'
```

Then open Grafana → "Hermes Agent" dashboard.

## Optional env vars

| Var | Default | Purpose |
|-----|---------|---------|
| `HERMES_OTEL_ENDPOINT` | `127.0.0.1:4317` | OTLP gRPC endpoint |
| `HERMES_OTEL_SERVICE`  | `hermes-agent`   | `service.name` resource attribute (Loki label) |
| `HERMES_OTEL_ENV`      | `local`          | `deployment.environment` |
| `HERMES_OTEL_INSECURE` | `true`           | TLS off for local collector |
| `HERMES_OTEL_DEBUG`    | `false`          | Verbose plugin logging |

## Emitted metrics

| Metric | Type | Labels |
|--------|------|--------|
| `hermes_session_count_total` | counter | `platform` |
| `hermes_session_duration_milliseconds` | histogram | `platform` |
| `hermes_llm_calls_total` | counter | `model`, `provider`, `api_mode` |
| `hermes_llm_duration_milliseconds` | histogram | same |
| `hermes_token_usage_tokens_total` | counter | `model`, `provider`, `type` (input/output/cache_read/cache_write/reasoning) |
| `hermes_cost_usage_USD_total` | counter | `model`, `provider` |
| `hermes_tool_calls_total` | counter | `tool_name`, `success` |
| `hermes_tool_duration_milliseconds` | histogram | `tool_name`, `success` |
| `hermes_errors_total` | counter | `component`, `tool_name` |

(Prometheus normalizes OTel `.` to `_` and appends unit suffixes.)

## Disable

```bash
hermes plugins disable hermes-otel-exporter
```
