"""OTel SDK init, MeterProvider, LoggerProvider, env helpers."""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    from opentelemetry import metrics
    from opentelemetry._logs import set_logger_provider
    from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    _OTEL_AVAILABLE = True
except Exception:
    _OTEL_AVAILABLE = False

_INIT_LOCK = threading.Lock()
_INIT_DONE = False
_INIT_FAILED = False
_LOG_HANDLER: Optional[logging.Handler] = None


class _EventLogger:
    """Structured event logger bridged to OTel via the LoggingHandler.
    
    Hooks call ``r.event_logger.info(msg, extra=attrs)`` and 
    ``r.event_logger.error(msg, extra=attrs)``.  The extra dict keys become
    LogRecord attributes, which the OTel LoggingHandler forwards as OTel
    log-record attributes.
    """
    def __init__(self) -> None:
        self._logger = logging.getLogger("hermes.agent.events")

    def info(self, msg: str, extra: dict | None = None, **kwargs: Any) -> None:
        self._logger.info(msg, extra=extra or {})

    def error(self, msg: str, extra: dict | None = None, **kwargs: Any) -> None:
        self._logger.error(msg, extra=extra or {})


event_logger = _EventLogger()

def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()

def env_bool(name: str, default: bool = False) -> bool:
    val = env(name).lower()
    if not val:
        return default
    return val in {"1", "true", "yes", "on"}

def debug(msg: str) -> None:
    if env_bool("HERMES_OTEL_DEBUG"):
        logger.info("hermes-otel-exporter: %s", msg)

def session_label_enabled() -> bool:
    return env_bool("HERMES_OTEL_SESSION_LABEL", default=False)

class _SessionLogProcessor:
    def on_emit(self, log_data: Any) -> None:
        try:
            attrs = dict(getattr(log_data.log_record, "attributes", {}) or {})
            try:
                from hermes_logging import _current_session_id, _current_task_id  # type: ignore
                sid = _current_session_id.get(None) if hasattr(_current_session_id, "get") else None
                tid = _current_task_id.get(None) if hasattr(_current_task_id, "get") else None
                if sid and "session_id" not in attrs:
                    attrs["session_id"] = sid
                if tid and "task_id" not in attrs:
                    attrs["task_id"] = tid
                log_data.log_record.attributes = attrs
            except Exception:
                pass
        except Exception:
            pass
    def shutdown(self) -> None:
        pass
    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True

def init() -> bool:
    global _INIT_DONE, _INIT_FAILED, _LOG_HANDLER

    if _INIT_DONE:
        return not _INIT_FAILED
    if not _OTEL_AVAILABLE:
        _INIT_DONE = True
        _INIT_FAILED = True
        logger.warning(
            "hermes-otel-exporter: opentelemetry SDK not installed; hooks will no-op."
        )
        return False

    with _INIT_LOCK:
        if _INIT_DONE:
            return not _INIT_FAILED

        endpoint = env("HERMES_OTEL_ENDPOINT", "127.0.0.1:4317")
        service = env("HERMES_OTEL_SERVICE", "hermes-agent")
        environment = env("HERMES_OTEL_ENV", "local")
        insecure = env_bool("HERMES_OTEL_INSECURE", True)

        try:
            resource = Resource.create({
                "service.name": service,
                "deployment.environment": environment,
            })
            reader = PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=endpoint, insecure=insecure),
                export_interval_millis=15000,
            )
            
            from .metrics_setup import _get_views, _build_meters, _METERS
            views = _get_views()
            
            metrics.set_meter_provider(MeterProvider(
                resource=resource, metric_readers=[reader], views=views,
            ))
            _build_meters(metrics.get_meter("hermes.agent"))

            log_provider = LoggerProvider(resource=resource)
            log_provider.add_log_record_processor(_SessionLogProcessor())
            log_provider.add_log_record_processor(BatchLogRecordProcessor(
                OTLPLogExporter(endpoint=endpoint, insecure=insecure)
            ))
            set_logger_provider(log_provider)

            _LOG_HANDLER = LoggingHandler(level=logging.INFO, logger_provider=log_provider)
            try:
                from agent.redact import RedactingFormatter  # type: ignore
                _LOG_HANDLER.setFormatter(RedactingFormatter("%(message)s"))
            except Exception as exc:
                logger.warning("hermes-otel-exporter: RedactingFormatter unavailable")
            for name in ("hermes", "agent", "gateway", "model_tools", "run_agent", "hermes_logging", "hermes.agent.events"):
                logging.getLogger(name).addHandler(_LOG_HANDLER)

            from .tracing import init_tracing
            init_tracing(resource, endpoint, insecure)

            _INIT_DONE = True
            debug(f"initialized: endpoint={endpoint} service={service} env={environment}")
            return True
        except Exception as exc:
            _INIT_DONE = True
            _INIT_FAILED = True
            logger.warning("hermes-otel-exporter: init failed (%s); hooks will no-op", exc)
            return False
