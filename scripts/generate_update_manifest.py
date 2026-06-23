from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist"


def read_version() -> str:
    version_file = ROOT / "VERSION"
    if version_file.exists():
        text = version_file.read_text(encoding="utf-8").strip()
        if text:
            return text.lstrip("vV")
    namespace: dict[str, str] = {}
    exec((ROOT / "app" / "core" / "version.py").read_text(encoding="utf-8"), namespace)
    return str(namespace.get("APP_VERSION") or "0.0.0").lstrip("vV")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def guess_kind(path: Path) -> str:
    lower = path.name.lower()
    if lower.endswith(".exe") or "setup" in lower or "installer" in lower:
        return "installer"
    if lower.endswith(".zip"):
        return "portable"
    return "artifact"


def build_manifest(*, artifacts: list[Path], base_url: str, version: str, channel: str, notes: str, mandatory: bool) -> dict:
    normalized_base = base_url.rstrip("/")
    assets = []
    for path in artifacts:
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(path)
        url = f"{normalized_base}/{path.name}" if normalized_base else path.name
        assets.append(
            {
                "name": path.name,
                "url": url,
                "sha256": sha256_file(path),
                "size": path.stat().st_size,
                "kind": guess_kind(path),
                "platform": "windows-x64" if path.suffix.lower() in {".exe", ".zip"} else "any",
                "content_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                "silent_args": "/VERYSILENT /NORESTART /CLOSEAPPLICATIONS" if guess_kind(path) == "installer" else "",
            }
        )
    return {
        "schema_version": 1,
        "app": "douyin_monitor",
        "version": version.lstrip("vV"),
        "channel": channel,
        "mandatory": mandatory,
        "published_at": int(time.time()),
        "release_notes": notes,
        "assets": assets,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate update_manifest.json for Douyin Monitor releases.")
    parser.add_argument("--artifact", action="append", default=[], help="Artifact path. Can be specified multiple times.")
    parser.add_argument("--artifacts-dir", default="", help="Directory whose .exe/.zip artifacts should be added.")
    parser.add_argument("--base-url", default=os.environ.get("UPDATE_BASE_URL", ""), help="Public base URL where artifacts are hosted.")
    parser.add_argument("--version", default=os.environ.get("APP_VERSION", read_version()))
    parser.add_argument("--channel", default=os.environ.get("UPDATE_CHANNEL", "stable"), choices=["stable", "beta", "dev"])
    parser.add_argument("--notes", default=os.environ.get("RELEASE_NOTES", ""))
    parser.add_argument("--mandatory", action="store_true")
    parser.add_argument("--output", default=str(DIST_DIR / "update_manifest.json"))
    args = parser.parse_args()

    artifacts = [Path(item).resolve() for item in args.artifact]
    if args.artifacts_dir:
        directory = Path(args.artifacts_dir).resolve()
        if directory.exists():
            artifacts.extend(sorted(path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in {".zip", ".exe"}))
    if not artifacts:
        raise SystemExit("No artifacts supplied. Use --artifact or --artifacts-dir.")
    manifest = build_manifest(
        artifacts=artifacts,
        base_url=args.base_url,
        version=args.version,
        channel=args.channel,
        notes=args.notes,
        mandatory=args.mandatory,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"update manifest OK: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
