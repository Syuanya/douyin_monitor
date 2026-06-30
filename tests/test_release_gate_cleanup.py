from __future__ import annotations

from pathlib import Path


def test_release_gate_cleans_runtime_configs_before_strict_smoke() -> None:
    text = Path("scripts/release_gate.py").read_text(encoding="utf-8")
    assert "def clean_runtime_artifacts" in text
    assert "RUNTIME_CONFIG_FILES" in text
    assert 'ROOT / "data"' in text
    assert 'ROOT / "backups"' in text
    assert 'ROOT / "cache"' in text
    assert "runtime_dir.exists()" in text
    assert "clean_runtime_artifacts()" in text.split('scripts/run_tests.py', 1)[1].split('scripts/smoke_check.py', 1)[0]
