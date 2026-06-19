# 隐私、Cookie 与平台风险说明

本项目是本地运行工具。用户需要自行确认使用场景符合平台规则、法律法规和内容授权边界。

## 使用边界

- 仅处理用户主动提供的公开链接、公开主页或用户有权访问的内容。
- 不承诺绕过登录、验证码、风控、私密内容、付费内容或任何访问限制。
- 当平台返回验证码、限流、403、登录失效等状态时，程序应停止自动重试或降低频率。
- 下载内容前，用户应确认自己拥有查看、保存或使用该内容的权利。

## 本地数据

可能保存在本地的运行数据包括：

- Cookie 配置或安全 Cookie 文件。
- 用户设置。
- 账号监控记录。
- 解析历史。
- 任务中心记录。
- SQLite 运行数据库。
- 日志和诊断报告。

发布包会排除运行态敏感文件；但用户本机运行后会重新生成这些文件。

## 清理本地数据

预览将被清理的文件：

```bash
python scripts/clear_local_data.py
```

确认清理配置、Cookie、运行诊断等本地数据：

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
