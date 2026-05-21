from __future__ import annotations

import re
import threading
from collections import defaultdict
from typing import Any, Dict, Optional

from .runtime_core import init, debug, session_label_enabled
from .metrics_setup import _METERS

STATE_LOCK = threading.Lock()
SESSION_START_TS: Dict[str, float] = {}
LLM_START_TS: Dict[str, float] = {}
TOOL_START_TS: Dict[str, float] = {}
APPROVAL_START_TS: Dict[str, float] = {}
SESSION_API_CALLS: Dict[str, int] = defaultdict(int)
SESSION_TURNS: Dict[str, int] = defaultdict(int)

SESSION_SPANS: Dict[str, Any] = {}
LLM_SPANS: Dict[str, Any] = {}
TOOL_SPANS: Dict[str, Any] = {}

def key_for(task_id: str, session_id: str) -> str:
    return task_id or f"session:{session_id}" or f"thread:{threading.get_ident()}"

def session_attrs(session_id: str, **base: Any) -> Dict[str, Any]:
    attrs = {k: v for k, v in base.items() if v is not None}
    if session_id and session_label_enabled():
        attrs["session_id"] = session_id
    return attrs

def add(name: str, value: float, attributes: Optional[Dict[str, Any]] = None) -> None:
    if not init():
        return
    inst = _METERS.get(name)
    if inst is None:
        return
    try:
        inst.add(value, attributes=attributes or {})
    except Exception as exc:
        debug(f"metric {name} add failed: {exc}")

def record(name: str, value: float, attributes: Optional[Dict[str, Any]] = None) -> None:
    if not init():
        return
    inst = _METERS.get(name)
    if inst is None:
        return
    try:
        inst.record(value, attributes=attributes or {})
    except Exception as exc:
        debug(f"metric {name} record failed: {exc}")

def payload_size(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (bytes, bytearray)):
        return len(value)
    if isinstance(value, str):
        return len(value.encode("utf-8", errors="ignore"))
    try:
        import json
        return len(json.dumps(value, default=str, ensure_ascii=False).encode("utf-8"))
    except Exception:
        return len(repr(value).encode("utf-8", errors="ignore"))

_SAFE_CLS_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")

def classify_error(exc: Any) -> str:
    if exc is None:
        return "unknown"
    cls = type(exc).__name__ if isinstance(exc, BaseException) else str(exc)
    msg = str(exc).lower()
    if "rate" in msg and "limit" in msg:
        return "rate_limit"
    if "timeout" in msg or "timed out" in msg:
        return "timeout"
    if "connection" in msg or "connect" in cls.lower():
        return "connection"
    if "auth" in msg or "unauthor" in msg or "401" in msg or "403" in msg:
        return "auth"
    if "quota" in msg or "billing" in msg:
        return "quota"
    if "invalid" in msg or "validation" in msg or "schema" in msg:
        return "invalid_request"
    if "context" in msg and ("length" in msg or "exceed" in msg):
        return "context_length"
    if cls and _SAFE_CLS_PATTERN.match(cls):
        return cls
    return "other"
