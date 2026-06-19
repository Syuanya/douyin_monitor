from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.media.cookie_utils import cookie_looks_usable, sanitize_cookie_header


async def check_parse_url(run_path: Path, url: str) -> dict[str, str]:
    from app.core.media.video_parser_service import VideoParserService

    parser = VideoParserService(str(run_path), parse_concurrency=1)
    data = await parser.parse_url(url)
    item_id = str(data.get("aweme_id") or data.get("id") or "")
    return {"status": "ok" if data else "empty", "item_id": item_id}


def check_cookie(run_path: Path) -> dict[str, str]:
    cookies: dict[str, object] = {}
    try:
        from app.core.config.config_manager import ConfigManager

        manager = ConfigManager(str(run_path))
        loaded = manager.load_cookies_config()
        cookies = loaded if isinstance(loaded, dict) else {}
    except Exception:
        cookie_path = run_path / "config" / "cookies.json"
        try:
            loaded = json.loads(cookie_path.read_text(encoding="utf-8")) if cookie_path.exists() else {}
            cookies = loaded if isinstance(loaded, dict) else {}
        except Exception:
            cookies = {}
    douyin_cookie = sanitize_cookie_header(str(cookies.get("douyin_cookie") or ""))
    return {
        "status": "ok" if cookie_looks_usable(douyin_cookie) else "missing_or_short",
        "douyin_cookie": "configured" if douyin_cookie else "empty",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run opt-in real Douyin platform checks.")
    parser.add_argument("--run-path", default=str(ROOT), help="Project/run directory.")
    parser.add_argument("--douyin-url", default="", help="Optional real Douyin share/work URL to parse.")
    parser.add_argument("--require-url", action="store_true", help="Fail if --douyin-url is not provided.")
    args = parser.parse_args()

    run_path = Path(args.run_path)
    cookie = check_cookie(run_path)
    print(f"real_platform_check: cookie={cookie['status']} ({cookie['douyin_cookie']})")

    if not args.douyin_url:
        if args.require_url:
            print("real_platform_check: missing --douyin-url")
            return 2
        print("real_platform_check: skipped live parse; provide --douyin-url to validate real parsing")
        return 0

    try:
        result = asyncio.run(check_parse_url(run_path, args.douyin_url))
    except Exception as exc:
        print(f"real_platform_check: parse failed: {exc}")
        return 1
    print(f"real_platform_check: parse={result['status']} item_id={result['item_id'] or '-'}")
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
