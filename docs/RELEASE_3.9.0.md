# v3.9.0 发布记录

> 状态：2026-10-23 构建验收中。发布说明见 [RELEASE_NOTES_3.9.0.md](RELEASE_NOTES_3.9.0.md)。完成后补充实际资产、标签及验证证据。

## 范围

- 基线为 v3.8.0，包含启动优化提交 `8de982d`。
- 桌面、CLI、MCP 和 Python 包由 `desktop/src-tauri/Cargo.toml` 派生版本 3.9.0。
- 按上一版范围发布至 GitHub Release：Windows x64 安装包、安装包 SHA-256、installer-payload-manifest.json、wheel、sdist、SHA256SUMS 和 python-package-manifest.json。
- Windows 后端使用独立 CPython 3.13.15 x64 和哈希锁定依赖重新构建；Python 发布资产由 annotated tag 工作流一次构建并审计。

## 已有启动优化验证

- 版本准备前，同一机器、同一快捷方式、保留缓存的启动平均由 7.41 秒降至 2.87 秒，三个优化后样本为 3.13、2.76、2.71 秒。
- 37 项前端测试、8 项 Rust release 测试、生产构建与类型检查通过。
- 独立配置目录和虚构密钥验证：启动不改写配置/凭据，实际编辑保存与重启恢复正常，凭据保持隐藏，窗口最大化/还原状态同步正常。
- 用户现有配置及凭据文件的内容和修改时间经核对保留。本机已安装 exe 以备份方式替换为优化构建；此操作不等同于 3.9.0 安装器覆盖升级验收。

## 本版发布门禁

- Python unittest：405 项运行完成，6 项按条件跳过，其余通过。
- 前端：37/37；Vite 7.3.7 生产构建与 TypeScript 检查通过，pnpm audit 已知漏洞为 0。
- Rust：锁定依赖、release 模式测试 8/8。
- 待记录候选提交 CI、Windows 构建、7-Zip 检查、ProductVersion、包内后端 smoke、上版文件清单比对、标签包审计、干净安装矩阵和公开资产反向下载校验。

## 验收边界

本版不要求有效 B 站 Cookie 或付费 LLM 才能验证启动修复。若未实际执行真实爬取/分析、桌面导出或用户目录安装覆盖，不将自动化与后端 smoke 记为这些路径通过。Windows 安装包未签名。本次 GitHub Release 不自动同步至 TestPyPI/PyPI。
