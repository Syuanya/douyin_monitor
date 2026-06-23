# Linux Web 远程部署说明

本项目现在同时支持桌面端和 Linux Web 端。Web 端是可选能力，不影响原 Flet 桌面应用。

## 功能范围

Web 端提供：

- 内容监控账号列表、添加、删除、启动/停止监控
- 批量导入账号预览、重复检测、TXT/CSV 文件上传导入
- 检测更新、同步作品、查看作品列表、下载作品
- 视频链接批量解析、边解析边下载
- 任务中心、后台 Job 状态
- Cookie 健康度、限速器、批任务、分片下载状态观测
- 基础设置读取和配置 patch

## 直接运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-web.txt
export DOUYIN_MONITOR_RUN_PATH=/opt/douyin-monitor/data
export DOUYIN_MONITOR_WEB_TOKEN='change-this-token'
python scripts/run_web_server.py --host 0.0.0.0 --port 8080 --run-path "$DOUYIN_MONITOR_RUN_PATH"
```

访问：

```text
http://服务器IP:8080/
```

如果设置了 `DOUYIN_MONITOR_WEB_TOKEN`，网页右上角输入同一个 Token 后保存。

## Systemd 部署

```bash
sudo bash deploy/linux/install_web.sh
sudo systemctl status douyin-monitor-web
```

默认监听 `127.0.0.1:8080`，建议通过 Nginx HTTPS 反向代理暴露到公网。

查看日志：

```bash
sudo journalctl -u douyin-monitor-web -f
```

## Nginx 反向代理

参考：

```text
deploy/linux/nginx.conf
```

建议使用 HTTPS，不建议把 8080 端口直接暴露到公网。

## Docker 部署

```bash
docker compose -f docker-compose.web.yml up -d --build
```

修改 `docker-compose.web.yml` 中的：

```yaml
DOUYIN_MONITOR_WEB_TOKEN: "change-me"
```

## API 鉴权

若设置了：

```bash
DOUYIN_MONITOR_WEB_TOKEN=your-token
```

API 请求需要带：

```http
Authorization: Bearer your-token
```

也支持：

```http
X-Auth-Token: your-token
```

## 主要 API

```text
GET  /health
GET  /api/status
GET  /api/accounts
POST /api/accounts
POST /api/import/preview
POST /api/import/commit
POST /api/import/file/preview
POST /api/import/file/commit
POST /api/monitor/check-all
POST /api/monitor/sync-all
POST /api/accounts/{account_id}/check
POST /api/accounts/{account_id}/sync
GET  /api/accounts/{account_id}/items
POST /api/parse
POST /api/parse/stream
GET  /api/tasks
GET  /api/jobs
```

## 安全建议

1. 设置长随机 Token。
2. 用 Nginx HTTPS 反代。
3. 不要直接公开 8080 到公网。
4. 下载目录、配置目录只给服务用户读写。
5. Cookie 属于敏感信息，不要在日志和截图中公开。

## 风控提醒

Web 端只是远程控制界面，不会消除抖音侧 IP / Cookie 风控。批量检测和同步仍建议低并发、分批、遇到空响应自动冷却。
