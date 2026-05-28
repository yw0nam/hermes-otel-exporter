"""Top-level plugin entry — thin shim into the real ``hermes_otel_exporter`` package.

The hermes-agent plugin loader requires ``<plugin_dir>/__init__.py`` at the
plugin directory root (see ``hermes_cli/plugins.py:_load_directory_module``).
The actual implementation lives under ``src/hermes_otel_exporter/`` so the
project can be developed and tested with standard uv + pyproject workflows.

All this file does is:
  1. Put ``<plugin_dir>/src`` on ``sys.path`` (idempotent).
  2. Re-export ``register`` from the real package.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from hermes_otel_exporter import register  # noqa: E402,F401
