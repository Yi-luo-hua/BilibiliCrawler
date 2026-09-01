# BilibiliCrawler v3.4.0

v3.4.0 将桌面端、命令行与 MCP 的后端统一到可安装的 `bilibili-crawler` Python 包，并补齐
长分析任务的恢复、诊断与发布链路。

## 新功能

- 新增 `bilibili-crawler` 与 `bilibili-crawler-mcp` 稳定命令，支持 Python 3.10–3.13。
- 新增只读 `doctor` 诊断，显示配置来源、有效 provider/model、运行目录和 MCP 状态；只有
  显式指定联网检查时才访问 provider。
- 分离 run 与分析 attempt。重新分析失败或取消时保留上一份完整报告，成功后原子切换当前结果。
- 为鉴权、模型、端点、网络、超时、限流与解析失败提供明确分类，并允许直接复用已爬取的 run。
- 长分析显示已用时间、批次和重试信息；真实 MCP stdio 支持中文与 Windows 编码场景。

## Python 包

- GitHub Release 提供 wheel、sdist、`SHA256SUMS` 和 `python-package-manifest.json`。
- wheel 与 sdist 在 Windows Python 3.10–3.13、Ubuntu 3.13 和 macOS 3.13 的干净环境验证。
- TestPyPI 与 PyPI 通过 GitHub OIDC Trusted Publishing 发布，不保存长期上传令牌。
- 发布门禁绑定注解标签、Cargo/包版本、`main` 提交和产物 SHA-256；TestPyPI 与 PyPI 复用
  GitHub Release 上的同一份不可变产物。

## 安全与兼容性

- provider、model 与 API Key 按同一 profile 解析，避免把凭据发送到错误端点。
- CLI、MCP、公开摘要和持久化报告继续执行敏感信息脱敏。
- 旧源码入口保留为兼容层，既有桌面 run 与配置发现顺序保持兼容。

## 安装

桌面用户从本 Release 下载 `BilibiliCrawler-Setup-3.4.0-x64.exe` 并核对同页 SHA-256。

Python 用户可在正式发布后运行：

```bash
python -m pip install "bilibili-crawler[mcp]==3.4.0"
```
