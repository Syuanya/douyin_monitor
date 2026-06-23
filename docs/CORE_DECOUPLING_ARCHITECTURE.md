# Core Decoupling Architecture

本版本完成了内容监控与视频解析核心链路的拆分解耦，同时保留旧 public API 兼容层，避免 UI 和外部调用一次性大面积改造。

## 设计目标

1. 内容监控、视频解析、Cookie 运行时、下载编排、周期调度分层维护。
2. UI 继续调用稳定门面，业务状态和核心规则下沉到 core/service 层。
3. 旧导入路径继续可用，避免第三方脚本或历史测试直接失效。
4. 不重写 Flet UI 布局，降低界面回归风险。

## 内容监控模块

### 兼容入口

- `app/core/content_monitor/douyin_content_monitor.py`
  - 仅作为旧路径 import shim。
  - 新代码不应在这里添加业务逻辑。

### 新门面

- `app/core/content_monitor/facade.py`
  - `DouyinContentMonitorManager` 的兼容门面。
  - 负责注入 services、repository、merge service、scheduler。
  - 不再承载具体业务实现。

### 领域模型

- `app/core/content_monitor/models.py`
  - `DouyinContentItem`
  - `DouyinMonitorAccount`

### 服务拆分

- `services/account_service.py`
  - 账号增删改查
  - 批量恢复
  - 配置持久化
  - 账号命名补全

- `services/profile_sync_service.py`
  - 账号检测
  - 作品同步
  - 新作品合并
  - 公开主页与 parser fallback 编排

- `services/profile_parser.py`
  - 公开主页 HTML / JSON 解析
  - 作品字段归一化
  - 账号昵称、头像、作品数提取

- `services/cookie_runtime.py`
  - Cookie 池读取
  - Cookie 轮换
  - 风控冷却
  - 响应健康记录

- `services/download_service.py`
  - 内容监控项下载
  - 本地文件路径匹配
  - 预览 URL 解析
  - 图集下载

- `services/base_service.py`
  - 通用时间、排序、配置读取、请求 Header
  - 监控历史记录
  - 账号状态辅助方法

- `services/scheduler_facade.py`
  - 周期任务启动、停止和状态查询

- `services/account_repository.py`
  - 存储适配：SQLite / JSON mirror

- `services/content_merge_service.py`
  - 内容合并、基线建立、保留策略、自动暂停策略

- `services/scheduler_service.py`
  - 纯周期调度器

## 视频解析模块

### 兼容门面

- `app/core/media/video_parser_service.py`
  - 保留 `VideoParserService` public API。
  - 只负责初始化状态和组合 mixin。

### 领域模型

- `app/core/media/parser_models.py`
  - `ParsedVideoResult`
  - `ParseFailure`
  - `VideoParseBatchResult`
  - `normalize_work_url`

### 服务拆分

- `parser_runtime.py`
  - 单 URL 解析
  - 批量解析
  - 并发控制
  - inflight 去重
  - 解析缓存

- `parser_cookie_pool.py`
  - Douyin / TikTok Cookie 池配置
  - 运行时 Cookie 注入
  - 已加载 crawler 配置刷新

- `url_extractor.py`
  - 文本 URL 提取、去重和尾部标点清理

- `douyin_user_posts_client.py`
  - 抖音主页作品分页拉取
  - `DouyinWebCrawler` 适配

- `parser_common.py`
  - 解析服务共享类型和依赖

## 兼容规则

- 旧路径仍可用：
  - `from app.core.content_monitor.douyin_content_monitor import DouyinContentMonitorManager`
  - `from app.core.media.video_parser_service import VideoParserService`
- 新代码应优先使用：
  - `from app.core.content_monitor.facade import DouyinContentMonitorManager`
  - `from app.core.content_monitor.models import DouyinContentItem, DouyinMonitorAccount`
  - `from app.core.media.parser_models import ParsedVideoResult`

## 后续开发约束

1. 不允许把新业务逻辑继续写回 `douyin_content_monitor.py` 兼容 shim。
2. 不允许让 UI 直接读写 Cookie 池内部游标或风控冷却状态。
3. 不允许让视频解析服务直接处理 UI 任务记录。
4. 新增平台解析器时，应新增 adapter/client，而不是修改 `VideoParserService` 主类。
5. 新增监控状态时，应在 content-monitor service 层统一流转，再由 UI 展示。
