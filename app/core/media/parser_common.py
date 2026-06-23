from __future__ import annotations

import asyncio
import inspect
import os
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

import yaml

from ..parser.risk_model import classify_parser_failure
from .cookie_utils import parse_cookie_pool, sanitize_cookie_header
from .parser_models import ParseDownloadEvent, ParseFailure, ParseProgress, ParsedVideoResult, VideoParseBatchResult, normalize_work_url

ParserCallable = Callable[..., dict[str, Any] | Awaitable[dict[str, Any]]]
