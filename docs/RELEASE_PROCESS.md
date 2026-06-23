# 正式发布流程

1. 更新 `VERSION` 和 `app/core/version.py`。
2. 更新 `CHANGELOG.md`。
3. 本地执行：

```bash
python scripts/release_gate.py --package --name douyin_monitor_release.zip
```

4. Windows 机器执行：

```bat
build_windows_release.bat --installer --portable-zip --manifest --sign
```

5. 检查产物：

```text
dist/DouyinMonitor-<version>-windows-x64-portable.zip
dist/installer/DouyinMonitorSetup-<version>.exe
dist/update_manifest.json
```

6. 校验签名：

```powershell
Get-AuthenticodeSignature dist\installer\DouyinMonitorSetup-<version>.exe
```

7. Windows 实机安装、启动、升级覆盖测试。
8. 发布 Git tag：

```bash
git tag v<version>
git push origin v<version>
```

9. GitHub Actions 自动创建 Release 并上传安装包、便携包、更新清单。
10. 将设置页中的“更新清单 URL”配置为 Release 中的 `update_manifest.json` 地址。
