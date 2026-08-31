# Provider 错误与原 run 恢复契约

C 批，基线 `326bf58`。不更改 MCP/RPC 字段、超时配置或 UI，不发布新版本。

- 分析错误使用稳定 error_code：`LLM_AUTH`、`LLM_MODEL`、`LLM_ENDPOINT`、`LLM_NETWORK`、`LLM_TLS`、`LLM_TIMEOUT`、`LLM_RATE_LIMIT`、`LLM_UNAVAILABLE`、`LLM_RESPONSE_INVALID`、`LLM_REQUEST_INVALID`；非 provider 分析错误保留 `ANALYSIS_FAILED`。
- 401/403 优先归为鉴权；仅结构化 error.code/type 或 param 明确指向模型时归为模型配置。普通 404 属于端点/路由待核对，不断言模型不存在。其余 400/422 是请求配置错误。
- 仅 400/422 且明确拒绝 response_format 时移除该字段重发一次；不得对所有 400/404/422 盲目重发。
- 每个聊天请求最多发送三次（包括格式降级）。429（非额度耗尽）、500/502/503/504、ConnectTimeout 可重试；默认退避 1、2 秒。有效 Retry-After（秒数或 HTTP 日期）优先；超过 10 秒时交由用户稍后重试，不提前发送。
- 鉴权、模型、端点、TLS、无效配置、解析失败、额度耗尽不自动重试。读取超时/普通连接中断可能已经消费额度，不自动重放；提供人工重试指引。请求取消时等待立即结束，迟到响应不得发起下一次请求。
- 不跟随 provider 重定向。错误只输出固定安全说明与状态码，不透传原响应正文、异常文本、JSON 预览、URL 或凭据；成功结果仍走已有脱敏边界。
- 批次与总结请求共用分类。保留既有“总结整合失败时使用已完成批次总结”的降级行为，并在结果/任务 warnings 记录安全错误码和提示，不丢弃已付费批次。
- 爬取已完成而分析失败：保留评论文件与 run_id；CLI/MCP 提示按错误修正配置或等待，再调用 analyze-run/analyze_run 复用原 run，不默认重新爬取。已有有效报告时遵循 B 的尝试与有效 run 分离语义。
- 测试使用本地 HTTP provider、传输异常及取消夹具；检查真实调用次数、原 run 评论哈希、错误码在 manifest/CLI/MCP 的一致性，以及错误回显/成功产物的 canary 零泄露。外部付费调用和完整 MCP stdio 验收不属于本批。
