# v3.3.0 发布准备与验收清单

## 发布边界

- 目标版本：`v3.3.0`。
- 基线：`main` 的 `87a66f9`，叠加本发布准备提交。
- 当前状态：Release Candidate 准备中；在所有“发布阻断项”完成前不得创建标签或公开 Release。
- 版本模型：桌面客户端、CLI 与 MCP 服务器暂时共用同一仓库和版本号。
- 本次正式产物：Windows x64 NSIS 安装包；CLI / MCP 继续通过源码环境安装。
- Python wheel / sdist 与 PyPI / MCP Registry 发布属于 v3.3.0 之后的里程碑，不是本次发布阻断项。

## 发布阻断项

### 1. 仓库与版本预检

- [ ] 发布分支基于最新 `origin/main`，且工作区干净。
- [ ] `desktop/src-tauri/Cargo.toml` 与 `desktop/src-tauri/Cargo.lock` 中的根包版本均为 `3.3.0`。
- [ ] 确认没有待合并 PR、阻断 Issue 或遗漏分支。
- [ ] 处理并核对本机 `v1.0.1` 与远端同名标签的冲突；不得改写已有远端标签。
- [ ] 在最终构建前记录候选提交 SHA，并确认它就是拟打标签的提交。

### 2. 自动化门禁

- [ ] 生成 `$GateId = [guid]::NewGuid().ToString('N')`，在 `Join-Path $env:TEMP "bcc-v330-no-mcp-$GateId"` 与 `Join-Path $env:TEMP "bcc-v330-mcp-$GateId"` 创建两个全新 venv；分别设置 `$NoMcpPython`、`$McpPython` 为其中的 `Scripts\python.exe`，并用 `assert sys.prefix != sys.base_prefix` 验证隔离环境。
- [ ] 无 MCP 环境只安装 `requirements.txt`，运行 `& $NoMcpPython -c "import importlib.util; assert importlib.util.find_spec('mcp') is None"` 后再运行 `& $NoMcpPython -m unittest discover -s tests -q`。
- [ ] MCP 环境安装 `requirements-agent.txt`，运行 `& $McpPython -c "import importlib.metadata as m; assert m.version('mcp') == '2.1.0'"` 后再运行 `& $McpPython -m unittest discover -s tests -q`；Python 套件必须覆盖嵌套凭据回显与损坏/超限词云降级。
- [ ] 桌面契约：在 `desktop/` 运行 `node --experimental-strip-types --test tests/*.test.ts`；其中必须覆盖非 comments source 回退以及跨进程完成/取消。
- [ ] 前端构建：在 `desktop/` 运行 `corepack pnpm@10.28.0 build`。
- [ ] 依赖审计：在 `desktop/` 运行 `corepack pnpm@10.28.0 audit`。
- [ ] sidecar 构建完成后运行 Rust 检查：`cargo check --locked --manifest-path desktop/src-tauri/Cargo.toml`。
- [ ] PR 阶段基础卫生：`git diff --check origin/main...HEAD`；合并后设置 `$CandidateSha = git rev-parse HEAD`，运行 `git diff --check "$CandidateSha^1" $CandidateSha` 检查实际候选提交。

以上门禁必须在版本号和发布文档落定后重跑；历史通过记录只能作为参考，不能代替候选提交验证。

### 3. 构建链路预检

- [ ] 安装 CPython 3.13.15 x64，以它创建 GUID 命名的全新构建环境并设置 `$ReleasePython`；脚本必须 fail-fast 拒绝其他实现、版本或 32 位解释器。
- [ ] 运行 `powershell -ExecutionPolicy Bypass -File scripts/build_installer.ps1 -Python $ReleasePython`；脚本会以 `pip --require-hashes` 安装锁定的运行时与构建工具。
- [ ] 确认 `requirements-desktop.lock` 与 `requirements-build.txt` 已提交，并记录 `& $ReleasePython -m pip freeze`、Python 版本、Rust 版本和 `corepack pnpm@10.28.0 --version`。
- [ ] 确认构建脚本对 NSIS 3.11 zip 与 `nsis_tauri_utils.dll` 的 SHA-256 校验通过。
- [ ] 确认预检产物为 `desktop/src-tauri/target/release/bundle/nsis/BilibiliCrawler-Setup-3.3.0-x64.exe`，并完成安装与真机验收；PR 分支上的产物只证明构建链路可用，不得直接作为 Release 资产。
- [ ] 用 `Get-FileHash -Algorithm SHA256` 记录预检产物，供合并后的最终构建对比；不得把这个哈希写成正式发布哈希。
- [ ] Release notes 明确说明安装包当前未进行代码签名，Windows 可能显示 SmartScreen 提示。

### 4. Tauri 真机验收

这是发布阻断项，不能用 Python 单元测试或 sidecar 子进程测试替代。

- [ ] 安装前读取 `HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\BilibiliCrawler`；带日期的 `.install-test\\BilibiliCrawler-smoke-*` 目录视为历史验收样本，不得作为新候选的覆盖升级目标。
- [ ] 在 Windows x64 上分别验证全新安装与从 v3.2.0 覆盖升级，确认 currentUser 安装位置正常；禁止用 `/UPDATE + /D=<新目录>` 模拟常规安装后直接判定通过，因为该组合可能保留指向旧目录的快捷方式。
- [ ] 安装后解析开始菜单和桌面 `BilibiliCrawler.lnk`，确认 `TargetPath`、`WorkingDirectory` 与 `IconLocation` 都指向注册表 `InstallLocation` 下的 v3.3.0 主程序；必须从快捷方式启动验收，不能只直接运行 exe。
- [ ] 在 Windows 任务栏缩放 100% / 125% / 150% 下检查运行中图标，保存截图并确认使用 ICO 的 16/24/32 像素层而非放大单一 16×16 图标；升级后还要验证 Explorer 图标缓存刷新。
- [ ] 启动桌面端，确认既有登录状态与凭据发现路径正常；全程不得在日志或 UI 中显示 API Key。
- [ ] 完成一次普通评论爬取，核对进度事件、完成事件、评论数量、CSV 与 run 目录。
- [ ] 触发空评论结果，确认依次收到 `stats`、`finished(count=0)`、`idle(100)`，不出现 `error` 或 `cancelled`。
- [ ] 爬取中点击停止，确认保留部分结果、只发送一次终态并可立即重试。
- [ ] 对评论运行执行分析，核对结构化结果、词云显示、`analysis.json` 与 Markdown 报告。
- [ ] 分析中点击停止，确认不会迟到发送 `finished`，并能立即重新分析。
- [ ] 导出 CSV 与分析报告，确认路径可打开、内容完整，表格公式前缀已被安全处理。
- [ ] 用 canary API Key 完成一次分析，随后搜索该 run 目录下全部文件，确认 canary 零命中；嵌套配置回显由自动化测试负责，不用真机结果替代。
- [ ] 在 v3.2.0 中创建可识别的凭据和 run 标记后覆盖升级，确认两者仍存在且可读。
- [ ] 使用默认卸载选项卸载 v3.3.0，确认安装目录中的 `user-data` 与 `analysis-runs` 标记仍保留；记录结果后再由测试者手工清理这些测试数据。

### 5. 发布

- [ ] 合并发布准备 PR，更新本地 `main` 到 `origin/main`，确认工作区干净且没有未合并发布提交；设置 `$CandidateSha = git rev-parse HEAD`。
- [ ] 从 `$CandidateSha` 创建全新干净 worktree，断言其中 `git rev-parse HEAD` 等于 `$CandidateSha` 且 `git status --porcelain` 为空；在该 worktree 中重新运行第 2 节全部自动化门禁。
- [ ] 在该 worktree 中使用全新 CPython 3.13.15 x64 构建环境重新运行 `scripts/build_installer.ps1`；只有这次构建生成的安装包才是最终 Release 资产。
- [ ] 设置 `$Installer = Resolve-Path 'desktop/src-tauri/target/release/bundle/nsis/BilibiliCrawler-Setup-3.3.0-x64.exe'`，记录文件大小、构建时间、构建主机环境、SHA-256 与 `$CandidateSha`，并再次断言 worktree HEAD 未变化且工作区仍干净（忽略的构建产物除外）。
- [ ] 生成校验文件：`$ChecksumFile = "$Installer.sha256"; $Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Installer).Hash.ToLowerInvariant(); "$Hash  $([IO.Path]::GetFileName($Installer))" | Set-Content -Encoding ascii -LiteralPath $ChecksumFile`，并在本地反向解析校验文件确认文件名与哈希匹配。
- [ ] 用 `git ls-remote origin refs/tags/v3.3.0 'refs/tags/v3.3.0^{}'` 确认远端没有同名标签。
- [ ] 在最终提交创建 annotated tag：`git tag -a v3.3.0 -m "BilibiliCrawler v3.3.0"`，并确认 `git rev-parse 'v3.3.0^{}'` 等于候选提交 SHA。
- [ ] 用 `git push origin refs/tags/v3.3.0` 推送标签，再用 `git ls-remote origin refs/tags/v3.3.0 'refs/tags/v3.3.0^{}'` 确认远端 peeled SHA 仍等于候选提交。
- [ ] 使用 `gh release create v3.3.0 --draft --verify-tag --title "BilibiliCrawler v3.3.0" --notes-file docs/RELEASE_NOTES_3.3.0.md $Installer $ChecksumFile` 创建 Draft 并同时上传安装包与校验文件。
- [ ] 在 Draft 中补充文件大小和构建提交 SHA，并核对安装包未签名提示。
- [ ] 从 Draft 下载产物并复核 SHA-256 后再公开 Release。
- [ ] 发布后验证 Release 页面、下载链接、安装启动和版本显示。

## 回滚方案

- 远端标签推送前发现问题：停止发布，修复后重新生成候选，不复用旧 SHA 或旧安装包。
- 远端标签一旦推送就不移动或删除；若在 Draft 公开前发现问题，删除 Draft、保留原标签并以修复提交发布下一个补丁版本（例如 `v3.3.1`）。
- Release 已公开但安装包有问题：立即将 Release 标记为 pre-release 或撤下问题资产，发布说明置顶影响范围，并从新提交生成新版本；不移动或覆盖既有标签。
- 桌面迁移出现契约回归：优先恢复 v3.2.0 下载入口，同时保留失败候选和日志用于复盘。

## MCP 实际调用改进计划（v3.3.0 之后）

2026-08-29 使用独立 MCP 2.1.0 客户端经真实 stdio 子进程调用 `crawl_and_analyze`：5 页成功落盘 775 条评论，但只把桌面端 `credentials.json` 传给子进程时，服务端没有同时获得保存在 `ui.json` 中的 DeepSeek base URL 与 model，因而静默使用 OpenAI 默认端点并返回 401。补齐 `BILIBILI_LLM_BASE_URL=https://api.deepseek.com/v1` 与 `BILIBILI_LLM_MODEL=deepseek-v4-flash` 后，`analyze_run` 复用同一 run 成功生成报告。测试还观察到部分 Windows 控制台会把 MCP 返回的中文状态显示为乱码，但落盘 UTF-8 报告内容正常。

### P0：配置解析与启动诊断

- 将桌面端配置按一个 profile 解析：从桌面 `credentials.json` 命中 API Key 时，同时读取同目录 `ui.json` 的 `llm_base_url` / `llm_model`；显式 `BILIBILI_LLM_*` 环境变量仍逐字段拥有最高优先级。
- 保留 OpenAI 默认值的兼容行为，但不得在同目录已经存在非默认 provider 配置时忽略它并静默回落；配置损坏或字段冲突时返回不含密钥的可操作错误。
- 增加 `python -m backend.agent doctor`（或等价只读诊断入口），只显示凭据来源类型、已解析的 base URL、model、MCP SDK 版本及运行目录可写性，不显示 API Key；提供可选 provider 连通性检查。
- 在 MCP 宿主配置文档中明确：stdio 子进程是否继承调用者环境由宿主/客户端决定；示例必须把自定义环境显式放进启动参数，并覆盖“只有凭据文件、没有 base URL/model”的非 OpenAI 场景。

### P1：失败恢复与错误语义

- 分析请求收到 401/403、模型不存在或端点不可达时，区分 provider 鉴权、模型配置与网络错误，不再全部折叠成泛化的 `ANALYSIS_FAILED`；错误可以包含非敏感 endpoint/model/source，但仍必须经过 `scrub()`。
- `crawl_and_analyze` 已经成功落盘评论而分析失败时，返回值的 `next_step` 必须明确给出 `analyze_run(run_id=...)`，引导调用者复用已有数据，禁止默认重新爬取。
- 保持 acquire 与 analyze 分阶段、run 可恢复的现有设计；配置修正后的重试只重跑 LLM、解析与报告渲染，不覆盖评论原始数据。

### P1：真实 stdio 验收与 Windows 编码

- 增加启动真实 `python -m backend.agent mcp` 子进程的集成测试，而不只使用进程内 `Client(mcp)`；测试显式环境传递、7 个工具发现、调用终态和跨进程 run 恢复。
- 用夹具覆盖“Key 在 `credentials.json`、provider/model 在相邻 `ui.json`”以及环境变量逐字段覆盖桌面配置的优先级，断言请求实际发往预期 endpoint，且任何输出与落盘文件均不出现 canary key。
- 增加中文 progress、stage、summary 经 stdio 往返的 UTF-8 测试；Windows 手工说明补充 `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8` 的排障方式，区分终端显示问题与产物编码损坏。
- 提供 opt-in 的 live smoke（视频 URL、页数与 sample size 均由环境变量传入），检查工具发现、爬取、分析、报告/JSON/CSV/manifest 完整性和凭据零命中；外网与第三方模型不稳定，因此 live smoke 记录结果但不作为普通 PR 的硬门禁。

### 完成标准

- 非 OpenAI 桌面配置无需重复手工填写 base URL/model，即可从源码 MCP 和未来 wheel 安装入口完成一次真实 `crawl_and_analyze`。
- 故意配置错误 endpoint 或 model 时，在开始昂贵重试前得到不泄密、可定位的错误；修正配置后可对原 run 执行 `analyze_run` 并生成报告。
- Windows stdio 客户端可正确显示中文状态，且 comments、analysis、report、manifest 中对真实/测试 API Key 的扫描结果均为 0。

## Python 包计划（v3.3.0 之后）

目标是让 CLI / MCP 可以脱离源码 checkout 安装，同时先维持与桌面端同仓库、同版本发布，避免过早引入两套版本治理。

### P1：建立可打包边界

- 新增 `pyproject.toml`，声明 Python `>=3.10`、项目元数据、许可证、README 与构建后端。
- 将当前 `src`、`backend`、`config`、`utils` 等通用顶层模块收敛到唯一命名空间（建议 `src/bilibili_crawler/`），并为所有可分发子包建立明确的 `__init__.py` / package discovery；旧入口只保留薄兼容 shim。
- 明确可分发包清单和运行时资源清单，排除桌面构建产物、测试 fixture、用户数据和凭据文件。
- 消除 `src/service/paths.py` 等模块对源码 checkout 层级的假设：包内静态资源用 `importlib.resources`，run、凭据与缓存目录通过显式环境变量或平台数据目录解析。
- 将核心爬取/分析依赖与 MCP 依赖分层；评估采用 `mcp` 可选 extra，避免只使用 CLI 的用户被迫安装 MCP SDK。
- 提供稳定的 console scripts，例如 `bilibili-crawler` 与 `bilibili-crawler-mcp`，同时保留 `python -m backend.agent` 兼容入口。
- 继续以 `desktop/src-tauri/Cargo.toml` 为发布版本唯一来源；构建前由版本生成脚本写入包内 `_version.py`，CI 必须断言 wheel 元数据、Cargo 与标签三者一致。

### P2：验证 wheel / sdist

- 构建 wheel 与 sdist，并运行 `twine check`。
- 在全新 Python 3.10、3.11、3.12、3.13 虚拟环境中只从构建产物安装。
- 验证 CLI help、run 列举、最小爬取流程和 stdio MCP 握手，不允许依赖源码 checkout 或当前工作目录。
- 加入安装包内容审计，确认不携带 API Key、cookies、run 数据、缓存或本机绝对路径。

### P3：接入发布流程

- 初期随同一 GitHub Release 上传 wheel / sdist，并保持与桌面端 lockstep 版本。
- 在 TestPyPI 完成安装验证后再启用正式 PyPI 发布；使用受保护环境或 Trusted Publishing，不保存长期上传 token。
- 只有公共包安装路径稳定后，才增加 `server.json` 并评估 MCP Registry 发布。
- CI 中加入构建可重复性、包安装 smoke test、版本一致性与发布资产校验。

### P4：何时拆分版本

只有在 CLI / MCP 的发布频率、兼容承诺或用户群已经明显独立于桌面端时，才考虑独立包名、标签和 changelog。在此之前统一版本更容易说明“同一业务核心、两个入口”的兼容关系。

## 本次明确不做

- 不在 v3.3.0 临时加入未经 clean-install 验证的 `pyproject.toml`。
- 不发布 wheel / sdist，不上传 PyPI，不登记 MCP Registry。
- 不因 Python 包规划延后已经完成的桌面 sidecar 迁移发布；两条工作流在 v3.3.0 后再汇合。
