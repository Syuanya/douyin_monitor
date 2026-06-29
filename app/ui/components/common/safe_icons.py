from __future__ import annotations

import flet as ft


def icon(name: str, fallback: str = "INFO_OUTLINE"):
    """Return a Flet icon with a stable fallback for older Flet builds."""
    stable = getattr(ft.Icons, "INFO_OUTLINE")
    return getattr(ft.Icons, name, getattr(ft.Icons, fallback, stable))
