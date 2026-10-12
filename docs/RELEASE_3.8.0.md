# v3.8.0 发布记录

> 状态：**2026-10-12 已公开发布至 GitHub Release**。发布说明见 [RELEASE_NOTES_3.8.0.md](RELEASE_NOTES_3.8.0.md)，下载见 [GitHub Release v3.8.0](https://github.com/Yi-luo-hua/BilibiliCrawler/releases/tag/v3.8.0)。

## 范围与产物

- 基线 `v3.7.0`，包含 PR #59（合并提交 `1b21d3d`）及本版版本、发布文档更新。
- 桌面、CLI、MCP 和 Python 包统一由 `desktop/src-tauri/Cargo.toml` 派生版本 `3.8.0`。
- GitHub Release：Windows x64 安装包、安装包 SHA-256、`installer-payload-manifest.json`、wheel、sdist、`SHA256SUMS`、`python-package-manifest.json`。
- 从干净工作树和隔离 CPython 3.13.15 x64 环境构建 Windows 安装包；Python 资产由现有发布工作流从 annotated tag 构建并审计。

## 发布门禁

| 检查 | 结果 |
|---|---|
| PR #59 功能复核 | Python 438 项、前端 37 项、构建和 7 项 CI 通过；Edge 在 1440×1440、390×844 验证内部点击、按钮/Esc/遮罩关闭、重新打开和焦点恢复。此记录针对 PR 修复构建。 |
| v3.8.0 版本与自动化 | Python 438/438、前端 37/37、Rust release 模式锁定测试 7/7；生产前端及 Windows 构建通过。依赖审计发现的 source-map-js 高危问题已通过锁定 1.2.2 修复，复查无已知漏洞。 |
| Windows 构建、版本与上版 payload 比较 | 隔离 CPython 3.13.15 x64 构建成功，7-Zip 完整性及解包校验通过；主程序 ProductVersion 为 3.8.0，1299 个包内后端文件逐一通过大小/哈希检查。对比官方 3.7.0 清单：0 移除、0 新增、3 内容变化。包内冻结 sidecar 能发送 ready 并响应 session.status。 |
| 候选提交 CI | [Python package gate 38211708152](https://github.com/Yi-luo-hua/BilibiliCrawler/actions/runs/38211708152) 7/7 项通过。 |
| 标签、GitHub 资产与反向下载校验 | annotated tag v3.8.0 指向 e0c8415，属于 main 历史。七个资产均为 uploaded；从草稿下载的文件哈希均匹配本地 Windows 构建或标签工作流原始产物，以及 GitHub 的资产 digest。 |
| tagged Python 包审计与干净安装矩阵 | [发布工作流 38212318307](https://github.com/Yi-luo-hua/BilibiliCrawler/actions/runs/38212318307) 成功；Windows Python 3.10–3.13、Linux/macOS Python 3.13 的 wheel/sdist 基础和 MCP 安装验证通过。下载后本地再次通过 31 个运行文件的源码绑定审计、manifest 与 SHA256SUMS 验证。 |
| 公开状态与客户端更新发现 | GitHub releases/latest 返回 v3.8.0、draft=false、prerelease=false；使用实际客户端 parseRelease/isNewerVersion 处理该响应，可从 3.7.0 识别更新及正确的 x64 安装包地址。 |

## 发布证据

- 构建与标签提交：`e0c84151cbc70effea0b29aa5d6b655554e3eaaa`。本记录的完成状态在发布后以文档提交补齐，标签继续保持在实际构建提交。
- Windows 安装包：`BilibiliCrawler-Setup-3.8.0-x64.exe`，53,640,060 字节，SHA-256 `55b64689c4f77aabd3ee0751f2db093cd8a09bbca1c6685c7138bf10762c1fdd`。解包主程序与构建输出仅有 Tauri 的三字节 UNK/NSS bundle type 标记差异。
- Python wheel：`bilibili_crawler-3.8.0-py3-none-any.whl`，121,345 字节，SHA-256 `38a76280c822344f8ae8918aec2d5e76d9858da4eef8fc5050d58af3a4acbd3b`。
- Python sdist：`bilibili_crawler-3.8.0.tar.gz`，114,941 字节，SHA-256 `7b689a2012cf5f17bc3209558409cba7981d12cfacd6778186191b786f789d40`。
- Python manifest 的 source_commit 与 annotated tag 的 peeled SHA 相同。wheel/sdist 在工作流中只构建一次，下载验证和上传均复用这组文件。
- GitHub Release 于 2026-10-12 14:31（Asia/Shanghai）公开，设为正式最新版本，含安装包、安装包校验文件、payload 清单、wheel、sdist、SHA256SUMS 和 Python manifest 七个资产。

## 未执行的验收

本次没有在本版安装包上覆盖用户现有安装目录，也未用有效 B 站 Cookie 或 LLM 凭据完成真实分析与桌面报告导出。PR 的浏览器组件检查、冻结后端 smoke 和回归测试不能替代这些实机路径。Windows 安装包未签名。

本次按 GitHub Release 范围发布；未同步发布至 TestPyPI/PyPI，公开索引安装仍以其已发布版本为准。
