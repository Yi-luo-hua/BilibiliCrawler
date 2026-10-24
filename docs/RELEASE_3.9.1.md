# v3.9.1 发布记录

> 状态：2026-10-24 准备发布。发布说明见 [RELEASE_NOTES_3.9.1.md](RELEASE_NOTES_3.9.1.md)。构建、远端工作流和反向下载检查完成后补齐结果。

## 范围与产物

- 基线 v3.9.0，包含词云高清与 Prism 配色提交 `2ed9379`，以及默认窗口和登录按钮布局提交 `4fa5cbe`。
- 桌面、CLI、MCP 与 Python 包统一由 `desktop/src-tauri/Cargo.toml` 派生版本 3.9.1。
- GitHub Release 提供 Windows x64 安装包、安装包 SHA-256、installer-payload-manifest.json、wheel、sdist、SHA256SUMS 和 python-package-manifest.json 七个资产。
- Windows 后端按仓库要求使用独立 CPython 3.13.15 x64 与哈希锁定依赖构建；Python 包由 annotated tag 发布工作流构建并审计。
- 本次沿用 v3.9.0 的 GitHub Release 发布范围。

## 发布门禁

待记录本地回归、前端构建与审计、Rust 测试、安装包完整性与版本、相对 v3.9.0 的 payload 比较、冻结后端 smoke、候选 CI、标签包审计与干净安装矩阵、七个资产的反向下载及客户端更新发现结果。

## 验收边界

本次不覆盖用户现有安装目录，不使用有效 B 站 Cookie 或付费 LLM 凭据执行真实爬取、分析和桌面报告导出；这些路径不能由回归、包审计与冻结后端 smoke 替代。历史分析图片不会自动重写。Windows 安装包未签名。
