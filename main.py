from __future__ import annotations

import multiprocessing
import os
import sys

import flet as ft
from dotenv import load_dotenv

from app.core.runtime.bundled_env import setup_bundled_flet_view
from app.standalone.douyin_monitor_app import main as douyin_monitor_main
from app.utils.logger import logger

ASSETS_DIR = "assets"


def _run_path() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


async def main(page: ft.Page) -> None:
    await douyin_monitor_main(page, _run_path())


if __name__ == "__main__":
    load_dotenv()
    multiprocessing.freeze_support()
    logger.debug("Running standalone Douyin monitor desktop app")
    setup_bundled_flet_view()
    ft.run(main=main, assets_dir=ASSETS_DIR)
