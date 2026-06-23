# 全项目拆分解耦说明

本版本将项目从“核心业务解耦”推进到“应用层与 UI 外围功能解耦”。目标是让 Flet 页面只承担控件构建、事件绑定和反馈展示，业务状态聚合、数据查询、导出、恢复、健康检查、文件浏览等逻辑进入无 UI 依赖的服务层。

## 新增层次

```text
app/core/application/
├── service_container.py        # 应用服务容器，脱离 Flet shell

app/core/ui_services/
├── common.py                   # 通用路径、容量、权限工具
├── home_dashboard_service.py   # 主页状态聚合
├── issue_center_service.py     # 问题中心问题收集
├── task_center_service.py      # 任务中心状态、队列摘要、重试流程
├── download_history_service.py # 下载历史查询、恢复、清理、导出
├── storage_browser_service.py  # 存储页文件扫描、过滤、排序
├── settings_workflow.py        # 设置页校验、策略、Cookie 测试、备份导出
├── diagnostic_workflow.py      # 健康检查流程
└── video_parse_workflow.py     # 视频解析页 URL 提取与历史记录
```

## 旧页面保留的职责

`app/ui/views/*_view.py` 仍保留页面类与控件布局，避免 Flet 兼容性回归。页面中的非 UI 逻辑改为调用 `app/core/ui_services/`。

## 兼容约束

- `DouyinMonitorServices` 迁移到 `app/core/application/service_container.py`，`standalone` 入口继续使用同名类。
- 内容监控与视频解析的核心解耦结构保持不变。
- 任务中心仍禁止使用已知会触发灰块的 `TextField` 和复杂展开占位。
- 下载历史继续保持简单布局，避免灰块回归。

## 后续开发规则

1. 页面只写 Flet 控件、事件转发和 snackbar/dialog 反馈。
2. 业务计算、状态筛选、文件扫描、CSV 导出、健康检查、Cookie 校验等必须写在 `core/ui_services` 或对应 core service。
3. 新增主业务功能优先落在 `core/content_monitor`、`core/media`、`core/runtime`。
4. 不再把应用服务初始化逻辑写回 `standalone/douyin_monitor_app.py`。
