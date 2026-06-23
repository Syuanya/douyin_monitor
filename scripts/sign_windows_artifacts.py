from __future__ import annotations

import argparse
import base64
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TIMESTAMP = "http://timestamp.digicert.com"


def collect_artifacts(paths: list[str]) -> list[Path]:
    result: list[Path] = []
    for item in paths:
        path = Path(item)
        if path.is_dir():
            result.extend(sorted(p for p in path.rglob("*") if p.suffix.lower() in {".exe", ".dll", ".msi"}))
        elif path.exists() and path.suffix.lower() in {".exe", ".dll", ".msi"}:
            result.append(path)
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in result:
        resolved = path.resolve()
        if resolved not in seen:
            unique.append(resolved)
            seen.add(resolved)
    return unique


def materialize_pfx_from_env() -> Path | None:
    encoded = os.environ.get("WINDOWS_SIGN_CERT_PFX_BASE64", "").strip()
    if not encoded:
        return None
    tmp_dir = Path(tempfile.mkdtemp(prefix="douyin-monitor-sign-"))
    pfx = tmp_dir / "certificate.pfx"
    pfx.write_bytes(base64.b64decode(encoded))
    return pfx


def build_signtool_command(signtool: str, artifact: Path, *, cert_path: str, cert_password: str, cert_subject: str, timestamp_url: str) -> list[str]:
    cmd = [signtool, "sign", "/fd", "SHA256", "/tr", timestamp_url, "/td", "SHA256"]
    if cert_path:
        cmd.extend(["/f", cert_path])
        if cert_password:
            cmd.extend(["/p", cert_password])
    elif cert_subject:
        cmd.extend(["/n", cert_subject])
    else:
        raise ValueError("no signing certificate configured")
    cmd.append(str(artifact))
    return cmd


def main() -> int:
    parser = argparse.ArgumentParser(description="Sign Windows exe/dll/msi artifacts with signtool.")
    parser.add_argument("paths", nargs="*", default=[str(ROOT / "dist")], help="Files or directories to sign.")
    parser.add_argument("--signtool", default=os.environ.get("SIGNTOOL_PATH", "signtool.exe"))
    parser.add_argument("--cert-path", default=os.environ.get("WINDOWS_SIGN_CERT_PATH", ""))
    parser.add_argument("--cert-password", default=os.environ.get("WINDOWS_SIGN_CERT_PASSWORD", ""))
    parser.add_argument("--cert-subject", default=os.environ.get("WINDOWS_SIGN_CERT_SUBJECT", ""))
    parser.add_argument("--timestamp-url", default=os.environ.get("WINDOWS_SIGN_TIMESTAMP_URL", DEFAULT_TIMESTAMP))
    parser.add_argument("--strict", action="store_true", help="Fail if signing cannot run. Default is best-effort.")
    args = parser.parse_args()

    pfx_from_env = materialize_pfx_from_env()
    cert_path = args.cert_path or (str(pfx_from_env) if pfx_from_env else "")
    artifacts = collect_artifacts(args.paths)
    if not artifacts:
        print("sign_windows_artifacts: no signable artifacts found")
        return 0
    signtool = shutil.which(args.signtool) or args.signtool
    if not shutil.which(signtool) and not Path(signtool).exists():
        message = f"signtool not found: {args.signtool}"
        print(f"sign_windows_artifacts: {message}")
        return 1 if args.strict else 0
    if not cert_path and not args.cert_subject:
        message = "no certificate configured; set WINDOWS_SIGN_CERT_PFX_BASE64, WINDOWS_SIGN_CERT_PATH, or WINDOWS_SIGN_CERT_SUBJECT"
        print(f"sign_windows_artifacts: {message}")
        return 1 if args.strict else 0

    failures: list[str] = []
    for artifact in artifacts:
        cmd = build_signtool_command(
            signtool,
            artifact,
            cert_path=cert_path,
            cert_password=args.cert_password,
            cert_subject=args.cert_subject,
            timestamp_url=args.timestamp_url,
        )
        print("+ " + " ".join(cmd[:-1] + [artifact.name]))
        completed = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True)
        if completed.returncode != 0:
            failures.append(f"{artifact}: {completed.stderr.strip() or completed.stdout.strip()}")
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print(f"sign_windows_artifacts: signed {len(artifacts)} artifact(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
