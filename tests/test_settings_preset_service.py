from __future__ import annotations

from app.core.ui_services.settings_preset_service import SettingsPresetService
from app.core.ui_services.settings_validator import SettingsValidator


def test_stable_preset_applies_low_concurrency_and_risk_guards() -> None:
    result = SettingsPresetService.apply(
        {
            "max_parallel_downloads": 8,
            "video_parse_concurrency": 8,
            "development_bypass_risk_controls_enabled": True,
        },
        "stable",
    )
    assert result.values["download_strategy_preset"] == "conservative"
    assert result.values["max_parallel_downloads"] == 1
    assert result.values["video_parse_concurrency"] == 2
    assert result.values["global_request_limiter_enabled"] is True
    assert result.values["cookie_cooldown_enabled"] is True
    assert result.values["risk_backoff_enabled"] is True
    assert "max_parallel_downloads" in result.changed_keys


def test_fast_preset_enables_batch_pipeline_and_segmented_download() -> None:
    result = SettingsPresetService.apply({}, "fast")
    assert result.values["download_strategy_preset"] == "fast"
    assert result.values["batch_parse_download_pipeline_enabled"] is True
    assert result.values["segmented_download_enabled"] is True
    assert result.values["batch_download_concurrency"] > 3


def test_diagnostic_preset_matches_validator_development_override() -> None:
    result = SettingsPresetService.apply({}, "diagnostic")
    validation = SettingsValidator.validate(result.values, {})
    assert validation.values["development_bypass_risk_controls_enabled"] is True
    assert validation.values["global_request_limiter_enabled"] is False
    assert validation.values["cookie_cooldown_enabled"] is False
    assert validation.values["risk_backoff_enabled"] is False


def test_unknown_preset_falls_back_to_standard() -> None:
    result = SettingsPresetService.apply({}, "missing")
    assert result.preset.key == "standard"
    assert result.values["download_strategy_preset"] == "standard"
