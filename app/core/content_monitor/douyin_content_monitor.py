from __future__ import annotations

"""Backward-compatible import shim for the content-monitor facade.

New code should import from ``app.core.content_monitor.facade`` and domain
models from ``app.core.content_monitor.models``.  This module exists to keep
older UI code, tests and third-party integrations working.
"""

from .facade import DouyinContentMonitorManager
from .models import DouyinContentItem, DouyinMonitorAccount

__all__ = ["DouyinContentItem", "DouyinMonitorAccount", "DouyinContentMonitorManager"]
