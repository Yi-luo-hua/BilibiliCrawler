# Provider 错误与原 run 恢复契约

C 批，基线 `326bf58`。不更改 MCP/RPC 字段、超时配置或 UI，不发布新版本。

- 分析错误使用稳定 error_code：`LLM_AUTH`、`LLM_MODEL`、`LLM_ENDPOINT`、`LLM_NETWORK`、`LLM_TLS`、`LLM_TIMEOUT`、`LLM_RATE_LIMIT`、`LLM_UNAVAILABLE`、`LLM_RESPONSE_INVALID`、`LLM_REQUEST_INVALID`；非 provider 分析错误保留 `ANALYSIS_FAILED`。
- 401/403 优先归为鉴权；仅结构化 error.code/type 或 param 明确指向模型时归为模型配置。普通 404 属于端点/路由待核对，不断言模型不存在。其余 400/422 是请求配置错误。
- 仅 400/422 且明确拒绝 response_format 时移除该字段重发一次；不得对所有 400/404/422 盲目重发。
- 仅 400/422 且 `error.param` 精确等于 `temperature` 时移除该字段重发一次。判据只看 `param`：它就是
  provider 自己指认的被拒字段，同行的 `code`/`type` 随模型系列变化，对"哪个字段出错"不再增加信息。
  自由文本、缺少 `param`、`param` 指向其他字段一律 fail closed，不删字段、不重发。两种降级各自
  只发生一次（字段移除后条件自然不再成立），共用同一个三次请求预算。
- 每个聊天请求最多发送三次（包括格式与采样参数降级）。429（非额度耗尽）、500/502/503/504、ConnectTimeout 可重试；默认退避 1、2 秒。有效 Retry-After（秒数或 HTTP 日期）优先；超过 10 秒时交由用户稍后重试，不提前发送。
- 鉴权、模型、端点、TLS、无效配置、解析失败、额度耗尽不自动重试。读取超时/普通连接中断可能已经消费额度，不自动重放；提供人工重试指引。请求取消时等待立即结束，迟到响应不得发起下一次请求。
- 不跟随 provider 重定向。错误只输出固定安全说明与状态码，不透传原响应正文、异常文本、JSON 预览、URL 或凭据；成功结果仍走已有脱敏边界。
- 400/422 的安全说明可附带 provider 自报的 `code`/`type`、`param` 与 `status`，用于指出被拒的是什么，
  而不是复述远端措辞。三者都按同一条规则过滤：必须是字符串且形如裸标识符
  （`^[a-z0-9][a-z0-9_.:-]{0,39}$`，ASCII、无空白），否则整体省略，不截断、不转义后回显。
  数值 `code` 只是重复 HTTP 状态码，不输出；`status` 与 `code` 相同时不重复输出。

## 已观察到的上游错误形状

- OpenAI 兼容服务用 `code`/`type` 加 `param` 指明被拒字段，`response_format` 的精确降级依赖它。
- OpenAI 推理模型（o1/o3/gpt-5 系列）拒绝采样参数时有两种正文，只在 `param` 上一致：

  ```json
  {"error":{"message":"Unsupported parameter: 'temperature' is not supported with this model.",
            "type":"invalid_request_error","param":"temperature","code":null}}
  {"error":{"message":"Unsupported value: 'temperature' does not support 0.2 with this model. Only the default (1) value is supported.",
            "type":"invalid_request_error","param":"temperature","code":"unsupported_value"}}
  ```

  第一种更常见，`code` 为 `null`、`type` 是通用的 `invalid_request_error`。若要求 code 属
  unsupported 类才降级，就会漏掉它——所以判据只看 `param`。本仓库固定发送 `temperature`
  0.2 / 0.18，指向这类模型时若不降级就是硬失败。
- Google 系（经 CLIProxyAPI 的 Antigravity 通道，上游 `daily-cloudcode-pa.googleapis.com`）把 HTTP
  状态码放进 `error.code`，真正可操作的信息在 `error.status` 枚举里，`message` 是自由文本。
  2026-09-02 观察到的 10 次分析失败全部是 `status: FAILED_PRECONDITION`，属于上游对调用方所在区域的
  限制，与请求参数无关：`temperature` 与 `response_format` 原样送达且从未被评估。
  这类失败不能靠删字段重发绕过，本仓库也无法修复；分类保持 fail closed，只把 `status` 透出来供排查。
  **`temperature` 降级不针对也不解决这个问题**：该正文没有 `param`，`code` 是数值 400，触发条件
  不成立；即使成立，请求在参数被读取之前就已经被拒。上游侧的处理是让 CLIProxyAPI 通过受支持区域的
  出口访问（按认证配置 proxy-url），与本仓库无关。不要因为再次看到 Antigravity 400 就放宽降级条件。
- 批次与总结请求共用分类。保留既有“总结整合失败时使用已完成批次总结”的降级行为，并在结果/任务 warnings 记录安全错误码和提示，不丢弃已付费批次。
- 爬取已完成而分析失败：保留评论文件与 run_id；CLI/MCP 提示按错误修正配置或等待，再调用 analyze-run/analyze_run 复用原 run，不默认重新爬取。已有有效报告时遵循 B 的尝试与有效 run 分离语义。
- 测试使用本地 HTTP provider、传输异常及取消夹具；检查真实调用次数、原 run 评论哈希、错误码在 manifest/CLI/MCP 的一致性，以及错误回显/成功产物的 canary 零泄露。外部付费调用和完整 MCP stdio 验收不属于本批。
