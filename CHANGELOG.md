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
