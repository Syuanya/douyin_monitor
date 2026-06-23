from __future__ import annotations

import argparse
import os


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Douyin Monitor Linux Web Console")
    parser.add_argument("--host", default=os.environ.get("DOUYIN_MONITOR_WEB_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("DOUYIN_MONITOR_WEB_PORT", "8080")))
    parser.add_argument("--run-path", default=os.environ.get("DOUYIN_MONITOR_RUN_PATH", os.getcwd()))
    parser.add_argument("--token", default=os.environ.get("DOUYIN_MONITOR_WEB_TOKEN", ""))
    args = parser.parse_args()

    os.environ["DOUYIN_MONITOR_WEB_HOST"] = args.host
    os.environ["DOUYIN_MONITOR_WEB_PORT"] = str(args.port)
    os.environ["DOUYIN_MONITOR_RUN_PATH"] = args.run_path
    if args.token:
        os.environ["DOUYIN_MONITOR_WEB_TOKEN"] = args.token

    from app.web.server import main as run_main

    run_main()


if __name__ == "__main__":
    main()
