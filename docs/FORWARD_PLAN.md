# BilibiliCrawler 前瞻计划

> 状态：执行中
>
> 建立日期：2026-09-02
>
> 适用范围：v3.4.0 候选验收、发布收尾及后续兼容性工作
>
> 本文档是当前前瞻任务的权威入口；历史阶段记录继续保留在对应版本文档中，不再向
> `POST_3.3.0_PLAN.md` 追加新任务。

## 任务总览

| 优先级 | 任务 | 状态 | 完成标准 |
|---|---|---|---|
| P0 | 完成 v3.4.0 桌面真机验收 | 已完成 | 完成爬取、取消、重试、分析、导出、凭据脱敏、升级与卸载数据保留检查，并记录证据 |
| P1 | 修复 CLIProxyAPI Antigravity HTTP 400 参数兼容问题 | 规划中 | 精确识别被拒参数，安全兼容重试通过，普通 400 不被误重试，安装版 live smoke 通过 |
| P1 | 完成 Python 包远端发布配置 | 已完成 | TestPyPI 与 PyPI Trusted Publisher 配置完成，GitHub environments 规则复核通过 |
| P1 | 完成 v3.4.0 正式发布 | 已完成 | 从干净 worktree 构建正式资产，标签、GitHub Release、TestPyPI、PyPI 依次验证通过 |
| P2 | 复盘安装器跨构建覆盖残留 | 待评估 | 明确旧 sidecar 文件残留的影响，决定由安装器清理、版本化目录或文档约束处理 |

详细发布步骤与不可逆边界继续以 [v3.4.0 发布准备与验收清单](RELEASE_3.4.0.md) 为准。

## P0：v3.4.0 桌面真机验收

已完成。2026-09-02 在候选 `526e8cc` 的预检安装包上按下列顺序逐项执行，全部通过、未发现问题；
产物与门禁证据见 [v3.4.0 清单](RELEASE_3.4.0.md) 的验收记录。

原检查顺序：

1. 检查当前 Windows 缩放下的任务栏图标、桌面与开始菜单快捷方式。
2. 完成普通评论爬取，核对进度、评论数量、CSV 与 run 目录。
3. 在爬取过程中取消并立即重试，确认部分结果、单一终态和重试能力。
4. 完成评论分析，核对结构化结果、词云、`analysis.json` 与 Markdown 报告。
5. 在分析过程中取消并立即重试，确认不会出现迟到的成功终态。
6. 验证错误 provider/model 的分类提示，以及修正配置后复用原 run 的恢复能力。
7. 用 canary Key 分析后扫描完整 run，确认持久化文件零命中。
8. 完成 v3.3.0 → v3.4.0 覆盖升级和默认卸载的数据保留验证。

任何失败均记录为独立任务，不用自动化测试替代真实窗口观察。

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

## P1：远端配置与 v3.4.0 发布

已完成。v3.4.0 于 2026-09-02 公开发布，标签指向 `dc71f58`：GitHub Release 带 Windows x64 安装包
与四个 Python 资产，`bilibili-crawler` 3.4.0 已上架 PyPI，三处产物 SHA-256 一致。逐项证据见
[v3.4.0 清单](RELEASE_3.4.0.md)。

原执行步骤：

1. 在 TestPyPI 与 PyPI 配置 `bilibili-crawler` 的 pending Trusted Publisher。
2. 复核 GitHub `testpypi`、`pypi` environments 仅允许 `main`，且 `pypi` 保留人工 reviewer。
3. 真机验收和所有阻断修复完成后，从干净 worktree 重新构建正式安装包及 Python 资产。
4. 创建 annotated `v3.4.0` 标签与 Draft Release，验证所有资产和校验文件。
5. 依次执行 GitHub Release、TestPyPI、PyPI 发布与公共下载验证，不跳步或复用失败资产。

## P2：安装器覆盖残留评估

同版本候选覆盖安装时发现，当前 NSIS 卸载清单不会删除旧安装器遗留但新安装器不再包含的
sidecar `_internal` 文件。人工验收前已通过备份、默认卸载、移动旧 sidecar 目录和重装获得干净环境，
用户数据未受影响。

后续需评估正式方案：安装前精确清理程序资源目录、使用版本化资源目录，或在版本升级策略中显式约束。
任何方案都必须严格排除 `user-data`、`analysis-runs`、`analysis-assets` 等用户数据目录，并补充升级回归。

## 状态维护规则

- 只有实现、测试和对应验收证据全部完成后，任务才能标记为完成。
- 外部服务偶发成功不能替代可复现证据，历史 provider 的成功也不能证明新 provider 兼容。
- 新发现写入本文档对应任务；版本发布细节写入版本清单，历史版本计划不再追加新工作。
- 对涉及 Key、Cookie、OAuth 或远端错误正文的证据只记录脱敏后的结构化信息。
