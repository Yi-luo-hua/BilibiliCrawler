# v3.7.0 发布记录

> 状态：准备中。发布说明见 [RELEASE_NOTES_3.7.0.md](RELEASE_NOTES_3.7.0.md)。

## 范围与版本

- 对比基线：`v3.6.0`；包含 PR #52–#57 以及本版的版本与文档更新。
- 桌面、CLI、MCP 和 Python 包共用 `desktop/src-tauri/Cargo.toml` 中的 `3.7.0`。
- 产物：`BilibiliCrawler-Setup-3.7.0-x64.exe`、安装包 SHA-256、`installer-payload-manifest.json`、Python wheel / sdist、`SHA256SUMS` 与 `python-package-manifest.json`。
- 先上传 GitHub Release 的 Windows 资产，再由工作流附加并验证 Python 资产；公开后依次发布至 TestPyPI、PyPI。后两处必须复用 GitHub Release 上的相同文件。

## 发布门禁

| 检查 | 结果 |
|---|---|
| 远端 main、开放 PR/Issue、同名标签 | 2026-09-28 预检：main 为 `37ca589`；开放 PR/Issue 均为 0；远端无 `v3.7.0` 标签。候选提交推送前须复核。 |
| Python 回归测试与包检查 | 补充独立导入修复后，完整套件 437 项通过；`tests.test_agent_limits` 按模块名及 discover 两种入口各 22 项通过，27 个测试模块均可导入；`scripts/check_package_release.py` 读出 `3.7.0`。 |
| 桌面单元测试、类型检查与前端构建 | 本地单元测试 35/35，通过 `typecheck` 和生产前端构建；`pnpm audit --audit-level high` 无已知漏洞。 |
| Rust 测试与锁定构建 | 候选版本 `cargo test --locked`：7/7。 |
| Windows 安装包构建、清单与上版比对 | 待记录 |
| GitHub Actions 候选提交门禁 | 上一提交 `37ca589` 的 Python package gate 全部通过；候选提交尚未推送。 |
| 资产、校验值、发布说明、标签提交一致性 | 待记录 |
| TestPyPI 与 PyPI 同文件哈希及安装验证 | 待记录 |

## 影响与验收范围

- 回复分页、`max_pages=0`、抽样/全量分析及 CLI/MCP 参数由回归测试覆盖；PR #57 记录了真实 B 站回复分页与完整爬取验证。
- Cookie 登录及 IP 属地由 PR #54 记录了有效会话的真实接口验证；本次发布不要求在日志或文档中保存会话值。
- 桌面端“全量分析”修复由 PR #52 的回归测试覆盖。发布构建需验证安装包内容；没有实际桌面操作或有效 LLM 分析的路径，应在发布完成时明确记录为未执行。
- 发布预检发现 `tests.test_agent_limits` 不支持按模块名单独运行，已补与其余测试一致的双入口导入；两种入口均通过。这是本版新增的测试兼容修复。
- 安装器行为没有在这些 PR 中修改。若新旧 payload 清单有路径移除，须检查升级残留与用户数据保留后再发布。

## 发布证据

候选提交、构建环境、测试结果、安装包哈希、GitHub Release 与 Python 包索引验证结果在执行后填写。此处的“待记录”不是通过。
