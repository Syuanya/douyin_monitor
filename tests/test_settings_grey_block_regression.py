from __future__ import annotations

import ast
from pathlib import Path


def test_settings_textfields_are_bounded_to_prevent_windows_grey_blocks() -> None:
    text = Path("app/ui/views/settings_view.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    offenders: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "TextField"):
            continue
        if not (isinstance(func.value, ast.Name) and func.value.id == "ft"):
            continue
        for keyword in node.keywords:
            if keyword.arg == "expand" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                offenders.append(getattr(node, "lineno", -1))
    assert offenders == []
    assert "WIDE_FIELD_WIDTH" in text
    assert "SINGLE_LINE_FIELD_HEIGHT" in text


def test_storage_path_field_is_not_in_wrapped_row_with_buttons() -> None:
    text = Path("app/ui/views/settings_view.py").read_text(encoding="utf-8")
    storage_block = text.split('self._section(\n                    "存储",', 1)[1].split('self._section(\n                    "文件命名",', 1)[0]
    assert "self.download_path_field,\n                        ft.Row" in storage_block
    assert "self.download_path_field,\n                                ft.OutlinedButton" not in storage_block
