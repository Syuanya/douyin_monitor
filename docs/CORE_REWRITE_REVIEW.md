# Core Rewrite Review

本项目的主功能应聚焦两条主链路：内容监控和视频解析。当前代码能跑通测试，但原结构存在明显维护风险，不适合作为长期演进基础。

## 主要不合理点

1. `app/core/content_monitor/douyin_content_monitor.py` 职责过重：数据模型、账号仓储、检测调度、主页解析、下载、通知、UI 事件广播都混在同一个 2000+ 行文件里。
2. 视频解析层和爬虫层边界不清：`VideoParserService` 既处理批量解析、缓存、Cookie 池，又直接知道 `DouyinWebCrawler` 的分页实现。
3. 模型定义位置不合理：`DouyinContentItem` / `DouyinMonitorAccount` 被多个模块使用，但定义在 manager 文件里，导致反向依赖和潜在循环导入。
4. Cookie 配置有历史兼容逻辑：运行时 Cookie、YAML Cookie、UI 安全存储并存，容易产生“设置里有 Cookie，实际请求没带 Cookie”的错觉。
5. UI 视图承担了过多业务判断：例如新作品筛选、状态文案、可执行动作判断，应该尽量由服务层输出稳定状态。
6. 平台 API 解析没有明确的错误模型：空响应、风控、登录失效、字段缺失、真实无作品应被区分，而不是都变成普通异常或空列表。

## 本次已完成的核心解耦

1. `douyin_content_monitor.py` 已改为兼容 shim，真实门面迁移到 `app/core/content_monitor/facade.py`。
2. 内容监控核心已拆分为 account、profile sync、profile parser、cookie runtime、download、scheduler、base helper 等 service 模块。
3. `DouyinContentItem` / `DouyinMonitorAccount` 已迁移到 `models.py`，旧路径继续兼容。
4. `VideoParserService` 已拆分为 parser runtime、cookie pool、URL extractor、Douyin user posts client、parser models。
5. UI 入口继续走稳定门面，避免 Flet 布局层伴随核心重构发生大面积回归。
6. 已同步更新静态检查与测试，避免测试仍绑定旧的大文件结构。
7. 详细结构见 `docs/CORE_DECOUPLING_ARCHITECTURE.md`。

## 后续建议的正式重写边界

### 内容监控模块

建议拆成以下层次：

- `models.py`：账号、作品、检测结果、错误分类。
- `account_repository.py`：SQLite/JSON 存储，禁止混入业务判断。
- `profile_client.py`：只负责 HTTP 请求、Cookie、代理、重试、响应分类。
- `profile_parser.py`：只负责从网页/API JSON 提取作品和账号信息。
- `monitor_service.py`：只负责基线、新作品检测、状态流转。
- `download_policy.py`：只负责自动下载策略。
- `scheduler_service.py`：只负责周期调度。
- `facade.py`：给 UI 调用的薄门面，维持兼容 API。

### 视频解析模块

建议拆成以下层次：

- `parser_models.py`：解析结果、失败结果、媒体资源。
- `url_extractor.py`：文本中的 URL 提取、去重、规范化。
- `cookie_pool.py`：Cookie 池、轮换、冷却、失败计数。
- `douyin_parser_adapter.py`：封装 Douyin Web 爬虫。
- `tiktok_parser_adapter.py`：封装 TikTok 爬虫。
- `video_parser_service.py`：只负责编排批量任务、缓存、并发控制。

## 重写原则

1. UI 不直接判断业务规则，只消费服务层 DTO。
2. 解析失败必须有分类：`cookie_invalid`、`risk_control`、`empty_response`、`schema_changed`、`not_found`、`network_error`。
3. 所有状态流转集中在服务层，不允许散落在 UI 回调里。
4. 所有外部请求统一通过 client 层，禁止业务层直接 `httpx.get()`。
5. 兼容旧配置，但新代码只认一个运行时 Cookie 来源。
6. 每次结构重构必须保留旧 public API，避免 UI 大面积联动崩溃。
