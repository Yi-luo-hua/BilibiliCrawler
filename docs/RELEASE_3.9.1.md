# v3.9.1 发布记录

> 状态：**2026-10-24 已公开发布至 GitHub Release**。发布说明见 [RELEASE_NOTES_3.9.1.md](RELEASE_NOTES_3.9.1.md)，下载见 [GitHub Release v3.9.1](https://github.com/Yi-luo-hua/BilibiliCrawler/releases/tag/v3.9.1)。

## 范围与产物

- 基线 v3.9.0，包含词云高清与 Prism 配色提交 `2ed9379`，以及默认窗口和登录按钮布局提交 `4fa5cbe`。
- 桌面、CLI、MCP 与 Python 包统一由 `desktop/src-tauri/Cargo.toml` 派生版本 3.9.1。
- GitHub Release 提供 Windows x64 安装包、安装包 SHA-256、installer-payload-manifest.json、wheel、sdist、SHA256SUMS 和 python-package-manifest.json 七个资产。
- Windows 后端按仓库要求使用独立 CPython 3.13.15 x64 与哈希锁定依赖构建；Python 包由 annotated tag 发布工作流构建并审计。
- 本次沿用 v3.9.0 的 GitHub Release 发布范围。

## 发布门禁

| 检查 | 结果 |
|---|---|
| 本地回归与前端审计 | Python unittest 438/438、前端 37/37、锁定依赖的 Rust release 测试 8/8 通过；TypeScript 与 Vite 生产构建通过，pnpm audit 已知漏洞为 0。 |
| 词云实际渲染 | 发布用 CPython 3.13.15 环境以原来的 142 个词频生成 3200 × 1760 图片，与选中的 Prism 预览逐像素一致。 |
| Windows 安装包 | 7-Zip 完整性检查与解包通过，主程序 ProductVersion/FileVersion 均为 3.9.1；1,299 个后端文件逐一通过大小与 SHA-256 检查。相对官方 v3.9.0 清单：0 移除、0 新增、2 内容变化，分别为 base_library.zip 与 sidecar.exe。解包主程序与构建输出仅存在 Tauri 三字节 UNK/NSS bundle type 标记差异。 |
| 冻结后端与桌面启动 | 包内 sidecar 发出 ready、完成渲染初始化、成功响应 session.status 并正常退出。独立解包目录的桌面界面显示 v3.9.1，连接该目录中的后端，渲染引擎就绪；登录文字保持单行。测试窗口已关闭。 |
| 候选提交 CI | [Python package gate 40104808893](https://github.com/Yi-luo-hua/BilibiliCrawler/actions/runs/40104808893) 7/7 项通过。 |
| 标签包审计与干净安装 | [发布工作流 40105537846](https://github.com/Yi-luo-hua/BilibiliCrawler/actions/runs/40105537846) 成功，8 项任务通过，2 项索引发布任务按范围跳过；Windows Python 3.10–3.13、Linux/macOS Python 3.13 的 wheel/sdist 基础与 MCP 安装均通过。下载后本地再次通过 31 个运行文件的标签源码绑定、manifest 和 SHA256SUMS 检查。 |
| 资产与更新发现 | 草稿阶段和公开后均反向下载七个资产，大小和 SHA-256 均匹配本地 Windows 构建或标签工作流原始文件，并匹配 GitHub asset digest。公开后 releases/latest 返回 v3.9.1、draft=false、prerelease=false；实际客户端 parseRelease/isNewerVersion 可从 3.9.0 识别更新及正确的 x64 安装包地址。 |

## 发布证据

- 实际构建提交与 annotated tag v3.9.1 的目标：`960f01f5b97baf608a63060dc6920a74ddb9ba56`，属于 main 历史。本记录在公开发布后以文档提交补齐，标签保持在实际构建提交。
- Windows 安装包 `BilibiliCrawler-Setup-3.9.1-x64.exe`：53,645,549 字节，SHA-256 `b6098e1440da28d0a253aa8f1ff363b5ff09734c3e47ec3efe7c401aca0b4572`。
- Python wheel `bilibili_crawler-3.9.1-py3-none-any.whl`：121,653 字节，SHA-256 `29c74cd539b81ba5577813e468b12506c58e98dcf5666d7cd9a00e46a490810a`。
- Python sdist `bilibili_crawler-3.9.1.tar.gz`：115,297 字节，SHA-256 `ae2437273af3d526978e0a94ba86fa2a8cc3d400d17e312561addc4b865f6894`。
- Python manifest 的 source_commit 与标签目标一致，wheel/sdist 只在标签工作流构建一次，后续校验与上传复用同一组文件。
- GitHub Release 于 **2026-10-24 23:12:51（Asia/Shanghai）**公开，设为正式最新版本，包含安装包、安装包 SHA-256、payload 清单、wheel、sdist、SHA256SUMS 和 Python manifest 七个资产。

## 验收边界

本次不覆盖用户现有安装目录，不使用有效 B 站 Cookie 或付费 LLM 凭据执行真实爬取、分析和桌面报告导出；这些路径不能由回归、包审计与冻结后端 smoke 替代。历史分析图片不会自动重写。Windows 安装包未签名。

本次未同步发布至 TestPyPI/PyPI，公开索引安装仍以其已发布版本为准。
