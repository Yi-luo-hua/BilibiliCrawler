# v3.8.0 发布记录

> 状态：2026-10-12 发布准备中。发布说明见 [RELEASE_NOTES_3.8.0.md](RELEASE_NOTES_3.8.0.md)。

## 范围与产物

- 基线 `v3.7.0`，包含 PR #59（合并提交 `1b21d3d`）及本版版本、发布文档更新。
- 桌面、CLI、MCP 和 Python 包统一由 `desktop/src-tauri/Cargo.toml` 派生版本 `3.8.0`。
- GitHub Release：Windows x64 安装包、安装包 SHA-256、`installer-payload-manifest.json`、wheel、sdist、`SHA256SUMS`、`python-package-manifest.json`。
- 从干净工作树和隔离 CPython 3.13.15 x64 环境构建 Windows 安装包；Python 资产由现有发布工作流从 annotated tag 构建并审计。

## 发布门禁

| 检查 | 结果 |
|---|---|
| PR #59 功能复核 | Python 438 项、前端 37 项、构建和 7 项 CI 通过；Edge 在 1440×1440、390×844 验证内部点击、按钮/Esc/遮罩关闭、重新打开和焦点恢复。此记录针对 PR 修复构建。 |
| v3.8.0 版本与自动化 | 待验证。 |
| Windows 构建、版本与上版 payload 比较 | 待验证。 |
| 标签、GitHub 资产与反向下载校验 | 待验证。 |
| tagged Python 包审计与干净安装矩阵 | 待验证。 |

## 未执行的验收

尚未在本版安装包上覆盖用户现有安装目录，也未用有效 B 站 Cookie 或 LLM 凭据完成真实分析与桌面报告导出。PR 的浏览器组件检查和回归测试不能替代这些实机路径。未进行 TestPyPI/PyPI 发布。
