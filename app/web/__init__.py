"""Headless web server for Douyin Monitor.

The web package is optional. Desktop/Flet users do not need FastAPI installed;
Linux deployments install ``requirements-web.txt`` and run ``python -m app.web.server``.
"""

__all__ = ["create_app"]


def create_app(*args, **kwargs):
    from .server import create_app as _create_app

    return _create_app(*args, **kwargs)
