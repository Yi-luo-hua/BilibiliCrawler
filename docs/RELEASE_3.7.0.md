# v3.7.0 发布记录

> 状态：**2026-09-28 已公开发布**。发布说明见 [RELEASE_NOTES_3.7.0.md](RELEASE_NOTES_3.7.0.md)，下载见 [GitHub Release v3.7.0](https://github.com/Yi-luo-hua/BilibiliCrawler/releases/tag/v3.7.0)。

## 范围与版本

- 对比基线：`v3.6.0`；包含 PR #52–#57 以及本版的版本与文档更新。
- 桌面、CLI、MCP 和 Python 包共用 `desktop/src-tauri/Cargo.toml` 中的 `3.7.0`。
- 产物：`BilibiliCrawler-Setup-3.7.0-x64.exe`、安装包 SHA-256、`installer-payload-manifest.json`、Python wheel / sdist、`SHA256SUMS` 与 `python-package-manifest.json`。
- 先上传 GitHub Release 的 Windows 资产，再由工作流附加并验证 Python 资产；公开后依次发布至 TestPyPI、PyPI。后两处必须复用 GitHub Release 上的相同文件。

## 发布门禁

| 检查 | 结果 |
|---|---|
| 远端 main、开放 PR/Issue、同名标签 | 发布前无开放 PR/Issue 或同名远端标签；候选 `622b3e1` 推送后，远端 main 与之相同。annotated tag 的 peeled SHA 也是 `622b3e1`。 |
| Python 回归测试与包检查 | 补充独立导入修复后，完整套件 437 项通过；`tests.test_agent_limits` 按模块名及 discover 两种入口各 22 项通过，27 个测试模块均可导入；`scripts/check_package_release.py` 读出 `3.7.0`。 |
| 桌面单元测试、类型检查与前端构建 | 本地单元测试 35/35，通过 `typecheck` 和生产前端构建；`pnpm audit --audit-level high` 无已知漏洞。 |
| Rust 测试与锁定构建 | 候选版本 `cargo test --locked`：7/7。 |
| Windows 安装包构建、清单与上版比对 | 干净 worktree 和隔离 CPython 3.13.15 x64 环境构建通过；7-Zip 解包校验通过，包内主程序为 3.7.0。清单 1299 文件，对比 3.6.0：0 移除、3 新增、44 内容变化。 |
| GitHub Actions 候选提交门禁 | `Python package gate` [36335868969](https://github.com/Yi-luo-hua/BilibiliCrawler/actions/runs/36335868969) 全绿，涵盖 Windows 3.10–3.13、Ubuntu 与 macOS 3.13。 |
| 资产、校验值、发布说明、标签提交一致性 | 七个上传资产均为 `uploaded`；从草稿下载的 Windows 三个资产与本地逐字节相同，Python manifest 的 `source_commit` 与标签 peeled SHA 一致，wheel/sdist 内容审计通过。 |
| TestPyPI 与 PyPI 同文件哈希及安装验证 | [TestPyPI 工作流](https://github.com/Yi-luo-hua/BilibiliCrawler/actions/runs/36336999704) 和 [PyPI 工作流](https://github.com/Yi-luo-hua/BilibiliCrawler/actions/runs/36337307129) 均通过；两个公开索引的 wheel/sdist SHA-256 均等于 Release 资产。两处工作流都通过已发布文件的安装与 MCP smoke。 |

## 影响与验收范围

- 回复分页、`max_pages=0`、抽样/全量分析及 CLI/MCP 参数由回归测试覆盖；PR #57 记录了真实 B 站回复分页与完整爬取验证。
- Cookie 登录及 IP 属地由 PR #54 记录了有效会话的真实接口验证；本次发布不要求在日志或文档中保存会话值。
- 桌面端“全量分析”修复由 PR #52 的回归测试覆盖。发布构建需验证安装包内容；没有实际桌面操作或有效 LLM 分析的路径，应在发布完成时明确记录为未执行。
- 发布预检发现 `tests.test_agent_limits` 不支持按模块名单独运行，已补与其余测试一致的双入口导入；两种入口均通过。这是本版新增的测试兼容修复。
- 安装器行为没有在这些 PR 中修改。若新旧 payload 清单有路径移除，须检查升级残留与用户数据保留后再发布。

## 发布证据

- 候选与标签：`622b3e15ff38817b74f8622f05057465d3c65f6f`；annotated tag `v3.7.0` 的对象为 `2504fd6f2b8163ccc9bae0cd060de9577b7c2a52`。构建后检出内容无差异；Tauri 重写 `Cargo.toml` 的工作区行尾，但文件 blob 与 `HEAD` 的 `87f414d10cb3f13f7ebd880e60226eb2f2dc142b` 一致。
- 安装包：`BilibiliCrawler-Setup-3.7.0-x64.exe`，53,643,974 字节，SHA-256 `44d4ff0d1ae3cd0d8f57cb9618a9ceb27d4bae4f7ce8957afb4c606510999fe4`。校验文件反向解析一致。7-Zip 完整解包校验通过；提取的主程序 `ProductVersion=3.7.0`。包内主程序与构建输出只有 Tauri 的三字节 bundle type 标记不同。
- Python wheel：128,852 字节，SHA-256 `aa3e53d54f7472557633f50a85e256df172d677ba0e17d2f4bc8b98f2d9e24ee`；sdist：140,828 字节，SHA-256 `49977123bf5b3c0a11083bdc95f824e5bec950a16116c49eac60ebbfaa259df0`。`check_package_release.py --verify-release-files` 与 `check_package_artifacts.py` 通过。
- 发布顺序：标签 → GitHub Release 草稿（Windows 三资产）→ [GitHub Python 资产工作流](https://github.com/Yi-luo-hua/BilibiliCrawler/actions/runs/36336653739) 附加四资产 → 下载反向验证 → 公开 Release → TestPyPI → PyPI。PyPI environment 的 required reviewer 门禁由维护者身份在用户授权发布后批准。
- 线上更新检查：GitHub `releases/latest` 返回 `v3.7.0`、`draft=false`、`prerelease=false`；Windows 安装包地址与客户端按标签拼出的地址逐字节一致。
- 真实爬取：匿名、隔离运行目录、`BV15QtG6PEzh --max-pages 1` 得到 30 条主评论与 274 条回复，共 304 条；最大单条回复串 74 条，所有评论 ID 唯一。未使用登录 Cookie。
- 发布后本机干净 CPython 3.13.15 venv 从 PyPI 安装 `bilibili-crawler[mcp]==3.7.0`；`pip check` 无破损，包版本 3.7.0 / MCP 2.1.0，`--version` 与只读 `doctor` 正常。

## 未执行的验收

本次没有覆盖安装到用户现有桌面目录，也没有经真实桌面 UI 操作完成分析与报告导出；没有用有效 LLM 凭据或登录 Cookie 在本次发布构建上重测成功分析与 IP 属地。对应行为有回归测试，PR #54/#57 留有此前的真实接口验证记录，但不能当作本次实机验收。安装包未签名。
