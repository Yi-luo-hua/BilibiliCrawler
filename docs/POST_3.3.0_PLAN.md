# v3.3.0 之后的实施计划

更新：2026-09-01。基线：已发布 v3.3.0 / `main` 的 `6ae33df`。
本文把 `RELEASE_3.3.0.md` 的后续路线拆成可独立验收的批次，不承诺尚未确定的发布日期。

## 当前边界

- Sidecar 迁移阶段 1–6、导出加固、7 个 MCP 工具已合并，不再作为新开发任务。
- v3.3.0 已公开发布。旧发布清单的未勾选项是历史模板，不能据此判定发布未完成。
- 桌面、CLI、MCP 继续同仓库、同版本；本轮不更改版本号，不发布安装包或 Python 包。
- 不迁移动态/混合来源分析、扫码登录，不新增远程 MCP 服务或并发任务队列。
- 持久化 run 不等于桌面重启恢复；在完成启动恢复前不对外作此承诺。

## 顺序与状态

优先修正会选错 provider 的配置问题，再处理数据状态和失败恢复。打包不能固化目前的配置缺陷。

| 批次 | 优先级 | 交付物 | 依赖 | 状态 |
|---|---|---|---|---|
| A | P0 | 完整 LLM profile、`doctor`、配置回归测试 | 当前基线 | 实现、双线 review 与验证完成；未发版 |
| B | P1 | run 与分析尝试分离、重试与取消的原子语义 | A | 实现、双线 review 与验证完成；未发版 |
| C | P1 | provider 错误分类、复用原 run 的恢复提示 | A；结合 B 的尝试状态 | 实现、双线 review 与验证完成；未发版 |
| D | P1 | 耗时、超时、重试提示 | C | 实现、双线 review 与验证完成；未发版 |
| E | P1 | 真实 MCP stdio、Windows 编码与可选 live smoke | A–D | 实现、双线 review 与离线验证完成；live 未执行 |
| F | P1 | 命名空间、资源路径、CLI/MCP 可安装包边界 | A–C；E 提供验收基线 | 实现、双线 review 与本机安装验证完成；未发包 |
| G | P2 | wheel/sdist 干净安装与内容审计 | F | 审计、串行矩阵与双线 review 完成；并发 I/O 风险未定位 |
| H | P3 | GitHub 包资产、TestPyPI/PyPI、发布门禁 | G | 待开始 |
| I | P4 | 评估是否拆分版本 | 仅当用户群/发布节奏独立时 | 条件性，不排期 |

每批只修改本批相关行为，验证后再进入下一批；不在单个 PR 中混合状态机、UI、命名空间迁移和发布治理。

## A：完整 profile 与安全诊断（本次交付）

**问题**：只读取 `credentials.json` 的 Key，忽略相邻 `ui.json` 中的 provider/model，曾导致 DeepSeek Key 发往 OpenAI 默认地址并收到 401。

实现规则：

1. 按字段解析：非空 `BILIBILI_LLM_API_KEY` / `BILIBILI_LLM_BASE_URL` / `BILIBILI_LLM_MODEL` > 同一个桌面 profile > 既有 OpenAI 默认值。空白环境变量视为未提供。
2. `BILIBILI_AGENT_CREDENTIALS` 明确选择一个文件；未指定时依原有开发目录、currentUser、perMachine 顺序发现。Key 与 provider/model 不跨安装目录拼接。
3. 文件 Key 来自 `credentials.json.api_key`；端点与模型读取同目录 `ui.json.llm_base_url` / `llm_model`。也接受 credentials 文件内的 `base_url` / `model`，但两文件同一字段冲突时必须修正或显式环境覆盖。
4. 环境中三个字段完整时不读取文件；部分环境配置只覆盖对应字段。显式选择的文件不存在、已选择的 JSON 损坏或字段类型错误时返回 `CONFIG_INVALID`，不继续偷偷尝试另一安装。
5. 缺失 `ui.json` 保留默认值兼容；未知 provider 的模型名不由本地猜测。仅校验 HTTP(S) 地址形式，拒绝 URL 内嵌用户名/密码、查询参数、片段和控制字符。
6. 桌面 RPC 已传入的 `LLMCredentials.from_config()` 继续保持原行为；不把 Key 放进策略对象、manifest 或诊断输出。
7. `python -m backend.agent doctor` 返回来源类型、有效地址/模型、MCP 版本、运行目录权限估计。默认不联网、不构造 RunStore、不创建或迁移目录、不改配置。
8. `doctor --check-provider --timeout 10` 才会发送 GET `/models`。不跟随重定向，不打印响应正文，不调用聊天接口。HTTP 成功仅证明该端点可访问，不证明所选模型可分析。
9. 真 HTTP 回显夹具发现已有成功摘要未脱敏：对公开 TaskSnapshot 的 summary 补充 `scrub()`，保护 CLI/MCP 返回值，同时保留桌面 adapter outcome 的原始结果契约。

验收：

- 桌面分文件配置能传入实际 HTTP 请求；逐字段覆盖保持其余字段不变。
- 缺失、损坏、重复字段、错误类型、冲突、不同安装配置均有隔离夹具。
- 真 CLI 子进程能输出可解码 JSON，退出码区分成功/失败；未安装 MCP 也能运行诊断。
- canary Key 在诊断 stdout/stderr、分析 JSON/Markdown、manifest 与归档中零命中。
- 默认诊断无网络、无目录/配置修改。权限估计明确不等于真实写入验证，尤其是 Windows ACL。
- 普通 Python 全量、MCP 2.1.0 全量、桌面契约测试通过。外部付费模型 smoke 为自愿检查，不是此批门禁。

## B：run 与分析尝试分离

**问题**：对已有报告重新分析并取消，旧报告仍在，但 run 状态被覆盖为 `cancelled`。

- 先冻结 manifest schema：run 保存评论数据与最近一次已提交报告；每次分析拥有独立 `attempt_id`、状态、开始/结束时间、错误与产物引用。
- 新尝试失败或取消只结束本次尝试；保留上一份完整结果的状态和引用，不改写评论原始数据。
- 成功后先完整落定包含分析 JSON、Markdown、词云的不可变版本目录，再一次原子替换有效报告指针。根目录兼容副本另行归档/刷新，不作为多文件原子入口；中断后通过 artifacts 读取不会拼接不同版本。
- 兼容读取旧 manifest；不一次性重写历史目录，不破坏现有 MCP 返回字段及桌面 RPC。
- 用阻塞夹具覆盖请求前、请求中、结果返回后、文件 staging、提交边界的取消与重试。测试每个窗口的内存/manifest/报告一致性。

验收：完成 → 再分析 → 取消/失败 → 再成功，旧报告始终可用；成功后只切换一次有效版本；跨进程恢复仍可判定当前结果。此前明确的取消竞态必须有回归测试。

具体 schema、task/run 查询差异、兼容入口与写失败边界见 [分析尝试契约](ANALYSIS_ATTEMPTS.md)。

## C：错误分类与恢复指引

- 在 provider 调用边界区分鉴权（401/403）、模型配置、端点、网络/TLS、超时、限流与结果解析错误；不能只凭状态码把所有 404 判成模型不存在。
- 只有可恢复故障允许有限重试；鉴权/明显配置错误在昂贵重试之前结束。
- 爬取成功、分析失败时保留评论与 `run_id`，MCP `next_step` 明确给出 `analyze_run(run_id=...)`，不提示默认重新爬取。
- 错误仅包含必要的非敏感地址/模型/来源；所有输出与落盘边界仍经过脱敏，不转发原始鉴权响应正文。

验收：每种错误均有 provider 夹具；修正配置只重跑分析，评论文件哈希不变，canary 在全 run 中零命中。

具体错误码、三次请求预算、兼容降级、Retry-After 与不重放边界见
[Provider 错误与恢复契约](PROVIDER_RECOVERY.md)。总结整合失败继续使用已完成批次，另给 warning。

## D：长请求体验

- 为分析阶段补充已用时、当前批次、重试次数与配置超时；保留已有 0–100 进度语义，不伪造进度增长。
- 明确连接、读取及整体任务超时的区别；停止操作继续可快速响应，不等待阻塞请求完成。
- 若需新增可选事件字段，同批更新类型和客户端契约；旧客户端缺少新字段时仍可工作。

验收：慢响应、断连、限流和取消夹具；桌面可区分等待/重试/失败，超时后能复用同一 run。UI 改动须另做真实窗口验收。

本批通过现有 progress 文本提供信息，不新增客户端字段或修改 UI 文件。连接/读取超时
保持原值各 90 秒，不增加整体任务 deadline。具体线程、计时和兼容边界见
[长请求进度契约](ANALYSIS_PROGRESS.md)。

## E：真实 MCP 传输与 Windows 编码

- 启动真实 `python -m backend.agent mcp` 子进程，经 SDK stdio 客户端完成初始化、7 工具发现、爬取、分析、状态查询和取消。
- 重启子进程后复用已落盘 run；验证子进程显式环境参数、桌面双文件配置和字段覆盖。
- progress/stage/summary 中文经 stdio 往返正确，stdout 只有协议帧，stderr 和产物 UTF-8 正常。
- 可选 live smoke 的视频、页数、样本量由环境提供；默认不联网、不消费模型额度。记录结果，不把第三方服务稳定性当作普通 PR 门禁。

验收：普通 PR 离线夹具稳定通过；真实网络报告单独注明时间、目标、用量边界和未验证项。

实现与隔离规则见 [stdio 验收契约](MCP_STDIO_VALIDATION.md)。可选 live 脚本默认跳过，
必须显式 `--live` 并从环境指定 BV/视频 URL、页数和抽样量；运行说明见 [MCP 文档](MCP.md)。

## F–H：Python 包与发布

F：增加 `pyproject.toml`，统一 `bilibili_crawler` 命名空间；旧入口保留薄兼容层。核心依赖与 MCP extra 分层；静态资源使用包资源 API，run/凭据/缓存脱离 checkout 路径。提供 `bilibili-crawler`、`bilibili-crawler-mcp` 稳定命令。版本仍由 Cargo.toml 派生。

本批具体约束见 [Python 包边界](PYTHON_PACKAGE_BOUNDARY.md)。安装包不写 site-packages/cwd；
源码 checkout 保留旧数据路径与 profile 发现，避免既有 run 失联。公开名称与多版本矩阵不由本批提前宣称完成。

G：构建 wheel/sdist 并执行 `twine check`；Python 3.10–3.13 全新环境只从产物安装，在无 checkout 的任意工作目录验证 help、doctor、列举、最小爬取与 MCP 握手。包内不得携带 Key、cookies、run、缓存、测试 fixture 或机器绝对路径。

完整门禁、复现命令与证据限制见 [Python 产物与干净安装验收](PYTHON_PACKAGE_VALIDATION.md)。
当前矩阵针对 Windows，每个版本分别从 wheel/sdist 创建新 venv，先验证基础安装，再增加 MCP extra。

H：先随 GitHub Release 附带包资产，TestPyPI 验证后再启用正式 PyPI，优先 Trusted Publishing。CI 校验版本、产物内容、安装 smoke 和哈希。公共包入口稳定后另行评估 `server.json` 与 MCP Registry。公开发布前确定包名、账户/权限与最终发布产物。

## 验证记录

- 分支：`codex/llm-profile-doctor`；从 `6ae33df` 开始。本批已通过 Standards / Spec 双线 review，随此变更提交；未打标签、未发版。
- 新增 28 项测试：profile 18 项、doctor 9 项、真实 service/HTTP 回显 1 项。旧 resolver 对新 profile 用例出现 15 个断言失败；修复后通过。
- HTTP 回显测试先发现公开 summary 泄露 canary，补上 summary 脱敏后通过。真实请求捕获确认地址、Authorization、模型与 profile/环境覆盖一致；第二次分析只复用评论，评论文件 SHA-256 不变；JSON、Markdown、manifest、archive 与返回摘要均无测试 Key。
- 最终无 MCP 环境（仓库 `.venv`，CPython 3.13.0）：`python -X utf8 -m unittest discover -s tests -q` 运行 232 项，231 通过、MCP 模块 1 项按预期跳过，退出码 0。
- 最终 MCP 环境（本机 Python，CPython 3.13.0，已确认 MCP 2.1.0）：同一全量命令运行 257 项，全通过，退出码 0。没有修改这两个环境的已安装依赖。
- 桌面 `npm run test:unit`：11/11 通过（含真实 SidecarClient 子进程）；`npm run typecheck` 通过；`git diff --check` 通过。
- 本机完整日志在 `.runlogs/p0-review-{no-mcp,mcp,desktop}.log`（忽略文件，不纳入提交）。
- 未调用外部付费模型，未跑新的 Tauri 真机验收或安装包构建；本批未修改 UI、Rust 或桌面请求配置语义。完整 MCP stdio 子进程验收仍属于 E 批，不能用本批 CLI doctor 子进程和进程内 MCP 测试代替。
- A 已提交推送为 `7658ace`。B 在独立分支 `codex/analysis-attempt-state` 继续实现；后续 C 的错误分类按已冻结的分析尝试契约接入。

### A 批 review 结论

- Standards：发现 1 项 P2，无法编码为 HTTP 请求头的 Key 导致 doctor 崩溃；已在 resolver 校验并加诊断兜底，真 CLI 回归通过，独立复核关闭。
- Spec：发现 1 项 P2，纯空白环境变量中的 tab/newline 没有回退；已按字段跳过纯空白并保留非空控制字符校验，独立复核关闭。
- 两轴均无未解决发现；不等于外部 provider 或新的安装包已经验收。

### B 批验证与 review 结论

- 分支 `codex/analysis-attempt-state`，基线为 A 的 `7658ace`；不更改版本号、不合并 main、不构建安装包。
- 新增 18 项分析尝试回归：取消窗口、失败/重试、旧格式按需升级、直接保存兼容、staging/manifest/兼容副本故障、单一 manifest 快照、真实子进程中断恢复、含 PNG 的 run 迁移、路径越界与缺失版本。
- 新增 1 项 MCP SDK 客户端回归，区分本次尝试 cancelled 与有效 run completed，并验证重新创建服务后仍能查询旧报告；轮询指引同步改为 task_id。MCP 专项 27/27 通过。
- 无 MCP 环境全量 250 项（249 通过、MCP 模块 1 项按预期跳过）；MCP 2.1.0 环境全量 276/276；退出码均为 0。
- 桌面单元/真实 SidecarClient 子进程契约 11/11，TypeScript 检查和 `git diff --check` 通过。已有真实 HTTP canary 回显回归覆盖新版本目录、manifest、根目录副本及 archive，评论哈希保持不变。
- Standards：审查发现的旧取消产物误提升、旧签名直接保存不可见、直接保存已发布后被兼容副本异常判失败均已修复，独立复核关闭。
- Spec：审查发现的直接保存可见性、快照两次读取混合版本、兼容副本 warning 未持久化、直接保存副本失败语义均已修复，独立复核关闭。
- 两轴无未解决发现；日志在 `.runlogs/b-review-{no-mcp,mcp,desktop}.log`，不纳入提交。故障注入产生的磁盘/锁错误日志为预期回归场景。
- 本批不支持多进程同时写同一 run；根目录兼容副本不是原子多文件读取入口，使用 artifacts 版本路径。未做真实外部付费模型调用、新安装包验收或 E 批完整 MCP stdio 子进程验收。
- 下一批 C：provider 错误分类与复用原 run 的恢复提示；其后才处理 D 的耗时/超时体验。

### C 批验证与 review 结论

- 分支 `codex/provider-error-recovery`，基线 B 的 `326bf58`。新增稳定 provider 错误码、按错误类型限制重试、CLI/MCP 原 run 恢复提示；不改 MCP/RPC 字段、不改版本号或 UI。
- 新增 16 项 provider 回归（含子场景），另新增 1 项 MCP 恢复回归。首轮有效基线回归出现 20 个断言失败、5 个错误，修复后全部通过。
- 真实 loopback HTTP 验证永久错误只发一次、明确格式拒绝才降级、三次总预算、Retry-After、超时、重定向与取消后不重发。真实 CLI 子进程验证失败退出 1、修正后同一 run 成功退出 0；MCP SDK 验证仅爬取一次、失败与成功复用同一 run、评论哈希不变。
- 总结整合失败保留已完成批次，安全 warning 同步至结果、任务与 manifest。错误正文、原始异常及 JSON 预览不透传；HTTP 回显 canary 及既有完整 run 脱敏回归通过。
- 最终无 MCP 全量：266 项（265 通过、MCP 模块 1 项预期跳过），退出码 0；MCP 2.1.0 全量：293/293，退出码 0。provider 专项 16/16、MCP 专项 28/28。
- 桌面单元/真实 SidecarClient 子进程契约 11/11、TypeScript 和 `git diff --check` 通过。日志位于 `.runlogs/c-review-{no-mcp,mcp,desktop}.log`，不纳入提交。
- Standards：1 项 P2，真实响应体超时被 requests 包装为 ConnectionError 后误归网络错误；已按具体异常类型链修复，真实 HTTP 超时回归与独立复核通过。
- Spec：2 项 P2，上述真实超时分类，以及明确其他参数错误被宽泛文本误判为格式拒绝；已让结构化参数优先，并限定明确的字段拒绝措辞，两项独立复核关闭。
- 两轴无未解决发现。没有调用真实付费 provider、没有关闭 TLS 校验、未构建安装包；MCP 验证仍为 SDK 内存传输，E 批完整 stdio 子进程验收未在此批完成。
- 下一批 D：长请求耗时、批次/重试提示与超时体验；依赖现有安全重试和取消契约。

### D 批验证与 review 结论

- 分支 `codex/analysis-progress-details`，基线为 C 已推送的 `67b668e`。沿用原客户端消息/字段，显示单调时钟耗时、批次、请求次数、退避与实际超时，不修改 UI 文件。
- 新增 5 项 Python 进度回归：真实慢 HTTP 的每秒等待提示和固定百分比、批次/总结重试消息、取消后无迟到进度、观察者失败停止重试、真实超时后原 run 重试与评论哈希不变。
- 新增 2 项桌面回归：reducer 对消息刷新保持原百分比；真实 SidecarClient + Python 子进程 + loopback HTTP 503→200，收到等待/退避/第二次请求消息，始终保持既有分析百分比且不泄露 canary。
- 最终无 MCP 全量 271 项（270 通过、MCP 模块 1 项预期跳过），MCP 2.1.0 全量 298/298，退出码均为 0。桌面 13/13、TypeScript 与 `git diff --check` 通过。
- Standards：0 项发现；Spec：0 项发现；两轴独立复核关闭。完整日志 `.runlogs/d-review-{no-mcp,mcp,desktop}.log` 不纳入提交。
- 超时仍为连接 90 秒/读取 90 秒，不代表总体 deadline；没有引入任务总超时或新的配置入口。私有请求方法增加可选 request_progress，公开 analyze 和客户端协议保持兼容。
- 未调用外部付费模型，未构建安装包、未做新的窗口视觉验收。桌面证据为真实协议通路验收，不替代安装包或 E 批 MCP stdio 验收。
- 下一批 E：真实 MCP stdio 子进程、Windows 编码、重启复用与可选 live smoke；之后进入 F–H 包边界与发布门禁。

### E 批验证与 review 结论

- 分支 `codex/mcp-stdio-validation`，基线为 D 的 `e672e49`。只新增验收夹具、可选 smoke 脚本和文档，不修改生产服务、版本号、依赖或 UI。
- 新增 4 项真实 SDK stdio 子进程测试：legacy/auto 握手及 7 工具发现；中文路径、GBK 环境、profile 与环境覆盖、实际进程重启复用；真实 HTTP 鉴权失败、取消与原 run 恢复；退出尾字节污染负例（垃圾和无换行 Key）。每个子进程关闭后退出码为 0。
- 新增 2 项网络隔离回归与 2 项 smoke CLI 回归。fixture 在解析/连接/UDP 等入口限制 literal loopback，并禁止反向解析；合成审计事件不触发实际外网。默认 smoke 即使有 live 环境参数也不启动服务器、不创建 run、不加载 MCP；无效 live 参数在启动前拒绝。
- 真正 HTTP 请求核对地址、Authorization 与模型字段；真实 stdout 原始字节、stderr、中文报告与完整 run 均检查 canary。修改 profile/环境后只重新分析原 run，评论哈希不变；取消新尝试保留旧有效报告。
- 最终无 MCP 全量 276 项（274 通过、两个 MCP 模块按预期跳过）；MCP 2.1.0 全量 306/306，退出码均为 0。桌面 13/13、TypeScript 与 `git diff --check` 通过。本机均为 CPython 3.13.0；没有据此宣称 3.10–3.13 安装矩阵已经完成。
- Standards：2 项 P2（DNS/UDP 隔离缺口、stdout 关闭残尾漏检）均修复并独立复核关闭。Spec：1 项 P2（stdout 无换行退出残尾漏检）已用真实 atexit 输出复现、修复并独立复核关闭。两轴无未解决发现。
- 完整日志 `.runlogs/e-review-{no-mcp,mcp,desktop}.log` 不纳入提交。没有执行 live B 站/付费模型调用、没有构建安装包或 wheel、未做新的窗口视觉验收。
- 下一批 F：冻结 Python 包命名空间、资源与用户数据路径的兼容边界，再实现可安装 CLI/MCP 入口；G 单独执行干净安装与产物内容审计，H 才进入公开发布。

### E 批追加 review 修复（基线 `2fbb2fa`）

- 上述为 E 原交付记录；用户要求追加 review 后发现 3 项 P2，本轮修复仍在 `codex/mcp-stdio-validation`，未推进 F。
- Standards 2 项：stdout 从 JSON/版本字段检查升级为完整 SDK JSON-RPC schema 校验；live 命令在整个 asyncio 传输及清理期间隔离父 SDK 日志，结束后恢复原日志设置。带版本字段的非协议 JSON 与真实 SDK canary 解析错误负例先失败、修复后通过。
- Spec 1 项：每次成功响应立即记下白名单元数据。停止、轮询、关闭传输三种异常均保留已知 run_id/task_id、最近状态、计数和产物名称；不保留原始错误、摘要或产物路径。正常完成仍返回成功，不额外停止任务。
- 另关闭迟到响应的验收局限：测试只观察真实 HTTP，不替换返回值；等待子进程读完响应体且请求线程结束后，在仍存活的 MCP 进程核对本次尝试完全保持取消终态、旧报告不变。独立复核额外延迟响应 1 秒也通过。
- 新增 2 项 smoke 异常回归（含正常完成、停止/查询/关闭异常子场景），扩展真实 stdio 负例。修复前 smoke 回归出现 1 个失败、3 个错误，协议残尾回归另有 1 个失败；修复后两轴独立复核均无未解决问题。
- 最终 MCP 2.1.0 全量 308/308；无 MCP 全量 277 项（274 通过、3 个 MCP 模块预期跳过）；桌面 13/13、TypeScript、`git diff --check` 通过。四个改动 Python 文件通过 3.10 语法解析，但运行验证仍是 CPython 3.13.0，不代表多版本安装矩阵完成。
- 完整日志 `.runlogs/e-review-fix-{mcp,no-mcp,desktop}.log`，修复前失败证据 `.runlogs/e-fix-red-{smoke,schema}.log` 均不纳入提交。未执行真实外网 live smoke、未消费模型额度、未发布安装包或 Python 包。

### F 批验证与 review 结论

- 分支 `codex/python-package-boundary`，基线为 E 追加修复的 `86f0eae`。运行实现迁入 `bilibili_crawler`，旧源码入口保留共享模块的薄兼容层；新增可安装 CLI/MCP 命令、包内词表与平台用户目录。不改 Cargo 版本、桌面锁定依赖或客户端协议。
- 新增 7 项包边界测试。MCP 2.1.0 全量 315/315；无 MCP 全量 284 项（281 通过、3 个 MCP 模块预期跳过）；桌面真实 SidecarClient/单元测试 13/13、TypeScript 通过。最后的帮助/恢复命令修正后，provider 恢复专项 16/16 与两个环境的安装 smoke 再次通过。
- wheel 从当前元数据构建，版本为 3.3.0；临时安装目录和无关 cwd 下，CLI/module help、只读 doctor、默认用户 run 目录、包资源与旧通用模块隔离均通过。阻断可选依赖后仍走完真实服务层的爬取、分析和报告落盘；合成 Key 在公开摘要与完整 run 中零命中。两个 MCP 入口经 SDK stdio 握手发现 7 个工具；无 SDK 时返回明确安装提示和退出码 2。
- Standards：1 项 P2，Pillow 误列可选依赖而持久化层必需；已补入核心依赖，旧 wheel 被新增安装检查拒绝，重建后通过。Spec：1 项 P3，安装帮助仍展示未安装的旧模块；帮助及同类恢复指引均改为新入口。两轴独立复核关闭，无未解决发现。
- 独立 Spec 安装布局验收覆盖用户 profile、字段覆盖、显式缺失不回退、Windows 桌面 profile 回退和 doctor 零写入；Linux/macOS 为路径逻辑验证，不代表对应系统实机验收。
- 本机 PyInstaller onedir sidecar 构建及启动通过：ready、session.status、32 项包内词表、用户数据目录和安装目录零写入均核对。工具链为本机 CPython 3.13.0/PyInstaller 6.17.0，不是正式桌面发布工具链或安装器验收；随后修改的 CLI 帮助/恢复文字不涉及该 sidecar 路径。
- 全量日志 `.runlogs/f-review-{mcp,no-mcp,desktop}.log`，安装日志 `.runlogs/f-install-{mcp,no-mcp}.log`，冻结 smoke `.runlogs/f-frozen-smoke.log`，依赖缺失失败证据 `.runlogs/f-pillow-regression-red.log` 均不纳入提交。
- 安装 smoke 复用现有解释器依赖，运行验证仍为 CPython 3.13.0；3.10 语法解析不能替代多版本运行。本批未执行外网 live smoke、未消费模型额度、未合并 main、未发布 Python 包或安装器。
- 下一批 G：wheel/sdist 内容审计、`twine check` 与 Python 3.10–3.13 全新环境产物安装矩阵；H 的公开包名、发布权限和发布流程继续待定。

### G 批验证与 review 结论

- 分支 `codex/python-package-validation`，基线 F 的 `3614a34`。仅修改验收脚本、测试与文档，没有更改生产实现、依赖声明、Cargo 版本或桌面协议。
- build 1.6.0 在隔离构建环境先生成 sdist、再由 sdist 构建 wheel；twine 7.0.0 对两者执行 `check --strict` 通过。静态审计确认 30 个运行文件逐字节一致，wheel 36 文件、sdist 44 文件，完整白名单、声明依赖/extra、入口、license、RECORD 和常见敏感内容扫描均通过。
- 新增 6 项归档回归（含多组子场景）：有效归档、混入敏感/未列明文件、Key/Cookie/机器路径、依赖/版本、RECORD/运行内容漂移、穿越/重复/链接/特殊类型/超限。Standards 的 2 项 P2（依赖子集假绿、普通 Cookie 漏检）及 Spec 的 3 项 P2（前两项与 ZIP 特殊类型漏检）均已修复并独立复核关闭。
- 全量 MCP 2.1.0 环境 321/321；无 MCP 环境 290 项（287 通过、3 个模块预期跳过）；桌面单元/真实 SidecarClient 13/13、TypeScript 通过。F 原 wheel smoke 的有/无 MCP 两种模式继续通过，不被误标为干净安装矩阵。
- 两轮 `--jobs 4` 矩阵分别完成 15/16、14/16 个阶段，但均在 Python 3.10/sdist 的首次分析目录发布遇到 WinError 5（`stage.rename` 拒绝访问），报告保持失败。原环境随后单独复跑 3 次均通过；尚未定位根因，不能认定为非产品问题或并发可靠性通过。已改为默认串行；并发仍可显式开启。
- 并发失败记录 `.runlogs/g-matrix/matrix-32yi47c3/`、`matrix-u52z2s10/`，单独复跑 `.runlogs/g-310-repeat-{1,2,3}.log`，全量 `.runlogs/g-review-{mcp,no-mcp,desktop}.log` 保留在本机，不纳入提交。
- 串行完整矩阵通过：CPython 3.10.20、3.11.16、3.12.14、3.13.15，各自 wheel/sdist 基础安装及 MCP extra 均通过，共 8 个新 venv / 16 阶段。报告 `.runlogs/g-matrix/matrix-4pde6fo3/report.json` 为 `ok: true`、错误列表为空；末次哈希核对与开始时一致。基础环境均无 MCP/jieba/wordcloud/qrcode，所有阶段通过 `pip check`、真实 CLI/HTTP 爬取分析与落盘；8 个 MCP 阶段均验证两个 stdio 入口。
- 最终表格与产物哈希见 [G 验收记录](PYTHON_PACKAGE_VALIDATION.md)。仅此 Windows 串行矩阵通过，不将单独复跑、语法解析或其他 OS 路径测试扩大为额外兼容承诺。H 尚未开始，公开发布前仍须评估未定位的并发 I/O 风险。

### A–G 累计全面 review 追加修复

- 累计 review 发现 2 项 P2：无 manifest 的原 `RunStore.save_analysis()` 调用可写但不能再读；损坏的旧 `analysis.json` 会在 processor 调用前反复抛错，完整评论也无法用于重分析。
- 新增 2 项公开接口回归，均先复现失败再修复。无 manifest 时恢复读取根目录兼容产物，但已有且损坏的 manifest 仍保持 fail-closed；损坏旧报告不再晋升为 legacy 当前版本，原文件保留至新分析正常发布，重分析可以完成。
- 最终 MCP 2.1.0 环境 323/323；无 MCP 环境 292 项（289 通过、3 个模块预期跳过）；分析尝试专项 20/20；桌面 13/13、TypeScript 和 `git diff --check` 通过。
- 生产运行文件变化后重新从 sdist 构建 wheel，`twine check --strict` 和 30 个运行文件的产物审计通过。新 wheel/sdist 哈希及报告已更新至 [G 验收记录](PYTHON_PACKAGE_VALIDATION.md)。
- Windows 串行矩阵重新创建 8 个 venv，CPython 3.10.20、3.11.16、3.12.14、3.13.15 的 wheel/sdist 基础与 MCP extra 共 16/16 阶段通过，报告 `.runlogs/fix-matrix/matrix-o02f4wde/report.json`。本轮未运行并发矩阵，不关闭既有 WinError 5 风险。
