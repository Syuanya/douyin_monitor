# 安装包、自动更新、代码签名与 CI/CD

本文档说明正式 Windows 发布链路。源码 zip 仍保留用于开发和审查；面向普通用户应发布 Windows 安装包与便携包。

## 1. Windows 安装包

Windows 发布脚本：

```bat
build_windows_release.bat --installer --portable-zip --manifest
```

产物：

```text
dist/DouyinMonitor/                              # PyInstaller 便携目录
dist/DouyinMonitor-<version>-windows-x64-portable.zip
dist/installer/DouyinMonitorSetup-<version>.exe
dist/update_manifest.json
```

安装包使用 Inno Setup：

```text
packaging/windows/installer.iss
```

安装器支持：

- 普通安装 / 覆盖升级
- 开始菜单快捷方式
- 可选桌面快捷方式
- 卸载入口
- `/VERYSILENT /NORESTART /CLOSEAPPLICATIONS` 静默更新参数

## 2. 自动更新

自动更新基于远程 `update_manifest.json`，示例：

```json
{
  "schema_version": 1,
  "app": "douyin_monitor",
  "version": "0.9.9",
  "channel": "stable",
  "assets": [
    {
      "name": "DouyinMonitorSetup-0.9.9.exe",
      "url": "https://github.com/<owner>/<repo>/releases/download/v0.9.9/DouyinMonitorSetup-0.9.9.exe",
      "sha256": "...",
      "size": 12345678,
      "kind": "installer",
      "platform": "windows-x64",
      "silent_args": "/VERYSILENT /NORESTART /CLOSEAPPLICATIONS"
    }
  ]
}
```

生成清单：

```bash
python scripts/generate_update_manifest.py \
  --artifact dist/installer/DouyinMonitorSetup-0.9.9.exe \
  --artifact dist/DouyinMonitor-0.9.9-windows-x64-portable.zip \
  --base-url https://github.com/<owner>/<repo>/releases/download/v0.9.9 \
  --version 0.9.9 \
  --output dist/update_manifest.json
```

应用侧自动更新服务：

```text
app/core/update/updater_service.py
```

更新策略：

- 默认不静默更新。
- 下载后校验 SHA256 和大小。
- 安装器更新可以启动 `/VERYSILENT /NORESTART /CLOSEAPPLICATIONS`。
- 便携 zip 不会自动覆盖正在运行的程序目录，只会打开下载目录，避免损坏运行中程序。

## 3. 代码签名

签名脚本：

```bash
python scripts/sign_windows_artifacts.py dist --strict
```

支持三种证书来源：

```text
WINDOWS_SIGN_CERT_PFX_BASE64   # GitHub Secrets 中保存的 base64 pfx
WINDOWS_SIGN_CERT_PATH         # 本地 pfx 路径
WINDOWS_SIGN_CERT_SUBJECT      # Windows 证书库中的证书主题
WINDOWS_SIGN_CERT_PASSWORD     # pfx 密码
WINDOWS_SIGN_TIMESTAMP_URL     # 默认 http://timestamp.digicert.com
```

本地示例：

```powershell
$env:WINDOWS_SIGN_CERT_PATH="D:\certs\code-signing.pfx"
$env:WINDOWS_SIGN_CERT_PASSWORD="***"
python scripts/sign_windows_artifacts.py dist --strict
```

GitHub Actions 中建议配置：

```text
Secrets:
  WINDOWS_SIGN_CERT_PFX_BASE64
  WINDOWS_SIGN_CERT_PASSWORD
  WINDOWS_SIGN_CERT_SUBJECT       # 可选

Variables:
  WINDOWS_SIGN_TIMESTAMP_URL      # 可选
```

没有证书时，签名脚本默认 best-effort，不会阻断开发包构建；正式发布应使用 `--strict`。

## 4. CI/CD

CI：

```text
.github/workflows/ci.yml
```

执行：

- 依赖安装
- Ruff
- `scripts/release_gate.py`
- 源码 release zip 打包
- 上传 CI artifact

Windows Release：

```text
.github/workflows/release.yml
```

触发：

- 推送 `v*` tag
- 手动 `workflow_dispatch`

执行：

- Windows 环境安装依赖
- 安装 Inno Setup
- 构建 PyInstaller 便携目录
- 生成便携 zip
- 生成 Inno Setup 安装包
- 可选代码签名
- 生成 `update_manifest.json`
- 上传 GitHub Release artifact
- 创建或更新 GitHub Release

## 5. 发布前强制检查

本地发布闸门：

```bash
python scripts/release_gate.py --package --name douyin_monitor_release.zip
```

Windows 发布验证：

```bash
python scripts/verify_windows_package.py --release-zip dist/DouyinMonitor-<version>-windows-x64-portable.zip
```

正式发布前仍需要真实 Windows 实机运行验证和有效 Cookie/IP 环境下的线上压测。
