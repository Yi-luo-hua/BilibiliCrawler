# MCP stdio 验收契约

E 批，基线 `e672e49`。不新增工具，不发布安装包或 Python 包。

- SDK stdio 客户端实际启动 `python -m backend.agent mcp`；覆盖初始化、7 工具发现、爬取、分析、状态、停止、列举和删除测试 run。
- 离线夹具注入假爬虫；真实 CLI/MCP/AgentService/RunStore/配置 resolver/LLM HTTP 处理器均不替换。取消验收额外观察真实 Session.send，在响应体已读取且请求线程结束后原子写入测试标记，不替换响应。测试专用 sitecustomize 经子进程显式 PYTHONPATH 和开关启用，生产代码不含测试入口。子进程网络只允许 loopback，不能读取真实用户凭据或修改真实 run。
- 子进程显式运行目录和 credentials/ui 双文件配置，包含中文路径；验证环境单字段覆盖不丢失其余 profile 字段。Key 全为测试 canary。
- 强制 PYTHONIOENCODING=gbk、PYTHONUTF8=0 验证服务端协议与 stderr 自行使用 UTF-8；在原始 receive 层记录全部 stdout 字节（含退出 drain 和未换行残尾），整体严格解码，每行通过 SDK JSON-RPC schema 校验且以换行结束，不能混入日志。退出时输出无换行垃圾、canary、或仅带 jsonrpc 版本字段的非协议 JSON，均必须被验收器拒绝。
- 验证中文 progress/stage/summary、manifest/报告，完整 run 与 stdout/stderr 无 canary。SDK legacy 初始化和默认 auto 协商均应可用。
- 真正关闭第一个进程、启动第二个进程，以 run_id 查询并重分析旧 run，评论哈希不变；取消新尝试不破坏有效报告。退出后没有残留被测进程。
- provider 错误通过真实 stdio 输出稳定错误码与同 run 恢复提示；延迟响应下查询/停止可及时响应。取消后先放行响应，等待子进程内的接收及请求线程结束标记，再通过仍存活的 MCP 进程核对本次尝试保持取消终态、旧有效报告不变，之后才能关闭进程。
- 默认 unittest 仅用 loopback，不访问 B 站或付费模型。未安装 MCP 时该模块跳过。可选 live smoke 单独脚本显式 --live 开启，目标、页数、样本量来自环境；默认只说明跳过且不读取凭据/联网/创建 run。live 成败不作为普通离线回归门禁。
- live 记录时间、参数边界、run_id、状态与有限元数据，不能记录凭据或完整评论；没有实际执行 live 时不得宣称外网/模型兼容性已验证。
- live 每次收到响应立即保存白名单元数据；停止、轮询或关闭传输失败仍保留已知 run_id/task_id、最近状态、计数及产物名称，失败只额外输出稳定错误码和异常类型。父进程日志在整个 asyncio 传输及清理期间禁用并于退出后恢复，子进程 stderr 单独隔离；异常协议含 canary 的真实 SDK 负例须验证 stdout/stderr 均无泄露。
