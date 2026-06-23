# Douyin Monitor

Douyin Monitor 是一个本地运行的抖音内容监控、视频/图集解析、批量下载和 Web 远程管理工具。项目同时提供 Windows 桌面端和 Linux/Docker Web 控制台，适合个人在本机或私有服务器中管理公开主页作品更新、解析链接、下载媒体文件和查看任务状态。

> 本项目仅用于用户主动提供的公开链接或用户有权访问的内容。请自行确认使用行为符合平台规则、法律法规和内容授权边界。Cookie、账号、下载记录、解析历史、任务记录、备份文件等运行数据只应保存在本地，不应提交到 GitHub。

## 当前版本

当前版本：`1.0.0`

最近版本重点：

- Web 端改为接近 Windows 桌面端的页面结构，减少功能分散。
- 新增 Linux/Docker Web 控制台，可通过浏览器远程访问。
- 存储页改为网盘式文件管理器布局，支持网格/列表切换、文件夹导航、面包屑、返回上一级。
- 存储页支持已下载视频和图片预览、沉浸式预览、打开/下载、删除。
- 视频解析结果改为简洁卡片，默认不展示完整 JSON，并补齐单条结果下载按钮。
- 内容监控、新作品箱、批量导入、任务中心、下载队列、下载历史、诊断、设置、Cookie 管理、备份恢复等能力已收敛到主页面内。
- 修复 Web SSE 实时事件中字符串时间解析失败的问题。
- 修复存储模块相对路径/绝对路径混用导致打开文件夹、预览文件、返回上一级失效的问题。

## 界面预览

项目保留桌面端和 Web 端两种使用形态。截图文件位于 `docs/images/`：

| 页面 | 截图 |
|---|---|
| 首页仪表盘 | `docs/images/01-home-dashboard.png` |
| 内容监控 | `docs/images/02-content-monitor.png` |
| 作品同步与下载 | `docs/images/03-work-gallery.png` |
| 视频解析 | `docs/images/04-video-parser.png` |
| 媒体预览 | `docs/images/05-media-preview.png` |

## 主要功能

### 内容监控

- 添加抖音公开主页链接并维护账号列表。
- 支持监控中、未监控、有新作品、异常账号等状态筛选。
- 支持手动检测、批量检测、作品同步、自动下载和新作品标记。
- 批量导入支持文本、TXT、CSV，导入前预览、重复检测和失败明细。
- 新作品箱集中展示未处理新作品和数量变化提醒。

### 视频解析与下载

- 支持粘贴 Douyin/TikTok 分享口令、短链或长链接。
- 解析结果默认以简洁卡片展示：标题、作者、作品 ID、类型、来源链接、下载按钮。
- 每条解析结果支持手动下载、复制直链、打开来源和查看解析明细。
- 支持解析成功后自动下载，也支持解析后逐条下载。
- 支持视频和图集下载，图集图片可并发下载。

### 任务与下载管理

- 任务中心展示检测、同步、解析、下载等后台任务。
- 下载队列支持队列状态、暂停、继续、取消、失败重试和实时状态摘要。
- 下载历史记录已下载文件、失败原因和重试入口。
- 批量任务支持失败分类、剩余项摘要和按失败类别重试。

### 存储与媒体预览

- 网盘式文件管理器布局：左侧文件夹导航，右侧网格/列表文件区域。
- 支持进入文件夹、返回上一级、面包屑路径、搜索、排序、媒体类型筛选。
- 已下载图片显示缩略图，已下载视频显示预览卡片。
- 支持沉浸式图片/视频预览、上一项/下一项切换、打开/下载、删除。
- 支持扫描空文件、扫描重复文件、清理临时文件、查看占用统计。

### 设置、Cookie 与诊断

- 设置页集中管理常用配置、Cookie、通知、更新、访问控制和备份恢复。
- Cookie 管理支持本地保存、基础结构检测、启用/禁用、删除、健康状态记录。
- 诊断中心提供环境、依赖、SQLite、磁盘、解析器、下载策略等检查。
- 支持导出诊断包，敏感信息会做脱敏处理。

### Web 远程控制台

- 支持 Linux/Docker 部署，浏览器访问远程控制台。
- 支持 Token 鉴权、子 Token、基础 RBAC、访问审计。
- 支持 SSE 实时事件，用于刷新总览、任务、下载队列等状态。
- 支持 PWA 基础适配，移动端可用浏览器访问。

## 页面结构

Web 端当前按 Windows 桌面端风格收敛为以下主页面：

```text
oùinyin Monitor
├─ 主页
├─ 内容监控
│  ├─ 账号管理
│  ├─ 新作品箱
│  ├─ 批量导入
│  └─ 作品库
├─ 视频解析
├─ 任务中心
│  ├─ 任务记录
│  ├─ 下载队列
│  ├─ 批量任务
│  └─ 运行日志
├─ 下载历史
├─ 问题中心
├─ 设置
│  ├─ 常用设置
│  ├─ Cookie
│  ├─ 通知
│  ├─ 更新
│  ├─ 访问控制
│  └─ 备份恢复
├─ 存储
└─ 诊断
```

## 项目结构

```text
douyin_monitor/
├─ app/
│  ├─ core/                  # 核心业务逻辑：监控、解析、下载、任务、诊断
│  ├─ ui/                    # Windows/Flet 桌面端 UI
│  └─ web/                   # FastAPI Web 控制台、静态前端、Web 运行上下文
├─ crawlers/                 # 内置 Douyin/TikTok 解析器
├─ config/                   # 默认配置与语言配置
├─ deploy/                   # Linux systemd / nginx 部署文件
├─ docs/                     # 文档、部署说明、截图
├─ locales/                  # 界面文案
├─ packaging/windows/        # Windows 打包、安装包、自动更新配置
├─ scripts/                  # 检查、迁移、打包、发布、部署脚本
├─ tests/                    # 单元测试与回归测试
├─ Dockerfile.web            # Web Docker 镜像
├─ docker-compose.web.yml    # Web Docker Compose
├─ requirements.txt          # 桌面端依赖
├─ requirements-web.txt      # Web 运行依赖
├─ requirements-web-docker.txt # Web Docker 精简依赖
└─ main.py                   # 桌面端入口
```

## 环境要求

### Windows 桌面端

- Windows 10/11
- Python 3.10 - 3.12
- 建议使用虚拟环境

### Linux/Docker Web 端

- Linux 或 WSL2
- Docker 与 Docker Compose
- 推荐 2 GB 以上内存
- 远程访问时必须设置强 Token，建议通过 HTTPS/Nginx 反代暴露

## Windows 桌面端快速运行

首次安装依赖：

```bat
install_windows.bat
```

启动桌面应用：

```bat
run_windows.bat
```

启动前检查运行环境：

```bat
run_windows_checked.bat
```

手动运行：

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

## Linux/Docker Web 快速部署

克隆仓库：

```bash
git clone https://github.com/Syuanya/douyin_monitor.git
cd douyin_monitor
```

设置国内镜像源和宿主机用户 ID：

```bash
cat > .env <<EOF
UID=$(id -u)
GID=$(id -g)
DEBIAN_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
EOF
```

生成 Web Token：

```bash
openssl rand -hex 32
```

编辑 `docker-compose.web.yml`，把：

```yaml
DOUYIN_MONITOR_WEB_TOKEN: "change-me"
```

改成你的长随机 Token。

构建并启动：

```bash
docker compose -f docker-compose.web.yml up -d --build
```

查看日志：

```bash
docker logs -f douyin-monitor-web
```

看到下面内容表示启动成功：

```text
Application startup complete.
Uvicorn running on http://0.0.0.0:8080
```

浏览器访问：

```text
http://localhost:8080/
```

如果部署在服务器或 WSL 中，局域网访问需要确认防火墙和端口映射。公网访问建议使用 Nginx + HTTPS，并在 Nginx 中为 SSE 关闭缓冲：

```nginx
proxy_buffering off;
proxy_cache off;
```

更多步骤见：

- `docs/WEB_LINUX_DEPLOYMENT.md`
- `WEB_LINUX_DOCKER_DEPLOYMENT.md`（如果你单独保存了部署文档）

## 常用 Docker 命令

```bash
# 启动
docker compose -f docker-compose.web.yml up -d

# 重新构建
docker compose -f docker-compose.web.yml up -d --build

# 查看日志
docker logs -f douyin-monitor-web

# 停止
docker compose -f docker-compose.web.yml down

# 进入容器
docker exec -it douyin-monitor-web bash
```

## Cookie 与本地数据

应用可以不配置 Cookie 启动，但解析、监控、下载的稳定性会受平台风控影响。推荐只在本地 Web 或桌面设置页填写：

- 抖音 Cookie
- TikTok Cookie
- 多个抖音 Cookie 可按行填写，用于轮换、冷却和容错

不要提交以下运行数据：

```text
.env
.venv/
__pycache__/
.pytest_cache/
.ruff_cache/
build/
dist/
data/
logs/
cache/
downloads/
diagnostics/
config/accounts.json
config/cookies.json
config/cookies.secure.json
config/douyin_content_monitor.json
config/parse_history.json
config/task_records.json
config/user_settings.json
```

这些路径已写入 `.gitignore`。上传 GitHub 前请执行：

```bash
git status
```

确认没有 Cookie、账号数据、下载文件或日志。

## 测试与检查

基础 smoke 检查：

```bash
python scripts/smoke_check.py --strict
```

运行测试：

```bash
python -m pytest -q
```

UI 静态和布局检查：

```bash
python scripts/ui_static_check.py
python scripts/ui_layout_regression_check.py
```

创建发布包：

```bash
python scripts/package_release.py --name douyin_monitor_release.zip
```

执行完整发布闸门：

```bash
python scripts/release_gate.py --package --name douyin_monitor_release.zip
```

## Windows 打包

生成 Windows exe：

```bat
build_exe_windows.bat
```

生成 Windows 发布包：

```bat
build_windows_release.bat --portable-zip --skip-tests
```

如需安装包，需要安装 Inno Setup 并确保 `ISCC.exe` 在 PATH 中：

```bat
build_windows_release.bat --installer --portable-zip --manifest --skip-tests
```

代码签名和自动更新说明见：

- `docs/INSTALLER_AUTO_UPDATE_SIGNING_CICD.md`
- `docs/RELEASE_PROCESS.md`
- `docs/RELEASE_CHECKLIST.md`

## GitHub 上传前检查清单

上传前建议确认：

- 不包含 `.git/`、`.venv/`、`build/`、`dist/`。
- 不包含 `.env`、真实 Cookie、账号列表、监控记录、解析历史、任务记录。
- 不包含 `data/`、`logs/`、`cache/`、`downloads/`、`diagnostics/`。
- 不包含 `__pycache__/`、`.pytest_cache/`、`.ruff_cache/`。
- `crawlers/*/config.yaml` 中的 `Cookie`、`msToken`、`ttwid.cookie` 等字段为空或由运行时生成。
- README 截图中不暴露真实账号、Cookie、私密链接或本地下载路径。

## GitHub 更新示例

如果远程仓库已经存在：

```bash
git clone git@github.com:Syuanya/douyin_monitor.git
cd douyin_monitor
```

复制项目文件到仓库目录后：

```bash
git status
git add .
git commit -m "Release web storage netdisk update"
git push origin main
```

如果当前远程仓库使用 `master` 分支：

```bash
git push origin master
```

首次初始化仓库：

```bash
git init
git branch -M main
git remote add origin git@github.com:Syuanya/douyin_monitor.git
git add .
git commit -m "Initial commit"
git push -u origin main
```

## 已知限制

- Web 媒体预览只预览已下载到本地的文件，不直接播放远程抖音直链。
- 抖音接口可能因 Cookie、登录态、IP、频率和平台策略返回空响应或触发风控。
- Docker Web 在线自更新目前以页面引导为主，生产环境仍建议通过命令行更新并先备份。
- 大规模监控和长时间运行需要在真实环境做 24-72 小时稳定性测试。

## 风险说明

更完整的隐私、Cookie 和平台风险说明见：

- `docs/PRIVACY_AND_RISK.md`
