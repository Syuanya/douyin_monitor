from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def inspect_release_zip(path: Path) -> dict:
    if not path.exists():
        return {"ok": False, "reason": f"release zip not found: {path}"}
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
    required = [
        "main.py",
        "requirements.txt",
        "packaging/windows/douyin_monitor.spec",
        "packaging/windows/installer.iss",
        "packaging/windows/apply_update.ps1",
        "scripts/build_windows_release.py",
        "scripts/generate_update_manifest.py",
        "scripts/sign_windows_artifacts.py",
        "config/default_settings.json",
        "app/core/update/updater_service.py",
    ]
    missing = [item for item in required if not any(name.endswith(item) for name in names)]
    forbidden = [name for name in names if "/logs/" in f"/{name}" or name.endswith(".log")]
    return {"ok": not missing and not forbidden, "missing": missing, "forbidden": forbidden[:20], "file_count": len(names)}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate Windows package structure and optionally run Windows packaging script.")
    parser.add_argument("--release-zip", default=str(ROOT / "douyin_monitor_release.zip"))
    parser.add_argument("--run-build", action="store_true", help="Windows only: invoke build_windows_exe.ps1")
    parser.add_argument("--strict-windows", action="store_true", help="fail on non-Windows")
    parser.add_argument("--output", default="")
    args = parser.parse_args(argv)
    result = {"platform": platform.platform(), "zip": inspect_release_zip(Path(args.release_zip)), "windows_build": "skipped"}
    if args.run_build:
        if not sys.platform.startswith("win"):
            result["windows_build"] = "skipped_non_windows"
            if args.strict_windows:
                result["success"] = False
        else:
            completed = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "build_windows_exe.ps1")], cwd=str(ROOT), text=True, capture_output=True)
            result["windows_build"] = {"returncode": completed.returncode, "stdout_tail": completed.stdout[-4000:], "stderr_tail": completed.stderr[-4000:]}
    result.setdefault("success", bool(result["zip"].get("ok")) and (result["windows_build"] in {"skipped", "skipped_non_windows"} or isinstance(result["windows_build"], dict) and result["windows_build"].get("returncode") == 0))
    output = Path(args.output) if args.output else ROOT / "downloads" / "windows_checks" / "windows_package_check.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
