from __future__ import annotations

import re
from dataclasses import dataclass


_VERSION_RE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+.]?([0-9A-Za-z_.-]+))?$")


@dataclass(frozen=True, order=True)
class ComparableVersion:
    major: int
    minor: int = 0
    patch: int = 0
    prerelease_rank: int = 1
    prerelease: str = ""


def normalize_version(value: str) -> str:
    text = str(value or "").strip()
    if text.lower().startswith("version="):
        text = text.split("=", 1)[1].strip()
    return text.lstrip("vV") or "0.0.0"


def parse_version(value: str) -> ComparableVersion:
    text = normalize_version(value)
    match = _VERSION_RE.match(text)
    if not match:
        return ComparableVersion(0, 0, 0, 0, text)
    major = int(match.group(1) or 0)
    minor = int(match.group(2) or 0)
    patch = int(match.group(3) or 0)
    prerelease = match.group(4) or ""
    # Stable releases sort after prereleases with the same numeric version.
    prerelease_rank = 0 if prerelease else 1
    return ComparableVersion(major, minor, patch, prerelease_rank, prerelease)


def is_newer_version(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)
