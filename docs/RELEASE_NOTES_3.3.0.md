# BilibiliCrawler v3.3.0

本版本完成桌面评论爬取与评论分析向共享 `AgentService` 的迁移，并强化持久化 run、MCP 管理能力与敏感信息边界。

## 主要变化

- 桌面评论爬取和 `source == "comments"` 的首次分析改用共享服务层，保持原有 RPC、事件与空结果契约。
- 新增跨进程 SidecarClient 回归测试，覆盖完成、取消、请求关联与无迟到终态。
- MCP 扩展为 7 个工具，新增持久化 run 的列举与删除。
- 分析 JSON、Markdown、词云与历史归档采用整组 staging / 原子提交，并补充来源、耗时与 schema 元数据。
- CSV 导出增加公式注入防护；损坏或超限词云会降级为 warning，不生成失效链接。
- `analysis.json`、Markdown 与归档中的已注册凭据会递归脱敏，包含嵌套配置回显。

## 安装与升级

- 下载 `BilibiliCrawler-Setup-3.3.0-x64.exe`，并用同页 `.sha256` 文件核对 SHA-256。
- 安装包面向 Windows 10/11 x64，采用 currentUser 安装，可直接覆盖升级 v3.2.0。
- 默认升级和卸载会保留安装目录中的 `user-data` 与 `analysis-runs`，请按需备份或手工清理。

## MCP / CLI

v3.3.0 的 MCP 与 CLI 仍通过源码环境安装，详见 `docs/MCP.md`。wheel / sdist、PyPI 与 MCP Registry 已进入后续路线，不属于本次发布产物。

## 已知限制

- Windows 安装包尚未进行代码签名，首次运行时可能出现 SmartScreen 提示。
- 本版本只提供 Windows x64 NSIS 安装包。
- 在已有完整报告的 run 上重新分析并取消时，旧报告仍会保留，但该 run 的状态会显示为 `cancelled`；后续版本将把 run 状态与单次分析尝试状态拆分。
