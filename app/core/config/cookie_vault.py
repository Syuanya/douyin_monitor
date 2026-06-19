from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from typing import Any


class CookieVault:
    """Best-effort local cookie vault.

    Windows uses DPAPI. Other platforms use an explicit compatibility fallback
    to keep the app dependency-free and backwards-compatible.
    """

    def __init__(self, vault_path: str):
        self.vault_path = Path(vault_path)

    def save(self, cookies: dict[str, Any]) -> str:
        payload = json.dumps(cookies or {}, ensure_ascii=False).encode("utf-8")
        provider, protected = protect_bytes(payload)
        self.vault_path.parent.mkdir(parents=True, exist_ok=True)
        self.vault_path.write_text(
            json.dumps(
                {"version": 1, "provider": provider, "payload": base64.b64encode(protected).decode("ascii")},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return provider

    def load(self) -> dict[str, Any]:
        if not self.vault_path.is_file():
            return {}
        data = json.loads(self.vault_path.read_text(encoding="utf-8"))
        protected = base64.b64decode(str(data.get("payload") or ""))
        raw = unprotect_bytes(protected, str(data.get("provider") or ""))
        value = json.loads(raw.decode("utf-8"))
        return value if isinstance(value, dict) else {}


def protect_bytes(data: bytes) -> tuple[str, bytes]:
    if sys.platform.startswith("win"):
        try:
            return "windows-dpapi", _crypt_protect_data(data)
        except Exception:
            pass
    return "base64-compat", data


def unprotect_bytes(data: bytes, provider: str) -> bytes:
    if provider == "windows-dpapi":
        return _crypt_unprotect_data(data)
    return data


def _crypt_protect_data(data: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    in_buffer = ctypes.create_string_buffer(data)
    in_blob = DATA_BLOB(len(data), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_char)))
    out_blob = DATA_BLOB()
    if not crypt32.CryptProtectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
        raise OSError("CryptProtectData failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _crypt_unprotect_data(data: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    in_buffer = ctypes.create_string_buffer(data)
    in_blob = DATA_BLOB(len(data), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_char)))
    out_blob = DATA_BLOB()
    if not crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
        raise OSError("CryptUnprotectData failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)
