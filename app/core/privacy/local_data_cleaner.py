from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CleanCandidate:
    path: Path
    kind: str
    exists: bool


@dataclass(frozen=True, slots=True)
class CleanResult:
    scanned: int
    removed: int
    failed: int
    paths: list[str]
    errors: list[str]


RUNTIME_CONFIG_FILES = (
    "accounts.json",
    "cookies.json",
    "cookies.secure.json",
    "douyin_content_monitor.json",
    "parse_history.json",
    "recordings.json",
    "task_records.json",
    "user_settings.json",
    "web_auth.json",
)

RUNTIME_TOP_LEVEL_DIRS = (
    "diagnostics",
)

DATABASE_FILES = (
    "data/douyin_monitor.sqlite3",
    "data/douyin_monitor.sqlite3-shm",
    "data/douyin_monitor.sqlite3-wal",
)


class LocalDataCleaner:
    """Conservative local runtime/sensitive data cleaner.

    It only touches a small whitelist under the provided run directory. User
    downloaded media is intentionally excluded; users can delete that folder
    manually after verifying its contents.
    """

    def __init__(self, run_path: str | Path):
        self.run_path = Path(run_path).resolve()

    def candidates(self, include_database: bool = False, include_logs: bool = False) -> list[CleanCandidate]:
        items: list[tuple[Path, str]] = []
        items.append((self.run_path / ".env", "secret"))
        for name in RUNTIME_CONFIG_FILES:
            items.append((self.run_path / "config" / name, "config"))
        for name in RUNTIME_TOP_LEVEL_DIRS:
            items.append((self.run_path / name, "runtime_dir"))
        if include_database:
            for name in DATABASE_FILES:
                items.append((self.run_path / name, "database"))
        if include_logs:
            logs_dir = self.run_path / "logs"
            if logs_dir.exists():
                for path in sorted(logs_dir.glob("*.log")):
                    items.append((path, "log"))
        return [CleanCandidate(path=path, kind=kind, exists=path.exists()) for path, kind in items]

    def clean(
        self,
        *,
        dry_run: bool = True,
        include_database: bool = False,
        include_logs: bool = False,
    ) -> CleanResult:
        candidates = self.candidates(include_database=include_database, include_logs=include_logs)
        removed: list[str] = []
        errors: list[str] = []
        for item in candidates:
            if not item.exists:
                continue
            path = item.path.resolve()
            if not self._inside_run_path(path):
                errors.append(f"refuse outside run path: {path}")
                continue
            if dry_run:
                removed.append(str(path))
                continue
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                removed.append(str(path))
            except Exception as exc:
                errors.append(f"{path}: {exc}")
        return CleanResult(
            scanned=len(candidates),
            removed=len(removed),
            failed=len(errors),
            paths=removed,
            errors=errors,
        )

    def _inside_run_path(self, path: Path) -> bool:
        try:
            path.relative_to(self.run_path)
            return True
        except ValueError:
            return False
