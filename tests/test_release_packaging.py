from __future__ import annotations

import zipfile
import unittest

from scripts import package_release


class ReleasePackagingTest(unittest.TestCase):
    def test_release_zip_excludes_runtime_sensitive_files(self) -> None:
        out_path = package_release.build_release_zip("test_release.zip")
        try:
            problems = package_release.inspect_zip(out_path)
            self.assertEqual(problems, [])
            with zipfile.ZipFile(out_path) as zf:
                names = set(zf.namelist())
            self.assertNotIn(".env", names)
            self.assertNotIn("config/cookies.json", names)
            self.assertNotIn("config/cookies.secure.json", names)
            self.assertNotIn("config/douyin_content_monitor.json", names)
            self.assertFalse(any(name.startswith("logs/") for name in names))
            self.assertFalse(any(name.startswith("data/") for name in names))
            self.assertFalse(any(name.startswith("diagnostics/") for name in names))
            self.assertIn("README.md", names)
            self.assertIn("CHANGELOG.md", names)
            self.assertIn("VERSION", names)
            self.assertIn("docs/PRIVACY_AND_RISK.md", names)
            self.assertIn("config/default_settings.json", names)
            self.assertIn("app/core/version.py", names)
            self.assertIn("app/core/diagnostics/__init__.py", names)
            self.assertIn("app/core/diagnostics/diagnostic_tools.py", names)
            self.assertIn("app/core/diagnostics/health_check_service.py", names)
            self.assertIn("app/core/media/resumable_download.py", names)
            self.assertIn("app/core/runtime/download_recovery_service.py", names)
            self.assertIn("app/core/parser/registry.py", names)
            self.assertIn("app/core/parser/risk_model.py", names)
            self.assertIn("app/core/privacy/local_data_cleaner.py", names)
            self.assertIn("app/ui/views/douyin_content_bulk_components.py", names)
            self.assertIn("app/ui/views/douyin_content_item_cards.py", names)
            self.assertIn("app/ui/views/download_history_view.py", names)
            self.assertIn("app/core/errors.py", names)
            self.assertIn("build_windows_exe.ps1", names)
            self.assertIn("build_windows_release.bat", names)
            self.assertIn("scripts/build_windows_release.py", names)
            self.assertIn("scripts/clear_local_data.py", names)
            self.assertIn("scripts/flet_ui_smoke_check.py", names)
            self.assertIn("scripts/maintain_sqlite.py", names)
            self.assertIn("scripts/real_platform_check.py", names)
            self.assertIn("scripts/ui_layout_regression_check.py", names)
            self.assertIn("scripts/version_check.py", names)
            self.assertIn("packaging/windows/douyin_monitor.spec", names)
            self.assertIn("packaging/windows/installer.iss", names)
            self.assertIn("packaging/windows/apply_update.ps1", names)
            self.assertIn("scripts/generate_update_manifest.py", names)
            self.assertIn("scripts/sign_windows_artifacts.py", names)
            self.assertIn("scripts/release_gate.py", names)
            self.assertIn("app/core/update/updater_service.py", names)
            self.assertIn("docs/INSTALLER_AUTO_UPDATE_SIGNING_CICD.md", names)
            self.assertIn("run_windows_checked.bat", names)
        finally:
            out_path.unlink(missing_ok=True)
