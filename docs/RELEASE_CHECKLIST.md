# Release Checklist

## 必跑检查

```bash
python -m compileall -q app crawlers scripts tests main.py
python -m pytest -q
python scripts/run_tests.py
python scripts/smoke_check.py --strict
python scripts/ui_static_check.py
python scripts/ui_layout_regression_check.py
python scripts/verify_legacy_migration.py
python scripts/package_release.py --name douyin_monitor_release.zip
python scripts/verify_windows_package.py --release-zip douyin_monitor_release.zip
```

## 有真实账号/Cookie 时再跑

```bash
python scripts/live_douyin_benchmark.py --parse --urls-file urls.txt --concurrency 3 --limit 100 --allow-network
python scripts/live_douyin_benchmark.py --monitor --allow-network
```

## Windows 实机检查

```powershell
python scripts\check_runtime.py
python scripts\package_release.py --name douyin_monitor_release.zip
python scripts\verify_windows_package.py --release-zip douyin_monitor_release.zip --run-build
.\build_windows_exe.ps1
```

## 发布前人工检查

- 设置页可打开，性能与批量区域显示 Cookie/限速/批任务/分片摘要。
- 诊断页一键检测包含 Cookie 健康度、全局限速器、批量任务、分片下载。
- 任务中心能显示批量任务详情，并能暂停、继续、取消批次。
- release zip 不包含 `logs/`、`data/`、`downloads/`、`.log` 文件。
- 默认不启用大视频分片下载；真实 CDN 验证后再建议用户开启高速模式。
- Cookie 健康记录不包含原始 Cookie，只包含 hash。

## 安装包 / 自动更新 / 签名 / CI/CD

```powershell
python scripts\release_gate.py --package --name douyin_monitor_release.zip
build_windows_release.bat --installer --portable-zip --manifest --sign --skip-tests
python scripts\verify_windows_package.py --release-zip dist\DouyinMonitor-<version>-windows-x64-portable.zip
python scripts\generate_update_manifest.py --artifacts-dir dist\installer --base-url https://github.com/<owner>/<repo>/releases/download/v<version> --version <version>
```

- `dist\installer\DouyinMonitorSetup-<version>.exe` 必须存在。
- `dist\DouyinMonitor-<version>-windows-x64-portable.zip` 必须存在。
- `dist\update_manifest.json` 必须包含安装器和便携包 SHA256。
- 正式发布必须检查 `Get-AuthenticodeSignature` 为有效签名。
- GitHub 仓库需要配置 `WINDOWS_SIGN_CERT_PFX_BASE64` 和 `WINDOWS_SIGN_CERT_PASSWORD` 后再启用正式签名。
- GitHub Release 中必须上传安装器、便携包和 `update_manifest.json`。
