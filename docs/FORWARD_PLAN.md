# BilibiliCrawler 前瞻计划

> 状态：执行中
>
> 建立日期：2026-09-02
>
> 适用范围：v3.4.0 发布之后的兼容性修复与功能演进
>
> 本文档是当前前瞻任务的权威入口，只记录未完成的工作。任务完成并归档验收证据后从本文档移除，
> 不在此长期留存；v3.4.0 的真机验收与发布记录见
> [v3.4.0 发布准备与验收清单](RELEASE_3.4.0.md)，更早的阶段记录保留在对应版本文档中，
> 不再向 `POST_3.3.0_PLAN.md` 追加新任务。

## 任务总览

| 优先级 | 任务 | 状态 | 完成标准 |
|---|---|---|---|
| P1 | 修复 CLIProxyAPI Antigravity HTTP 400 参数兼容问题 | 待 live 验证 | 精确识别被拒参数，安全兼容重试通过，普通 400 不被误重试，安装版 live smoke 通过 |
| P2 | 新增分析模块自定义文本模块 | 规划中 | 自定义模块可保存并参与分析，结果进入界面与报告，未启用时输出与实施前一致 |
| P2 | 复盘安装器跨构建覆盖残留 | 待评估 | 明确旧 sidecar 文件残留的影响，决定由安装器清理、版本化目录或文档约束处理 |

## P1：CLIProxyAPI Antigravity HTTP 400 参数兼容

### 已确认事实

- 复现环境为 CLIProxyAPI `7.2.145`、commit `d9cea890`，监听 `127.0.0.1:8317`。
- BilibiliCrawler Base URL 应为 `http://127.0.0.1:8317/v1`；客户端会追加 `/chat/completions`。
- 模型 `gemini-3.7-flash-high` 出现在已认证模型列表中，`owned_by` 为 `antigravity`。
- 正确的 `POST /v1/chat/completions` 多次在约 0.3–1.8 秒内返回 HTTP 400，不是连接或读取超时。
- `/chat/completions` 与 `/v1/chat/completions/chat/completions` 的 404 来自错误 Base URL，不是产品故障。
- 诊断产生的 `/v1/models` 401→200 和 Management API 404 不计入产品故障。
- 先前显示第 3/4 批的进度使用的是 DeepSeek API，不能作为 CLIProxyAPI 已成功完成前两批的证据。
- 失败只影响新的 analysis attempt；原 run、评论和上一份有效报告仍然保留。

### 当前假设与边界

BilibiliCrawler 的批次请求固定发送 `temperature: 0.2`，总结合并请求发送 `temperature: 0.18`，
两者均发送 `response_format: {"type":"json_object"}`。Antigravity 上游存在拒绝采样字段并返回 400
的同类记录，因此 `temperature` 是首要嫌疑，`response_format` 是次要嫌疑。

当前安全错误表面不会展示远端响应正文，CLIProxyAPI 请求错误日志也未提供本次具体字段，因此上述判断仍是
待验证假设。不得把任意 HTTP 400 直接认定为同一种兼容问题。

### 当前进度

步骤 1–5 已实现并通过回归：结构化 `param == "temperature"` 且 code 属 unsupported 类时移除该字段
重发一次，其余 400 一律 fail closed；400/422 的安全说明附带脱敏后的 `code`/`param`。步骤 6 的
live smoke 未做——它需要可用的 CLIProxyAPI/Antigravity 环境，且必须用重建后的安装版执行。

尚未验证的关键假设：上游是否在结构化 `param` 字段中指明 `temperature`。若它只返回自由文本，
当前实现按设计不会降级，live smoke 仍会失败；届时记录脱敏 `code`/`param` 再决定是否放宽条件。

### 实施步骤

1. 扩展 provider 错误解析，只提取并传递脱敏后的 HTTP status、error code 与 param。
2. 保持远端正文、API Key、prompt、评论内容不进入日志、快照、manifest、分析 JSON 或报告。
3. 仅当结构化错误明确指出 `temperature` 不受支持时，移除该字段并占用共享重试预算重新请求。
4. 保留现有的 `response_format` 精确降级、最多三次请求、取消和退避语义。
5. 任意 400、模糊错误或其他参数错误继续 fail closed，不自动删字段或重放请求。
6. 修复完成后重建 sidecar 与安装包，以相同 CLIProxyAPI/Antigravity 配置执行 live smoke。

### 验收标准

- 显式 `temperature` unsupported 错误先由回归夹具复现，修复后只重试一次且第二次请求不含该字段。
- `response_format` 的既有兼容降级继续通过。
- 无关参数错误、空错误体和普通 HTTP 400 均不重试。
- 重试预算、取消、超时与旧报告保留语义不变。
- 合成凭据与远端正文 canary 在 stdout、stderr、日志、快照和完整 run 目录中零命中。
- 普通 Python、MCP、桌面单元与真实 SidecarClient 门禁全部通过。
- 安装版使用 `gemini-3.7-flash-high` 完成至少一次最小分析；若上游仍拒绝，记录脱敏 code/param 并维持未完成状态。

## P2：分析模块自定义文本模块

来源为社区 issue #18：分析模块现有 7 个预设，希望增加一个自由项，由用户自行填写提示词。

### 已确认事实

- 现有 7 个预设并不同质。时间趋势、等级分布、地域分布由 `_build_local_layers` 纯本地统计产出，
  LLM 不参与；情绪分布、主题排行、词云由 LLM 返回 `{name,value}` 结构，提示词、字段约定与图表渲染
  三者绑定；只有舆论深入剖析返回自由文本，与"自定义提示词模块"同构。
- 同一份 7 项清单在四处硬编码：`LLMAnalysisProcessor.ALL_CHART_KEYS`、桌面端 `analysisChartOptions`、
  Tauri 侧 `default_analysis_chart_keys`，以及 caller policy 使用的 `AGENT_CHART_KEYS`。
- Tauri 侧 `normalize_analysis_chart_keys` 与桌面端 `normalizeAnalysisChartKeys` 都是白名单过滤。
  未放行前，自定义模块 id 会在配置读写时被静默丢弃，保存能力无法成立。
- sidecar `_display_analysis_result` 是白名单投影，未显式加入的结果字段不会到达桌面端。
- 分析结果解析依赖 `_extract_json_text`。任何促使模型改变输出结构的自定义提示词都会让整批分析失败，
  并归类为 `LLM_RESPONSE_INVALID`。

### 范围边界

本任务只新增"文本类模块"这一种可插拔类型，内置 7 项的提示词、合并与渲染路径保持不变。把舆论深入剖析
改写为同一套路径的内置文本模块属于后续阶段，须在本任务上线并稳定后单独评估。图表类与本地统计类模块
不做插件化，其渲染逻辑无法数据驱动。

### 数据契约

自定义模块保存在 `user_config.json` 的 `analysis_custom_modules`，每项包含 `id`、`title`、`prompt`
与 `enabled`。`id` 形如 `custom_` 加六位十六进制，由桌面端生成后不再变更；结果与历史报告均按 `id`
索引，因此改名不丢结果。标题上限 24 字，提示词上限 500 字，最多保存 8 个，单次分析最多启用 3 个。

`analysis.start` 新增 `custom_modules` 参数，只传启用项，并把这些 `id` 混入既有的 `chart_keys`，
不另开启用列表。模型返回值新增 `custom_results` 对象，键为模块 `id`，值为文本。分析结果的 `meta`
新增 `custom_modules` 定义快照，用于在模块改名或删除后仍能正确复现历史报告。

### 实施步骤

1. 在 `LLMAnalysisProcessor` 增加自定义模块归一化，剔除 `id` 不合法或标题、提示词为空的条目，
   截断超长字段并限制数量；`_normalize_chart_keys` 的白名单扩展为内置项加已归一化的自定义 `id`。
2. `_build_prompt` 为每个自定义模块追加一段说明，用户原文包裹在显式分隔标记内，先剥除原文中的
   分隔标记字样，并在其后声明分隔块只描述分析角度，不得改变输出结构、字段名与语言。
3. `_merge_llm_results` 按 `id` 汇总各批文本，复用现有分段合并逻辑产出 `custom_results`；
   `analyze` 将定义快照写入 `meta`。
4. `_build_markdown_report` 依据 `meta` 快照建立 `id` 到标题的映射，遍历启用模块时为自定义模块
   输出独立章节。
5. 打通服务链路：`_run_comment_analysis` 显式透传 `custom_modules`，`AgentService.start_analyze`
   与分析参数构造同步扩展，caller policy 对 `custom_` 前缀直通，`_display_analysis_result` 显式
   加入 `custom_results` 并限制条数与单条长度。
6. Tauri 侧 `UiConfig` 增加 `analysis_custom_modules`，`normalize_analysis_chart_keys` 接受自定义
   `id` 集合，并在归一化时丢弃非法条目。
7. 桌面端补齐类型定义、配置默认值与归一化调用；模块勾选区渲染自定义项及其编辑与删除入口，新增标题
   与提示词编辑界面；结果区复用文本卡片渲染并优先使用 `meta` 快照中的标题；图表资产导出跳过自定义模块。
8. 补充回归测试：归一化过滤与截断、提示词分隔与转义、多批结果按 `id` 合并、模块删除后的报告渲染、
   display 投影包含 `custom_results`、caller policy 放行、Tauri 白名单往返保留。

### 验收标准

- 新建自定义模块后重启桌面端，模块定义完整保留。
- 启用自定义模块完成一次分析，结果区出现对应文本卡片，导出的 Markdown 报告包含同名章节。
- 删除模块后重新打开该次分析的历史报告，章节标题仍与运行时一致。
- 未启用任何自定义模块时，分析输出与本任务实施前完全一致。
- 提示词中试图改变输出格式的内容不会破坏 JSON 解析，并由回归夹具覆盖该场景。
- LLM 桩响应按真实格式构造，包含代码围栏与多余前言，不得使用比真实响应更宽容的替身。
- 普通 Python、MCP、桌面单元与真实 SidecarClient 门禁全部通过。

## P2：安装器覆盖残留评估

同版本候选覆盖安装时发现，当前 NSIS 卸载清单不会删除旧安装器遗留但新安装器不再包含的
sidecar `_internal` 文件。人工验收前已通过备份、默认卸载、移动旧 sidecar 目录和重装获得干净环境，
用户数据未受影响。

后续需评估正式方案：安装前精确清理程序资源目录、使用版本化资源目录，或在版本升级策略中显式约束。
任何方案都必须严格排除 `user-data`、`analysis-runs`、`analysis-assets` 等用户数据目录，并补充升级回归。

## 状态维护规则

- 只有实现、测试和对应验收证据全部完成后，任务才能标记为完成。
- 任务完成后从本文档移除，验收证据归档到对应版本清单；本文档只保留未完成的工作。
- 外部服务偶发成功不能替代可复现证据，历史 provider 的成功也不能证明新 provider 兼容。
- 新发现写入本文档对应任务；版本发布细节写入版本清单，历史版本计划不再追加新工作。
- 对涉及 Key、Cookie、OAuth 或远端错误正文的证据只记录脱敏后的结构化信息。
