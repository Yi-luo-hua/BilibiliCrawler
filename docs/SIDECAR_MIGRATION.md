# Sidecar 编排下沉迁移方案（v3.3.0 第二步）

把 `backend/sidecar.py` 的 `_run_comments` 与 `_run_analysis` 迁到 `AgentService`，
同时不改变桌面端已验证的取消语义与 RPC 契约。

| | |
|---|---|
| 状态 | 阶段 1–2 已合并；阶段 3（adapter outcome / 事件通道）进行中。**`backend/sidecar.py` 仍未改动** |
| 前置 | PR #5（输出目录策略统一）、PR #7（行为基线）、PR #8（策略与请求参数分离）均已合并 |
| 迁入范围 | 评论爬取；`source` **严格等于** `comments` 的分析 |
| 不在范围 | 扫码登录、动态爬取；`dynamics` / `all` / `auto` / 缺失 / 非法 source 的分析 |

---

## 结论先行

**这一步不是纯搬运。** `AgentService` 是按 agent 场景写的，它的默认策略与桌面端直接冲突，
而且它对外只暴露摘要式的 `TaskSnapshot`——桌面端需要的完整分析结果、词云 base64 和
原始进度百分比都拿不到。

所以迁移的核心工作有两项，都在接线之前：

1. **把「策略」从「编排」里分离**——编排共用，策略按调用方注入。
2. **给服务增加 adapter 专用的 outcome / typed event 通道**——让 sidecar 能拿到完整结果，
   同时不把大体积词云塞进公开的 `TaskSnapshot`。

---

## 两个已定的决定

### 落盘：接受桌面评论任务产生 run 目录

不为了维持「不落盘」再造一套内存存储。`run_id`、manifest、任务恢复、评论加载和分析结果
保存全都依赖 `RunStore`，关掉落盘等于要写一个完整的 `MemoryRunStore`，那不是轻量策略注入。

边界：

- 只有**迁入 AgentService 的评论爬取和评论分析**落盘；动态路径保持原样。
- Sidecar 增加内部 `_last_comment_run_id`，评论分析复用该 run。
- `_last_comments` 和 `_last_analysis` 继续保留，维持现有 RPC、导出和 UI 行为。
- 本步**不向前端新增 RPC 字段**，`run_id` 仅作内部衔接信息。
- README 与发版说明要写清：数据目录位置、磁盘占用、以及凭据不会落盘。
- 在没有实现启动恢复之前，**不要宣传成「桌面重启后可恢复」**——目前只是数据持久化。

### 来源分叉：只迁精确的评论来源

桌面端的 `getAutoAnalysisSource()` 会产生三种非空取值，另外在既无评论也无动态时返回
`null`（此时前端直接提示并中止，不会发起 `analysis.start`）。`_normalize_source` 还会把
`auto` 归一化。只有精确匹配才迁移：

| `source` | 走哪条路径 |
|---|---|
| `comments` | AgentService |
| `dynamics` | 旧 Sidecar 路径 |
| `all` | 旧 Sidecar 路径 |
| 缺失 / `auto` / 非法值 | 旧 Sidecar 路径 |

`all` 这一支容易漏。准确的产生条件是：`getAutoAnalysisSource()` 先服从上一次的
`latestSource`——`latestSource === "comments"` 且有评论时直接返回 `comments`，即便同时
存在动态；只有在没有可服从的 `latestSource`（或它已失效）且评论与动态**同时存在**时，
才落到 `hasComments && hasDynamics → "all"` 这一支。

也就是说 `all` 不是「有评论又有动态」的必然结果，但确实会出现，而 `AgentService.start_analyze`
只处理评论。漏判会在不迁移动态爬取的前提下先把混合来源的分析弄坏。

除 `all` 外，`auto`、缺失和非法值也都必须走旧路径——`_normalize_source` 会把它们按当前
数据推断成 `comments` / `dynamics` / `all` 中的任意一个，不能依赖这个推断来路由。

---

## 必须原样保留的契约

桌面前端（`App.tsx` / `sidecarClient.ts` / `taskState.ts`）直接依赖下列表面，
迁移后任何一项变化都算回归。

| 类别 | 表面 | 要求 |
|---|---|---|
| RPC（本步涉及） | `comments.start` `analysis.start` `task.stop` `export.csv` `analysis.latest` `analysis.export` | 方法名、参数键、响应字段不变 |
| RPC（本步不动） | `session.status` `dynamics.start` `qr.login.start` `qr.login.cancel` | 继续走现有实现 |
| 事件 | `progress` `log` `stats` `finished` `error` `cancelled` `analysis.progress` | 事件名、字段、**发出顺序**不变 |
| 帧格式 | `{"kind":"event"\|"response", …}` | stdout 保持 ASCII-safe（`ensure_ascii=True`） |
| 会话状态 | `_last_comments` `_last_analysis` `_last_comment_context` | `export.csv` / `analysis.start` / `analysis.export` 依赖，不能直接删 |

---

## 语义冲突清单

风险标签表示改错了会不会被现有测试挡住。

| # | 冲突点 | AgentService 现状 | 桌面端需要 | 风险 |
|---|---|---|---|---|
| 1 | 页数上限 | `MAX_PAGES_CEILING = 50` 强制夹取 | 默认 100，用户可调，无 agent 上限 | 静默回归 |
| 2 | 图表模块 | 强制 `AGENT_CHART_KEYS`，排除词云 | 用 UI 勾选的 `chart_keys`，含词云 | 静默回归 |
| 3 | LLM 凭据 | 内部 `resolve_llm_credentials()` | 用请求里 `params.llm_config` 的 key | 功能失效 |
| 4 | 取消路由 | 每个 `_Task` 各有独立 `cancel_event`，但取消要按 `task_id` 调 `AgentService.stop(task_id)` | Sidecar 需保存当前 `task_id` 并精确转发；停爬虫**不**得置分析取消位（v3.1.1 行为） | 部分覆盖 |
| 5 | `batch_size` | 不透传 | UI 可配，需透传给 processor | 易漏 |
| 6 | **完整结果不可得** | `TaskSnapshot` 只有 `summary` + `artifacts`；`RunStore.save_analysis` 会 `pop("report_markdown")` 并把词云 base64 换成磁盘路径 | 需要**原始 result** 才能恢复 `_last_analysis`、词云展示和报告导出 | 阶段 3 已补：`take_outcome()` |
| 7 | **分析进度被压缩** | `task.emit(70 + percent * 0.25, …)`，原始百分比已丢失 | `analysis.progress` 需要 0–100 原值 | 阶段 3 已补：`EventKind.ANALYSIS_PROGRESS` |
| 8 | **空结果语义** | 空 → `ServiceError(CRAWL_FAILED)` | 旧行为是 `finished(count=0)`，不报错 | 静默行为变更 |
| 9 | **评论爬取的停止语义** | 停止 → `cancelled` | 旧行为是带部分数据走 `finished`（分析取消才发 `cancelled`，两条路径不同） | 静默行为变更 |
| 10 | **依赖注入点** | 默认自建 `BilibiliAPI()` | 必须复用 `SidecarServices` 注入的 api / crawler factory / data_processor / analysis_processor | 丢登录态、破坏现有测试替换点 |
| 11 | 结果呈现 | — | base64 词云、截断、asset 目录命名留在 sidecar | 保持现状即可 |

### 第 6、7 条是本步的结构性前提（阶段 3 已补）

这两条不是「接线时注意一下」的问题：`AgentService` 原本**没有**任何对外通道能交出
完整的分析结果或原始进度百分比，第 5 阶段的分析接线根本无法保持 `analysis.latest`、
词云展示和 `analysis.export` 的现有行为。

阶段 3 补出的通道分两半，都是 adapter 专用、默认关闭：

| | 用法 | 交出什么 |
|---|---|---|
| 结果 | `AgentService(retain_outcome=True)` + `take_outcome(task_id)` | `TaskOutcome`：清洗后的评论、**完整** stats 字典、处理器原样返回的 `result` |
| 事件 | `AgentService(events=listener)` | `TaskEvent`：`EventKind.LOG`（爬虫原文）、`EventKind.ANALYSIS_PROGRESS`（未压缩的 0–100） |

四条约束写进了测试：

- **`TaskSnapshot` 不变胖**——词云 base64 与完整报告都不进快照，MCP 返回值不膨胀。
- **不装监听器就完全无感**——进度队列与快照逐字段相同，`retain_outcome` 默认 `False`，
  MCP / CLI 一个字节都不多留。
- **结果先取后存，而且是深拷贝**——两半都在 store 拿到同一个对象之前记录，
  拷贝是 `copy.deepcopy`。浅拷贝会把每个嵌套 list / dict 继续和 store 共享，
  而 `save_analysis` 下一步要改的正是那些。测试用一个「就地改写嵌套对象」的 store 把
  顺序和深度一起钉住。
- **只有终态任务能 `take_outcome()`**——组合任务的两半在不同时刻记录，
  提前取会拿到半个 outcome、把另外半个留成第二个，同一个任务被消费两次。

终态既不走事件通道，也不能从 `take_outcome()` 反推，只能从 `TaskSnapshot` 读——
只留一条得知任务结束的路径，就不会有第二条路径发出陈旧的 `finished`。

### 第 8、9 条要先固化再决定

空结果和停止的语义确实不同，但**不能在迁移中顺手改掉**。做法是：先在旧 Sidecar 上写
characterization 测试把当前行为钉住，迁移后保持一致；如果之后要改成 AgentService 的语义，
另开一个明确的行为变更 PR。

---

## 实施顺序

每个 commit 独立通过测试；后续接线依赖前面的策略与 outcome API，因此**按逆序回退**，
不能任意撤销中间某个 commit。

1. **先补 characterization / golden 测试**（改动前的行为基线）
   覆盖：评论成功、空结果、异常、评论爬取停止（保留部分数据并发 `finished`）、
   分析取消（发 `cancelled` 且不发 `finished`）、登录态 API 复用、
   `comments` / `dynamics` / `all` 三种来源的分析，以及完整事件顺序。

2. **分离静态策略与单次请求参数**
   页数 ceiling 可以做成调用方策略；`chart_keys`、`batch_size`、`llm_config`
   属于**本次分析的临时参数**。API Key 不能进长生命周期策略对象，也不能进 manifest。

3. **增加 adapter 专用 outcome / typed event 通道**
   让 sidecar 能取到完整 result 与原始进度百分比；公开 `TaskSnapshot` 保持精简。

4. **接入评论爬取**
   保存 `_last_comment_run_id`，从 `take_outcome()` 取回评论与完整桌面 stats
   （阶段 3 已把这两项放进 outcome，不必再重新加载和重算），保留 `_last_comment_context`。

5. **接入 `source == "comments"` 的分析**
   其余来源继续旧路径。

6. **端到端验证**
   通过真实 `SidecarClient.request()` 路径验证请求关联、取消、无陈旧 `finished`；
   最后在 Tauri 真机跑一次完整链路。

---

## 测试矩阵

「现有」指今天已能挡住回归的测试；其余为本步必须补的覆盖。

| 行为 | 现有覆盖 | 状态 |
|---|---|---|
| 停爬虫不置分析取消位 | `test_stop_crawler_task_does_not_set_analysis_cancel_flag` | 已有 |
| 分析取消用显式 cancel_event | `test_run_analysis_cancel_uses_explicit_cancel_event` | 已有 |
| 取消后不再发 finished | `test_run_analysis_cancel_after_result_does_not_emit_finished` | 已有 |
| 含「取消」字样的普通错误不误判 | `test_run_analysis_generic_error_containing_cancel_text…` | 已有 |
| LLM 阻塞时能迅速停止 | `test_analyze_stops_promptly_while_llm_request_is_blocked` | 已有 |
| stdout ASCII-safe | `test_protocol_output_is_ascii_safe…` | 已有 |
| 词云 asset 目录命名 | `test_word_cloud_asset_dir_uses_source_label_timestamp_and_bvid` | 已有 |
| **空结果：`stats` + `finished(count=0)` 完整 payload，不发 `error`，收尾 `progress(status="idle", percent=100)`** | 无 | 必补（characterization） |
| **评论爬取停止：`stats` → `finished(count, stats)` → `progress(idle, 100)`** | 无 | 必补（characterization。`_run_comments` 无取消检查，爬虫返回部分数据后照常走完；此处的 `finished` **合法**，不是陈旧帧） |
| **分析取消：`cancelled` → `log` → `progress(idle, 100)`，且此后不得出现 `finished` 或 `error`** | `test_run_analysis_cancel_after_result_does_not_emit_finished`（部分） | 必补完整帧序列 |
| **桌面端页数不被夹到 50** | 无 | 必补 |
| **桌面端 chart_keys 含词云** | 无 | 必补 |
| **凭据来自 params 而非环境** | 无 | 必补 |
| **API Key 不进 manifest / 不进策略对象** | 部分（agent 侧有） | 必补（桌面路径） |
| **`dynamics` 与 `all` 仍走旧路径** | 无 | 必补 |
| **`analysis.progress` 仍是 0–100** | `test_analysis_progress_reaches_the_listener_unremapped`（服务侧） | 接线后仍必补（sidecar 侧） |
| **`task.stop` 精确转发到 `AgentService.stop(task_id)`** | 无 | 必补（Sidecar 需保存当前 task_id；现有测试只覆盖旧路径的取消位隔离） |
| **内部 `_last_analysis` 保留原始结果** | `test_the_analysis_outcome_is_the_processors_untouched_return`（服务侧） | 接线后仍必补（`analysis.export` 的 markdown 依赖它） |
| **`analysis.latest` 返回值与当前 compact display payload 完全一致** | 无 | 必补（含 `word_cloud_image` / `word_cloud_image_path`，且 `report_markdown` 仍为空串） |
| **复用注入的 api / factory / processor** | `test_comment_task_reuses_logged_in_api_session` | 必补（迁移后保持） |
| **事件序列逐帧一致：名称、顺序与 payload** | 部分 | 必补（录制迁移前后 `CaptureSidecar.messages` 比对，不只比事件名） |
| **`stats` 事件携带完整 comments stats 字段** | 无 | 必补（逐字段断言，非仅 `total`） |
| **`_last_comment_context` 保持** | 无 | 必补（词云 asset 目录命名依赖它） |
| **评论成功：`stats` + `finished(count, stats)` 完整 payload + 收尾 `idle` 帧** | 无 | 必补（characterization） |
| **评论异常：`error(mode, message)` 完整 payload，不发 `finished`，收尾 `idle` 帧仍发出** | 无 | 必补（characterization） |
| **`auto` / 缺失 / 非法 source 走旧路径** | 无 | 必补 |
| `batch_size` 透传 | 无 | 补 |
| `export.csv` 在迁移后仍可用 | 无 | 补 |
| 真机桌面端完整链路 | 无 | 发版前必做，不以自动化测试代替 |

---

## 验收门槛

- 每阶段结束都跑：venv 全量、无 mcp 全量、桌面 TS，三者全绿方可进入下一阶段。
- 凡声称「行为不变」的地方，一律先移除修复、确认对应测试变红，再写进 PR。
- 合并前在真机桌面端手动跑一遍：爬取 → 分析 → 停止 → 导出。

## 本步不做

- 扫码登录（`qr.login.*`）与动态爬取（`dynamics.start`）的迁移。
- 向前端暴露 `run_id`，或实现「桌面重启后恢复任务」。
- 把空结果 / 停止语义改成 AgentService 的版本（如需变更另开 PR）。
- 任何 MCP 侧工具签名或默认值的改动。
