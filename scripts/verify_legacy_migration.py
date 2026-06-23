from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _copy_if_exists(src: Path, dst: Path) -> None:
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)


def _seed_legacy_run_path(path: Path) -> None:
    config = path / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "user_settings.json").write_text(json.dumps({"config_version": 1, "douyin_content_monitor_interval_minutes": "10", "download_resume_enabled": True}, ensure_ascii=False), encoding="utf-8")
    (config / "cookies.json").write_text(json.dumps({"douyin_cookie": "sessionid=legacy; ttwid=legacy;", "tiktok_cookie": ""}, ensure_ascii=False), encoding="utf-8")
    (config / "douyin_content_monitor.json").write_text(json.dumps({"accounts": []}, ensure_ascii=False), encoding="utf-8")


def verify(path: Path) -> dict[str, Any]:
    from app.core.application.service_container import DouyinMonitorServices

    services = DouyinMonitorServices(str(path))
    checks = {
        "settings_loaded": bool(getattr(services.settings_config, "user_config", None) is not None),
        "cookies_loaded": bool(getattr(services.settings_config, "cookies_config", None) is not None),
        "sqlite_schema": bool(getattr(services, "sqlite_store", None) is not None),
        "content_monitor": bool(getattr(services, "douyin_content_monitor", None) is not None),
        "video_parser": bool(getattr(services, "video_parser", None) is not None),
        "batch_store": bool(getattr(services, "batch_job_store", None) is not None),
        "cookie_health_store": bool(getattr(services, "cookie_health_store", None) is not None),
    }
    try:
        services.download_http_client_pool
    except Exception:
        pass
    return {"success": all(checks.values()), "checks": checks}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate old user data can boot with the current service container.")
    parser.add_argument("--source-run-path", default="", help="旧版本运行目录；为空则使用内置旧样本")
    parser.add_argument("--output", default="")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="douyin_legacy_migration_") as tmp:
        temp = Path(tmp)
        if args.source_run_path:
            source = Path(args.source_run_path)
            for name in ("config", "data"):
                _copy_if_exists(source / name, temp / name)
        else:
            _seed_legacy_run_path(temp)
        result = verify(temp)
        result["source"] = args.source_run_path or "sample"
    output = Path(args.output) if args.output else ROOT / "downloads" / "migration_checks" / "legacy_migration_check.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
