# v3.3.0 之后的实施计划

更新：2026-08-31。基线：已发布 v3.3.0 / `main` 的 `6ae33df`。
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
| D | P1 | 耗时、超时、重试提示 | C | 待开始 |
| E | P1 | 真实 MCP stdio、Windows 编码与可选 live smoke | A–D | 待开始 |
| F | P1 | 命名空间、资源路径、CLI/MCP 可安装包边界 | A–C；E 提供验收基线 | 待开始 |
| G | P2 | wheel/sdist 干净安装与内容审计 | F | 待开始 |
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

## E：真实 MCP 传输与 Windows 编码

- 启动真实 `python -m backend.agent mcp` 子进程，经 SDK stdio 客户端完成初始化、7 工具发现、爬取、分析、状态查询和取消。
- 重启子进程后复用已落盘 run；验证子进程显式环境参数、桌面双文件配置和字段覆盖。
- progress/stage/summary 中文经 stdio 往返正确，stdout 只有协议帧，stderr 和产物 UTF-8 正常。
- 可选 live smoke 的视频、页数、样本量由环境提供；默认不联网、不消费模型额度。记录结果，不把第三方服务稳定性当作普通 PR 门禁。

验收：普通 PR 离线夹具稳定通过；真实网络报告单独注明时间、目标、用量边界和未验证项。

## F–H：Python 包与发布

F：增加 `pyproject.toml`，统一 `bilibili_crawler` 命名空间；旧入口保留薄兼容层。核心依赖与 MCP extra 分层；静态资源使用包资源 API，run/凭据/缓存脱离 checkout 路径。提供 `bilibili-crawler`、`bilibili-crawler-mcp` 稳定命令。版本仍由 Cargo.toml 派生。

G：构建 wheel/sdist 并执行 `twine check`；Python 3.10–3.13 全新环境只从产物安装，在无 checkout 的任意工作目录验证 help、doctor、列举、最小爬取与 MCP 握手。包内不得携带 Key、cookies、run、缓存、测试 fixture 或机器绝对路径。

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
