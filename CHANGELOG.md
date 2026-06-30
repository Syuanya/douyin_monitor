## 内容监控模块 P3 完成阶段桌面效率面板升级

- 新增 `app/ui/views/douyin_content_insights_controller.py`，将 P3 核心洞察能力接入桌面端，避免健康评分、分组统计、素材筛选等逻辑继续堆入主页面。
- 内容监控工具栏新增“健康面板”“素材收集箱”“分组统计”“新增摘要”入口，用户无需打开 Web API 即可在桌面端查看 P3 效率数据。
- 健康面板展示账号总数、平均健康分、高风险/需关注/未监控数量，并按优先级列出低分账号、风险原因和下一步建议，支持直接查看作品或重新检测。
- 素材收集箱支持按关键词、状态、视频/图集、分组筛选，展示作品链接、保存路径、失败建议，并支持打开作品、复制链接、打开下载位置和按当前筛选导出素材链接 CSV。
- 分组统计报告按分组展示账号数、启用数、异常数、作品数、待处理数、已下载数、失败数、视频/图集数量和平均健康分，便于定位问题最多的分组。
- 新增摘要支持查看近 1 天、3 天、7 天新增作品，高亮新增最多账号、视频/图集数量、已下载和失败数量，适合每日素材处理。
- `douyin_content_view.py` 仅新增 controller 初始化和薄 wrapper，P3 桌面能力通过独立 controller 承载，保持 P1 拆分后的页面边界稳定。
- 新增 `tests/test_douyin_content_insights_controller.py`，覆盖健康摘要、分组统计、素材筛选、摘要、导出参数、标签文案和文本压缩。
- 验证：`python -m compileall -q app tests`，`PYTHONPATH=. pytest -q`，208 passed；`ui_static_check`、`ui_layout_regression_check`、`smoke_check`、`release_gate --skip-tests`、`verify_windows_package` 均通过。

## 内容监控模块 P3 第一阶段用户效率升级

- 新增 `app/core/content_monitor/insights.py`，提供账号健康评分、分组统计、素材收集箱、时间窗口摘要和素材链接 CSV 导出等用户效率能力。
- 账号健康评分会综合监控开关、最近成功检测时间、错误次数、Cookie/风控/网络错误、下载失败数和待处理新作品数，输出 `score`、`level`、原因和下一步建议，方便优先处理异常账号。
- 内容监控运行态摘要 `content_monitor_runtime_summary()` 增加 `health`、`groups`、`digest_24h`，Web 状态页和诊断入口可直接读取账号健康、分组统计和 24 小时新增摘要。
- 新增核心接口：`content_monitor_health_summary()`、`account_health_detail()`、`content_monitor_group_statistics()`、`content_monitor_material_collection()`、`content_monitor_time_window_digest()`、`export_content_monitor_material_links()`。
- 素材收集箱支持按状态、图集/视频、分组和关键词筛选，默认聚合待处理新作品和下载失败作品，适合二创素材收集、批量处理和链接导出。
- Web API 新增 `/api/content-monitor/health`、`/api/content-monitor/groups`、`/api/content-monitor/materials`、`/api/content-monitor/digest`、`/api/content-monitor/materials/export`，Web 管理端可直接接入 P3 效率面板。
- 素材链接导出使用 UTF-8-SIG CSV，字段包含账号、分组、作品 ID、标题、类型、状态、发布时间、首次发现、作品链接、下载位置、失败分类和处理建议。
- 新增 `tests/test_content_monitor_p3_insights.py`，覆盖健康评分、分组统计、素材筛选、时间窗口摘要、核心 manager 接口和 CSV 导出。
- 验证：`python -m compileall -q app tests`，`PYTHONPATH=. pytest -q`，204 passed；`ui_static_check`、`ui_layout_regression_check`、`smoke_check`、`release_gate` 均通过。

## 内容监控模块 P2 完成阶段刷新一致性与任务闭环升级

- 新增 `app/ui/views/douyin_content_refresh_coordinator.py`，统一管理内容监控页面 pubsub 刷新、批量任务中延迟刷新、高频事件节流和长任务结束后的最终强制刷新，降低灰块、空白、滚动状态丢失和局部状态不同步风险。
- 内容监控页 `subscribe_update()` 改为委托刷新协调器；批量检测/同步、批量下载、批量开始/停止、批量删除、全量开始/停止等长任务结束后统一触发最终刷新，保证账号卡、新作品箱、作品列表和任务中心状态收敛一致。
- 批量下载任务中心记录新增 `cancel_action="batch_job"` 与 `cancel_payload={"job_id": ...}`，任务中心可安全取消由 BatchJobStore 托管的内容下载批次，不再只能标记历史记录。
- 自动下载和批量下载任务的 `retry_payload` 增加 `all_item_ids`、`retryable_only`，进度回写保留 `failed_item_ids`，失败重试默认只重试可恢复项，避免反复请求失效作品。
- `TaskCenterFacadeService.cancel_record()` 支持取消 `batch_job`，并在任务取消/内容下载重试后广播 `douyin_monitor_update`，让内容监控页面和 Web 状态页及时刷新。
- Web `/api/tasks/{task_id}/cancel` 改为真正调用任务中心取消动作；Web 任务卡对带 `cancel_action` 的运行中任务显示可点击“取消任务”，没有安全取消入口的运行中任务仍保持禁用，避免 UI 状态和真实执行状态不一致。
- 新增 `tests/test_douyin_content_refresh_coordinator.py` 和 `tests/test_content_monitor_p2_complete.py`，覆盖刷新延迟/节流/最终刷新、批量任务中心取消、批量下载 cancel payload、内容重试后的刷新广播。
- 验证：`python -m compileall -q app tests`，`PYTHONPATH=. pytest -q`，199 passed；`ui_static_check`、`ui_layout_regression_check`、`smoke_check`、`release_gate` 均通过。

## 内容监控模块 P2 第二阶段任务中心控制升级

- 自动下载任务完整接入任务中心取消链路：`TaskRecord` 新增 `cancel_action` / `cancel_payload`，任务中心可针对正在运行的内容监控自动下载显示“取消”入口。
- 自动下载任务增加运行态元数据 `_auto_download_task_meta`，记录账号、作品 ID、任务中心 ID、成功数、失败数、失败作品 ID 和更新时间；运行态摘要会返回可诊断的任务明细。
- `cancel_auto_downloads()` 支持按账号、作品 ID、任务 key 精准取消，避免取消一个账号时误伤其他账号或其他批次。
- 任务中心新增 `cancel_record()`，目前支持 `content_auto_download` 取消动作；桌面任务卡对 active 且可取消的任务显示“取消”按钮。
- 下载失败重试闭环升级：任务中心和内容监控失败重试默认跳过 `failure_retryable=False` 的作品，避免对 404、作品失效等不可恢复错误反复请求。
- 下载状态摘要增加 `failure_categories`、`non_retryable_failed`，用户和诊断面板可以直接看到失败归类分布和不可重试数量。
- `TaskCenter` 的取消动作和 payload 支持 SQLite / JSON mirror 持久化，应用重启后仍可正确展示历史任务的取消元信息。
- 新增 `tests/test_content_monitor_p2_stage2.py`，扩展 `tests/test_task_center_sqlite.py`，覆盖自动下载取消、不可重试失败跳过、失败分类统计和任务中心取消字段持久化。
- 验证：`python -m compileall -q app tests`，`PYTHONPATH=. pytest -q`，193 passed；`ui_static_check`、`ui_layout_regression_check`、`smoke_check`、`release_gate` 均通过。

## 内容监控模块 P2 第一阶段稳定性升级

- 下载失败状态升级：`DouyinContentItem` 新增失败分类、处理建议和可重试标记；下载失败后自动基于错误内容生成用户可理解的下一步操作。
- 桌面作品卡、新作品箱卡片、作品详情弹窗和 Web 新作品箱同步展示失败建议，避免用户只看到“下载失败”而不知道该怎么处理。
- 新增内容监控运行态摘要 `content_monitor_runtime_summary()`，统一输出账号总数、启用账号、异常账号、待处理新作品、下载失败数、调度器状态、自动下载任务、持久化状态、媒体队列和批量任务数量。
- 自动下载任务增加可取消和清理接口 `cancel_auto_downloads()` / `cleanup_auto_download_tasks()`，避免后台自动下载任务完成后长期残留，也为后续任务中心控制打基础。
- 持久化防抖逻辑增强：`flush_persist()` 会安全取消挂起的延迟保存任务，避免关闭或停止监控时出现未等待的取消任务。
- 周期监控状态接口修正：`is_periodic_task_running()` 返回真实调度任务状态；停止周期监控后强制 flush 持久化，降低关闭时状态丢失风险。
- SQLite 内容监控保存升级：删除 stale 账号/作品改为分块查询删除，避免账号或作品数量超过 SQLite 变量上限时报错；upsert 增加 no-op 保护，未变化数据不会重复刷新 `updated_at`。
- Web `/api/status` 增加 `content_monitor` 运行态摘要，便于 Web 管理页和诊断面板读取模块健康状态。
- 新增 `tests/test_content_monitor_p2_runtime.py`，并扩展 `tests/test_sqlite_store.py`，覆盖失败分类、运行态摘要、自动下载取消、持久化 flush 和 1200 个作品保存场景。
- 验证：`python -m compileall -q app tests`，`PYTHONPATH=. pytest -q`，188 passed；`ui_static_check`、`ui_layout_regression_check`、`smoke_check`、`release_gate` 均通过。

## 内容监控模块 P1 代码拆分完成

- 新增 `app/ui/views/douyin_content_batch_import_controller.py`，将批量导入账号的解析、文件选择、预览报告、导入执行、后台昵称补全从 `douyin_content_view.py` 中完整抽离。
- 新增 `app/ui/views/douyin_content_global_actions_controller.py`，将全量快速检测、全量同步作品、全部开始监控、全部停止监控从主页面中抽离，统一复用账号批量任务控制器。
- `douyin_content_view.py` 从 1816 行降到 1563 行，P1 阶段页面拆分目标完成；主页面仅保留页面组装、刷新、事件代理和少量兼容 wrapper。
- 批量导入继续复用核心 `batch_import_service`，保持重复校验、无效行提示、默认分组、自动下载策略、通知开关和大批量启动提醒不变。
- 未填备注账号继续在后台补全昵称，避免导入时逐个阻塞；昵称补全逻辑迁移到 controller 后增加独立回归测试。
- 全量检测只处理启用监控账号；全量同步保留二次确认，避免账号多时误触发高成本请求。
- 新增 `tests/test_douyin_content_batch_import_controller.py`、`tests/test_douyin_content_global_actions_controller.py`，并更新昵称补全与 UI 组件化契约测试，覆盖批量导入、全量检测/同步和全部开始/停止入口。
- 验证：`python -m compileall -q app tests`，`PYTHONPATH=. pytest -q`，183 passed；`ui_static_check`、`ui_layout_regression_check`、`smoke_check`、`release_gate` 均通过。

## 内容监控模块 P1 第八轮专业升级优化

- 新增 `app/ui/views/douyin_content_add_account_controller.py`，将添加账号弹窗、快捷输入添加和自动昵称补全逻辑从主页面中抽离，避免新增账号流程继续污染页面渲染类。
- 新增 `app/ui/views/douyin_content_account_controller.py`，统一托管账号卡片创建、编辑账号弹窗、监控历史弹窗、开始/停止监控、删除和恢复账号等账号级交互。
- 新增 `app/ui/views/douyin_content_download_complete_controller.py`，将下载完成弹窗、复制路径和打开下载目录动作从主页面中抽离，减少下载交互与页面刷新逻辑耦合。
- `douyin_content_view.py` 从 2085 行降到 1816 行，本轮继续削减 269 行页面职责；主页面进一步收敛为页面组装、刷新和事件代理。
- 控制器导入兼容无 Flet 的单元测试环境，纯规则逻辑可在 CI/无桌面依赖环境中直接测试。
- 更新 `tests/test_ui_componentization.py` 的架构契约，使其识别账号 controller、添加账号 controller 和下载完成 controller 的新拆分边界。
- 新增 `tests/test_douyin_content_add_account_controller.py`、`tests/test_douyin_content_account_controller.py`、`tests/test_douyin_content_download_complete_controller.py`，覆盖手动命名跳过昵称补全、自动昵称补全、开始/停止监控、删除恢复快照和下载完成文件数提示。
- 验证：`python -m compileall -q app tests`，`PYTHONPATH=. pytest -q`，174 passed；`ui_static_check`、`ui_layout_regression_check`、`smoke_check`、`release_gate` 均通过。

## 内容监控模块 P1 第七轮专业优化

- 新增 `app/ui/views/douyin_content_inbox_controller.py`，将新作品收件箱标题区、摘要统计、独立分页、批量下载、单项下载、预览和标记已处理逻辑从 `douyin_content_view.py` 中抽离。
- 新增 `app/ui/views/douyin_content_error_repair_controller.py`，将异常账号筛选、异常分类、修复面板、重新检测、同步异常账号和复制异常摘要统一托管。
- 新增 `app/ui/views/douyin_content_preview_controller.py`，将视频预览、图集预览、下载位置打开和作品详情弹窗从主页面中抽离，继续保留 legacy `VideoPlayer` 弹窗预览路径。
- `douyin_content_view.py` 从 2498 行降到 2085 行，本轮继续削减 413 行页面职责，页面类进一步收敛为渲染入口、事件代理和控制器调度。
- 新作品箱 fallback 标记逻辑补强：`download_failed` 项标记已处理时会恢复为 `active`，避免失败作品长期卡在新作品入口。
- 更新静态 UI 契约测试，使视频预览和直链复制检查识别拆分后的 preview controller，避免架构拆分被误判为功能缺失。
- 新增 `tests/test_douyin_content_inbox_controller.py`、`tests/test_douyin_content_error_repair_controller.py`、`tests/test_douyin_content_preview_controller.py`，覆盖失败下载保留/标记、异常分类摘要和详情弹窗文件大小格式化。
- 验证：`python -m compileall -q app tests`，`PYTHONPATH=. pytest -q`，169 passed；`ui_static_check`、`ui_layout_regression_check`、`smoke_check`、`release_gate` 均通过。

## 内容监控模块 P1 第六轮专业优化

- 新增 `app/ui/views/douyin_content_batch_settings_controller.py`，将批量设置弹窗、勾选式局部更新、批量/单账号保存 fallback 从 `douyin_content_view.py` 中抽离，避免页面类继续持有表单状态和保存规则。
- 新增 `app/ui/views/douyin_content_export_controller.py`，统一承接作品 CSV、账号 CSV、导出目录、诊断包和日志目录入口，后续导出字段扩展不再污染主页面。
- 新增 `app/ui/views/douyin_content_toolbar.py`，将内容监控首页标题区、主操作按钮、筛选入口和批量进度挂载逻辑抽成独立工具栏构建器。
- `douyin_content_view.py` 从 2904 行继续降到 2498 行，累计进一步削减 406 行页面职责，降低灰块、空白、刷新冲突和滚动状态丢失问题的复发风险。
- 导出控制器保留原有 UTF-8-SIG CSV 输出、账号级导出字段、作品图集/视频类型判断和诊断包反馈，保证用户原有导出入口不变。
- 批量设置控制器保留“只修改已勾选项目”的交互保护，避免批量误改分组、通知或自动下载策略。
- 新增 `tests/test_douyin_content_batch_settings_controller.py` 和 `tests/test_douyin_content_export_controller.py`，覆盖批量设置 payload、批量保存 fallback、导出行生成、count-only 过滤和 CSV 编码。
- 更新静态 UI 契约测试以识别拆分后的 toolbar、batch settings 和 export controller，避免架构拆分被误判为功能缺失。
- 验证：`python -m compileall -q app tests`，`PYTHONPATH=. pytest -q`，163 passed；`ui_static_check`、`ui_layout_regression_check`、`smoke_check`、`release_gate` 均通过。

## 内容监控模块 P1 第五轮专业优化

- 新增 `app/ui/views/douyin_content_account_batch_controller.py`，将账号批量检测、同步、开始/停止、删除、取消、任务中心进度和最近批量结果 fallback 从 `douyin_content_view.py` 中抽离。
- 新增 `app/ui/views/douyin_content_work_controller.py`，集中处理作品筛选、作品可见窗口、作品批量选择、加载更多和选择模式切换，减少作品列表状态散落在页面类中。
- `douyin_content_view.py` 从 3230 行继续降到 2900 行，累计削减 330 行页面职责，页面类进一步回归渲染和事件绑定。
- 账号批量任务控制器继续统一读取 `monitor_batch_concurrency` / `douyin_content_monitor_batch_concurrency`，并限制到 1-8，保证批量检测与同步并发规则集中可测。
- 最近批量结果查询迁移到账号批量控制器，继续保留任务中心 `snapshot(limit=30)` fallback，用户在刷新页面后仍可查看最近批量任务结果。
- 作品列表控制器复用 `douyin_content_state.filter_work_items()`，保证作品页、新作品箱、下载筛选沿用同一状态语义。
- 新增 `tests/test_douyin_content_account_batch_controller.py` 和 `tests/test_douyin_content_work_controller.py`，覆盖并发配置、选中账号解析、任务中心结果 fallback、批量任务进度回写、删除恢复快照、作品筛选、可见窗口批量选择和加载更多。
- 验证：`python -m compileall -q app tests`，`PYTHONPATH=. pytest -q`，158 passed；`ui_static_check`、`ui_layout_regression_check`、`smoke_check`、`release_gate` 均通过。

## 内容监控模块 P1 第四轮专业优化

- 新增 `app/ui/views/douyin_content_download_controller.py`，将内容监控批量下载队列、并发限制、任务中心进度回写、失败项重试 payload、下载位置解析等逻辑从 `douyin_content_view.py` 中抽离。
- `douyin_content_view.py` 从 3356 行降到 3230 行，页面类继续回归“渲染 + 事件绑定”，降低后续灰块、空白页、滚动状态丢失和批量下载刷新冲突的维护风险。
- 批量下载控制器统一读取 `batch_download_concurrency` 并限制到 1-12，继续兼容旧 `max_parallel_downloads`，但不再把该逻辑散落在页面类中。
- 批量下载任务增加空列表保护，避免空任务进入任务中心后出现 0/0 状态误导。
- 下载筛选、下载筛选文案、下载位置解析均通过控制器统一出口，后续 Web/桌面端可继续复用同一语义。
- 新增 `tests/test_douyin_content_download_controller.py`，覆盖并发配置钳制、下载筛选、文件路径解析、批量下载去重、任务中心失败重试参数、用户提前停止下载等关键场景。
- 验证：`python -m compileall -q app tests`，`PYTHONPATH=. pytest -q`，150 passed；`ui_static_check`、`ui_layout_regression_check`、`smoke_check`、`release_gate` 均通过。

## 内容监控模块 P1 第三轮专业优化

- 新增核心状态规则模块 `app/core/content_monitor/status_rules.py`，统一定义新作品、数量变化、下载失败、已下载、图文作品等状态判断，避免 Core、桌面 UI、Web 端各自硬编码。
- 新增桌面状态辅助模块 `app/ui/views/douyin_content_state.py`，集中处理账号筛选、作品筛选、下载筛选、新作品箱条目、分页窗口和异常归类，降低 `douyin_content_view.py` 巨型页面中的重复业务判断。
- 作品浏览页新增状态摘要：当前筛选已显示 x/y、全部作品、新作品、已下载、失败、图集/视频数量，用户可直接判断同步是否完整、失败是否需要处理。
- 作品浏览页“重试失败下载”按钮按失败数量动态禁用；存在失败项时摘要区域提供“重试失败”快捷入口，减少无效点击。
- Web 新作品箱与桌面端语义对齐：`download_failed` 继续保留在新作品箱，显示“下载失败”红色标记、失败原因、保存位置和“重试下载”按钮。
- Web 账号 `new_unhandled_count` 统计改为复用统一状态规则，下载失败的新作品不会被 Web 端漏计。
- 新增 `tests/test_douyin_content_state.py`，覆盖新作品状态、作品/下载筛选、账号筛选、状态统计、异常归类和 Web 字典序列化兼容。
- 更新 Web 静态契约测试和内容监控 UI 回归测试，防止后续再次遗漏下载失败项。
- 验证：`python -m compileall -q app tests`，`PYTHONPATH=. pytest -q`，145 passed。

## 内容监控模块 P1 第二轮专业优化

- 新作品箱语义优化：下载失败的新作品不再从新作品箱消失，会继续保留为待处理项，用户可重试或手动标记已处理。
- “已处理”逻辑补齐：`download_failed` 作品标记已处理后会恢复为 `active` 并刷新账号新作品计数，避免失败项长期卡在新作品入口。
- 账号卡片新增“下一次检测”和“连续失败”信息，辅助判断监控是否真正运行、是否到期等待调度。
- 账号状态与处理建议细化：自动暂停、Cookie/登录态、风控限流、主页不可访问、网络代理等错误会展示更明确的下一步动作。
- 作品卡片和新作品箱补充失败重试与打开下载位置入口；下载失败项按钮文案从普通“下载”强化为“重试下载”。
- 桌面 UI 批量下载并发读取 `batch_download_concurrency`，上限统一为 12，避免 UI 仍按旧 `max_parallel_downloads` / 8 上限执行。
- 核心层新增 `download_status_summary()` 和 `retry_failed_downloads()`，为后续任务中心、Web API 和批量失败重试提供统一入口。
- SQLite 内容监控保存从全量删除重写改为增量 upsert，仅删除过期账号/作品，降低账号和作品数量变多后的写入卡顿与 WAL 压力。
- 新增回归测试覆盖 SQLite 增量保存、下载失败保留待处理、标记已处理、下一次检测时间、下载状态摘要。
- 验证：`python -m compileall -q app tests`，`PYTHONPATH=. pytest -q`，139 passed；`ui_static_check`、`ui_layout_regression_check`、`smoke_check`、`release_gate` 均通过。

## 内容监控模块 P0 第一轮专业优化

- 批量导入预览去掉 UI 层重复解析函数，统一复用 `batch_import_service.parse_batch_import_text()`，避免导入预览和真实导入规则不一致。
- 内容监控作品列表与新作品箱默认显示数量从 12 提升到 20，并继续保留“加载更多”机制，降低账号作品较多时误以为数据缺失的问题。
- 统一内容监控并发上限：账号检测并发收敛为 1-8，批量下载并发收敛为 1-12，避免设置页允许值与核心执行上限不一致。
- `DouyinContentItem` 增加下载追踪字段：下载路径、完成时间、最后尝试时间、失败原因、重试次数、文件大小、处理时间等，便于用户排错和后续任务中心关联。
- 下载流程在成功、文件已存在、下载失败、图集失败等路径统一写入作品级下载状态；作品卡片和作品详情会展示失败原因、保存路径、重试次数等用户可理解的信息。
- 自动下载任务增加运行中任务注册和去重，异常不会静默丢失，并向任务中心持续回写成功/失败数量和失败作品重试参数。
- 下载位置查找优先使用作品保存的 `download_path`，兼容旧路径搜索逻辑。
- 验证：`python -m compileall -q app tests`，`PYTHONPATH=. pytest -q`，138 passed。

## 任务中心与下载历史 P3 深度架构优化

- 新增 `app/core/runtime/operation_models.py`，统一任务状态、下载状态、文件状态、可恢复判断和中英文显示映射。
- 任务中心快照新增 `status_key`、`status_label`、`is_active`，UI 与服务层可同时兼容中文旧状态和英文规范状态。
- 下载历史记录统一通过 `enriched_record()` 输出，补充状态中文名、文件状态 key/label、是否可恢复、是否完成文件缺失、失败归类和处理建议。
- SQLite 下载记录写入时统一规范化 `status`，并新增 `idx_download_records_task_id` 索引，提升任务详情查询关联下载记录的性能。
- 旧版 `download_recovery.py` 保留为兼容层，状态常量改为复用统一状态模型，正式恢复执行继续由 `download_recovery_service.py` 承担。
- 任务中心 UI 的筛选、重试、颜色和清理保护改为基于统一状态 key 判断，避免后续 Web/API 英文状态进入后判断失效。
- 新增 `tests/test_operation_models_p3.py`，覆盖任务状态兼容、下载状态规范化、文件状态与可恢复判断。
- 验证：`python -m compileall -q app tests`，`PYTHONPATH=. pytest -q`，138 passed；`ui_static_check`、`ui_layout_regression_check`、`release_gate` 均通过。

## 任务中心与下载历史 P1 专业优化

- 任务中心新增关键词搜索，支持按标题、类型、说明、任务ID、重试参数和作品ID检索任务。
- 任务中心列表改为渐进加载，默认显示 50 条并支持“加载更多”，避免记录多时整页渲染卡顿。
- 批量任务面板不再固定只显示 3 个，改为展示活跃任务优先、最多 12 个，并显示活跃任务数量。
- 下载历史新增关键词搜索，支持按标题、路径、URL、失败原因和关联任务ID检索。
- 下载历史新增“文件缺失”筛选，能够发现数据库显示完成但本地文件已不存在的记录。
- 下载历史列表改为渐进加载，默认显示 50 条，支持加载更多，避免历史记录多时卡顿。
- 下载历史增加复制路径、复制 URL、失败归类和建议处理展示。
- CSV 导出拆分为“导出当前筛选”和“导出全部”，并补充文件状态、失败分类字段。
- 清理完成/失败记录增加二次确认，明确只清理历史记录，不删除本地文件。
- Web API 支持任务中心和下载历史的 query/status/offset/limit 查询参数，便于 Web 端后续分页搜索对齐。
- 验证：`python -m compileall -q app tests`，`PYTHONPATH=. pytest -q`，136 passed。

## 任务中心与下载历史 P0 专业优化

- 下载记录写入时自动绑定当前任务中心 `task_id`，任务中心详情可回溯关联下载记录。
- 下载历史详情新增关联任务、文件状态，CSV 导出补充关联任务字段。
- “恢复全部”和单条恢复均进入任务中心，显示恢复进度、成功/失败数量和失败原因。
- 修正“可恢复”筛选逻辑：只展示真实可恢复记录，不再混入所有失败/取消/运行中记录。
- 任务中心清空记录改为安全清理，运行中/等待中任务不会被隐藏或误删。
- Web 端取消任务语义收敛：运行中/等待中任务不允许只取消记录，避免 UI 状态和真实队列状态冲突。
- 验证：`PYTHONPATH=. pytest -q`，136 passed。

# Changelog

## 1.0.4

- 设置模块继续做 P3 稳定性优化：完整设置页不再使用原生 `ft.Switch`，统一改为按钮式布尔开关，降低 Windows/Flet WebView2 灰块和卡顿风险。
- 布尔设置状态统一由 `_toggle_values` 管理，保存、运行模式预设、保存后回填仍按原配置键读写，不改变配置文件结构。
- 单账号通知列表改为搜索、分页和批量开启/关闭，避免账号多时一次性渲染大量开关控件。
- 新增 `tests/test_settings_toggle_and_account_list_regression.py`，覆盖设置页无原生 Switch、账号通知分页、状态字典保存等回归点。
- `scripts/ui_static_check.py` 增加 P3 稳定性规则，阻止设置页重新引入原生 Switch 或缺失分页/按钮式开关标记。
- 验证：`135 passed`，`release_gate: OK`。

## 1.0.3

- 设置模块继续做 P2 存储维护优化：新增“扫描残留”和“清理临时文件”能力。
- `settings_storage_service.py` 扩展为存储检查 + 存储维护服务，可扫描 `.tmp`、`.part`、`.download`、`.crdownload` 等临时下载残留，并统计 0 字节文件、空目录和占用空间。
- 清理操作增加二次确认，只删除明确的临时下载残留，不删除正常视频/图片文件，降低误删风险。
- 设置页和兼容设置页的存储区域都增加扫描/清理入口，反馈使用局部状态文本，避免整页重绘。
- 新增 `tests/test_settings_storage_maintenance.py`，覆盖残留扫描和安全清理逻辑。
- 验证：`124 passed`，`release_gate: OK`。

## 1.0.2

- 严格修复 Win 端问题中心再次出现灰块/空白的问题：问题中心移除会触发 Windows/Flet 灰块的复杂开关卡片、`Switch`、`OutlinedButton` 和扩展空状态容器。
- 问题中心改为保守布局：`TextButton` 按钮式开关、非扩展 Column、纯文本空状态，避免空列表或复杂控件被渲染为大面积灰色占位。
- 应用切页增加异常边界：页面加载失败时不再留下空白页，而是显示错误信息，便于定位问题并继续切换其他页面。
- 验证：`98 passed`，`smoke_check`、`ui_static_check`、`ui_layout_regression_check` 通过。

## 1.0.1

- 修复 Win 端问题中心点击后页面空白的问题：`ft.OutlinedButton` 不再使用当前 Windows Flet 版本不兼容的 `text=` 关键字参数。
- 保留“风控与调试开关”的按钮式交互，避免 `ft.Switch` 在部分 Windows/Flet 环境渲染成灰色占位块。
- UI 静态检查新增 Flet 按钮构造兼容性规则，禁止 `ft.OutlinedButton` / `ft.ElevatedButton` / `ft.TextButton` / `ft.FilledButton` 使用 `text=` 关键字，防止同类运行时崩溃再次出现。
- 验证：`98 passed`，`smoke_check`、`ui_static_check`、`ui_layout_regression_check`、release 打包通过。

## 0.9.8

- 修复保存设置时旧的 `selected_download_path` 覆盖输入框当前路径的问题。
- 视频保存路径输入框新增 `on_change` 同步，手动粘贴路径后保存会以输入框为准。
- `_storage_dir()` 和 `save_settings()` 改为优先读取可见输入框，避免旧状态导致路径看起来保存但实际不变。
- UI 静态检查新增禁止旧状态优先覆盖输入框的回归守卫。

## 0.9.7

- 存储目录选择成功后立即保存到用户配置，并回读校验。
- 新增“应用路径”按钮：手动修改输入框后可直接写入配置，不依赖目录选择器。
- 保存逻辑改为输入框/选择器双通道，最终统一走 `_persist_download_path()`，避免只显示变化但配置未变。
- UI 静态检查新增“立即持久化存储路径”的回归守卫。

## 0.9.6

- 修复选择存储目录后点击保存，配置路径没有实际变化的问题。
- 选择目录后新增页面级 `selected_download_path` 状态，保存时优先使用该状态，避免 Flet TextField 同步延迟导致读取旧值。
- 保存用户配置后立即从 `user_settings.json` 回读校验，若路径未写入会明确报错。
- 保存成功后同步刷新输入框和运行态设置。

## 0.9.5

- 修正“选择存储目录”一次点击可能弹出两个目录选择窗口的问题。
- 存储目录选择链路改为单路径：Windows 只使用系统原生 FolderBrowserDialog，非 Windows 使用 tkinter。
- 移除存储目录专用 Flet FilePicker/get_directory_path 分支，避免静默失败和二次弹窗。
- UI 静态检查新增禁止双选择器链路的回归守卫。

## 0.9.4

- Windows 下“选择存储目录”改为优先使用系统原生 FolderBrowserDialog。
- 避免 Flet FilePicker 静默失败导致点击按钮没有任何反应。
- 点击后立即显示“正在打开目录选择器...”提示，失败时明确提示手动粘贴路径。
- 保留 tkinter 和 Flet FilePicker 作为非 Windows 或异常场景兜底。

## 0.9.3

- 修复设置页“选择存储目录”点击无反应的问题。
- 修正 picker 创建后被错误清空的状态管理问题。
- 目录选择按钮改为异步事件触发，异常时能给出明确提示。
- 增加 tkinter 原生目录选择兜底，FilePicker 不可用或失败时仍可选择目录。
- UI 静态检查新增 picker 状态回归守卫。

## 0.9.2

- 设置页存储按钮从“打开存储目录”改为“选择存储目录”。
- 新增目录选择器，选择后自动回填视频保存路径并刷新命名预览。
- 目录选择后不会立即写配置，需要点击保存设置后生效，避免误改路径。
- UI 静态检查新增目录选择器回归守卫。

## 0.9.1

- 修复设置页“打开存储目录”按钮不可用的问题。
- `PageBase.open_path_or_url()` 增加旧参数 `error=` 兼容，避免同类按钮事件因参数名错误直接失败。
- 本地路径打开逻辑改为优先使用系统文件管理器；不存在的本地路径给出明确失败提示。
- UI 静态检查新增设置页打开存储目录参数校验。

## 0.9.0

- 将下载历史与恢复从任务中心拆成独立页面，并增加灰块 UI 回归静态检查。
- 新增下载历史保守布局，避免空列表时出现大面积灰色占位。
- 新增 SQLite/JSON 兼容开关 `sqlite_json_mirror_enabled`，默认保持旧版 JSON 镜像。
- 新增 Parser 风控、权限、网络、作品失效等失败分类模型。
- 新增真实平台验证脚本 `scripts/real_platform_check.py`，真实链接由用户本机显式传入。
- 新增本地敏感数据清理脚本 `scripts/clear_local_data.py`。
- 新增版本一致性检查、Flet UI 导入 smoke、发布包内容检查。

## 视频解析模块用户体验优化

- 输入区新增链接整理、去重、清理长链接参数和识别统计。
- 新增剪贴板粘贴入口。
- 结果卡片操作按钮改为图标 + 文字。
- 图集和视频结果展示更明确的类型信息。
- 新增下载全部、只下载视频、只下载图集。
- 新增复制失败链接。
- 大量结果渲染增加节流和默认渲染上限，降低批量解析卡顿。
- 验证：107 passed。

## 下一轮性能与体验优化

- 视频解析输入区新增链接摘要，长链接自动短显。
- 视频解析结果新增选择模式，支持下载选中、选择视频、选择图集、选择可下载结果。
- 视频解析新增失败集中处理面板和下载保存规则提示。
- 内容监控批量设置改为勾选式修改，未勾选项目保持不变。
- 补齐 GitHub Actions CI / Release 脚手架，发布自动化测试通过。

## P3 深度性能与使用体验优化

- 视频解析历史升级为解析资源库，保留资源明细、失败明细和失败分类。
- 内容监控新增异常修复中心和新作品收件箱摘要面板。
- 新增深度优化测试，验证资源库和异常修复入口。

## 设置模块 P0 拆分优化

- 新增 `app/core/ui_services/settings_service.py`：集中处理设置保存、Cookie 保存、运行时应用。
- 新增 `app/core/ui_services/settings_validator.py`：集中处理数值范围校验、非法值修正、开发模式覆盖逻辑。
- 新增 `app/core/ui_services/settings_runtime_apply.py`：集中处理解析器并发、Cookie 池和账号通知的即时生效。
- 新增 `app/core/ui_services/settings_backup_service.py`：集中处理配置包、完整备份、脱敏备份、导入恢复。
- 设置页保存后会回填修正后的配置值，并显示变更、生效范围和 Cookie 同步状态。
- 配置备份区新增“脱敏备份”入口，不导出 Cookie 和 web_auth 登录凭证。
- 新增 `docs/SETTINGS_MODULE_REFACTOR_PLAN.md`，记录 P0-P3 拆分和优化路线。


## 设置模块 P2 Cookie 与代理诊断优化

- 新增 `app/core/ui_services/settings_cookie_service.py`：Cookie 池分析、脱敏展示、重复/无效片段统计、健康状态合并。
- 新增 `app/core/ui_services/settings_proxy_service.py`：代理格式校验、地址自动规范化、代理连通性测试。
- 设置页新增“分析 Cookie 池”和“测试全部抖音 Cookie”，不再只能测试第 1 个 Cookie。
- 设置页代理区域新增“校验代理格式”和“测试代理”，支持 `127.0.0.1:7890` 自动规范为 `http://127.0.0.1:7890`。
- Cookie 状态展示仅显示脱敏键名、长度和健康状态，不暴露 Cookie 原文。
- 代理地址校验接入 `settings_validator.py`，保存时会提示代理格式问题或自动规范化结果。
- 新增 Cookie/代理服务测试，继续通过灰块回归检查。

## P2 Task Center & Download History Optimization

- Download recovery now supports bounded concurrency (1-5) with Task Center progress updates, ETA estimates, and failure-category summaries.
- Download History now prompts before bulk recovery and lets users choose serial recovery, concurrency 2, or concurrency 3.
- Download History adds a file-state verification action and clearer recovery-result messages with concurrency, task ID, and failure categories.
- Task Center details now summarize associated download records, recoverable counts, missing-file counts, and failure categories.
- Batch task details now group failure reasons by category before showing raw failure IDs/reasons.
- Web console Download History now supports keyword search, missing-file status, recover-all, export-current-filter, file-state labels, and failure metadata.
