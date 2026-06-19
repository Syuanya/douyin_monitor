# douyin_monitor

一个本地运行的抖音内容监控与视频解析工具，支持监控公开主页作品更新、解析抖音/TikTok 链接、下载视频/图集、查看任务记录，并提供 Windows 本地运行与 exe 打包脚本。

> 本项目仅用于用户主动提供的公开链接或有权访问的内容。请自行确认使用场景符合平台规则、法律法规和内容授权边界。

## 功能特性

- 抖音公开主页内容监控：支持添加账号、同步作品、检测更新。
- 视频/图集解析：内置 Douyin/TikTok parser，无需单独启动外部 API 服务。
- 下载任务管理：支持任务中心、进度记录、失败重试提示、下载恢复。
- 本地数据存储：使用 SQLite 保存运行数据，并保留 JSON 兼容镜像。
- Cookie 配置：可在设置页填写 Cookie，提高解析和监控稳定性。
- 桌面应用：基于 Flet，适合 Windows 本地运行。
- Windows 打包：提供一键生成 exe 的 `build_exe_windows.bat`。

## 项目结构

```text
douyin_monitor/
├─ app/                         # 桌面应用、业务逻辑、UI 页面
├─ crawlers/                    # 内置 Douyin/TikTok 解析器
├─ config/                      # 默认配置与语言配置
├─ docs/                        # 隐私、风险与补充文档
├─ locales/                     # 中英文界面文案
├─ packaging/windows/           # PyInstaller / Inno Setup 打包配置
├─ scripts/                     # 检查、迁移、维护、测试、发布脚本
├─ tests/                       # 单元测试
├─ build_exe_windows.bat        # Windows 一键生成 exe
├─ install_windows.bat          # Windows 安装依赖
├─ run_windows.bat              # Windows 启动应用
└─ main.py                      # 程序入口
```

## 环境要求

- Windows 10/11 推荐。
- Python 3.10 - 3.12。
- 建议使用虚拟环境运行。

Python 安装时请勾选 “Add Python to PATH”。

## Windows 快速运行

首次安装依赖：

```bat
install_windows.bat
```

启动桌面应用：

```bat
run_windows.bat
```

如果想在启动前检查运行环境：

```bat
run_windows_checked.bat
```

## 手动运行方式

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

Linux/macOS 可把激活虚拟环境命令换成：

```bash
source .venv/bin/activate
```

## 配置 Cookie

应用可以不配置 Cookie 启动，但解析和监控稳定性会受平台风控影响。推荐在桌面应用的“设置”页填写：

- 抖音 Cookie
- TikTok Cookie（如需解析 TikTok）

Cookie、账号列表、监控记录、解析历史、任务记录、日志、数据库等都属于本地运行数据，不应该提交到 GitHub。

## 生成 Windows exe

在 Windows 上双击或执行：

```bat
build_exe_windows.bat
```

脚本会自动完成：

1. 创建 `.venv` 虚拟环境。
2. 安装 `requirements.txt` 依赖。
3. 安装 PyInstaller。
4. 检查运行环境。
5. 使用 `packaging/windows/douyin_monitor.spec` 生成 exe。

生成结果：

```text
dist\DouyinMonitor\DouyinMonitor.exe
```

如果你想在 CI 或命令行里执行并跳过最后的 `pause`：

```bat
build_exe_windows.bat --no-pause
```

也可以使用更严格的发布流程：

```bat
build_windows_release.bat --skip-tests
```

如需生成安装包，需要先安装 Inno Setup，并确保 `ISCC.exe` 在 PATH 中：

```bat
build_windows_release.bat --installer --skip-tests
```

## 本地数据说明

运行后可能生成这些目录或文件：

- `config/accounts.json`
- `config/cookies.json`
- `config/cookies.secure.json`
- `config/douyin_content_monitor.json`
- `config/parse_history.json`
- `config/task_records.json`
- `config/user_settings.json`
- `data/`
- `logs/`
- `cache/`
- `downloads/`
- `diagnostics/`

这些文件已在 `.gitignore` 中排除。上传 GitHub 前请确认不要手动添加它们。

## 清理本地运行数据

预览将被清理的文件：

```bash
python scripts/clear_local_data.py
```

确认清理配置、Cookie、诊断等本地数据：

```bash
python scripts/clear_local_data.py --yes
```

同时清理 SQLite 数据库：

```bash
python scripts/clear_local_data.py --yes --include-database
```

同时清理日志：

```bash
python scripts/clear_local_data.py --yes --include-logs
```

下载目录默认不会被脚本删除，避免误删用户媒体文件。

## 测试与检查

基础 smoke check：

```bash
python scripts/smoke_check.py --strict
```

运行测试：

```bash
python scripts/run_tests.py
```

创建安全源码发布包：

```bash
python scripts/package_release.py
```

## GitHub 上传前检查清单

- 不包含 `.env`。
- 不包含 Cookie、账号、监控记录、解析历史、任务记录。
- 不包含 `data/`、`logs/`、`cache/`、`downloads/`、`diagnostics/`。
- 不包含 `__pycache__/`、`.pytest_cache/`、`.venv/`。
- `crawlers/*/config.yaml` 中的 `Cookie`、`msToken`、`ttwid.cookie` 等字段为空。
- README 能在 GitHub 首页说明安装、运行和打包方式。

## 风险说明

更完整的隐私和平台风险说明见 [docs/PRIVACY_AND_RISK.md](docs/PRIVACY_AND_RISK.md)。
