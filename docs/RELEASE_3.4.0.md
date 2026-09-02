# v3.4.0 发布准备与验收清单

> 状态：Release Candidate 准备中。清单未逐项勾选前不得创建标签、上传 Release 资产或向
> TestPyPI / PyPI 发布。批次进度见 [v3.3.0 后续实施计划](POST_3.3.0_PLAN.md)，包发布治理见
> [Python 包发布治理](PYTHON_PACKAGE_RELEASE.md)，面向用户的说明见
> [v3.4.0 发布说明](RELEASE_NOTES_3.4.0.md)。

## 发布边界

- 目标版本：`v3.4.0`。分发名 `bilibili-crawler`，导入名 `bilibili_crawler`。
- 基线：`main` 的 `52281af`（PR #20 合并后）。候选提交须在发布时重新确认，不复用本文写作时的 SHA。
- 版本模型：桌面客户端、CLI、MCP 与 Python 包继续共用同一仓库和版本号，唯一来源是
  `desktop/src-tauri/Cargo.toml` 的 `[package].version`；`pyproject.toml` 不另设版本。
- 本次正式产物：Windows x64 NSIS 安装包 **加上** 首次公开的 Python wheel / sdist。这是
  v3.3.0 之后新增 CLI/MCP、分析尝试状态与恢复能力的次版本，不是 v3.3.0 的补丁重发。
- 已公开的 `v3.3.0` 标签指向 `6ae33df`，早于 Python 包实现，禁止把 3.4.0 产物追加到该 Release。
- 不在本次发布范围：`server.json` / MCP Registry 登记、Python 独立版本号、远程 MCP 服务、
  并发任务队列、动态与混合来源分析、扫码登录。

## 发布阻断项

### 1. 仓库与版本预检

- [ ] 发布分支基于最新 `origin/main`，工作区干净，没有待合并 PR 或阻断 Issue。
- [ ] `desktop/src-tauri/Cargo.toml` 与 `desktop/src-tauri/Cargo.lock` 中的根包版本均为 `3.4.0`。
- [ ] `python scripts/check_package_release.py` 通过，输出的公开包名与版本为 `bilibili-crawler` / `3.4.0`。
- [ ] README 更新日志、`docs/RELEASE_NOTES_3.4.0.md` 与本清单一致；发布日期只在验收完成后填写。
- [ ] 用 `git ls-remote origin refs/tags/v3.4.0 'refs/tags/v3.4.0^{}'` 确认远端没有同名标签。
- [ ] 记录候选提交 SHA：`$CandidateSha = git rev-parse HEAD`，并确认它就是拟打标签的提交。

### 2. 自动化门禁

- [ ] 生成 `$GateId = [guid]::NewGuid().ToString('N')`，在 `Join-Path $env:TEMP "bcc-v340-no-mcp-$GateId"` 与
  `Join-Path $env:TEMP "bcc-v340-mcp-$GateId"` 创建两个全新 venv；分别设置 `$NoMcpPython`、`$McpPython`
  为其中的 `Scripts\python.exe`，并用 `assert sys.prefix != sys.base_prefix` 验证隔离环境。
- [ ] 无 MCP 环境只安装 `requirements.txt`，先运行
  `& $NoMcpPython -c "import importlib.util; assert importlib.util.find_spec('mcp') is None"`，
  再运行 `& $NoMcpPython -X utf8 -m unittest discover -s tests -q`；MCP 相关模块按预期跳过，退出码为 0。
- [ ] MCP 环境安装 `requirements-agent.txt`，先运行
  `& $McpPython -c "import importlib.metadata as m; assert m.version('mcp') == '2.1.0'"`，
  再运行同一条全量命令，要求全部通过。
- [ ] 桌面契约：在 `desktop/` 运行 `corepack pnpm@10.28.0 run test:unit`（真实 `SidecarClient` 子进程）
  与 `corepack pnpm@10.28.0 run typecheck`。
- [ ] 前端构建：在 `desktop/` 运行 `corepack pnpm@10.28.0 run build`。
- [ ] 依赖审计：在 `desktop/` 运行 `corepack pnpm@10.28.0 audit`。
- [ ] Rust 检查：**必须在 sidecar 构建完成之后**运行。先
  `powershell -ExecutionPolicy Bypass -File scripts/build_backend.ps1 -Python $ReleasePython`
  生成 `desktop/src-tauri/resources/backend`，再运行
  `cargo check --locked --manifest-path desktop/src-tauri/Cargo.toml`。干净 checkout 里该目录不存在，
  `tauri.conf.json` 又把它声明为打包资源，先跑 cargo check 会直接以
  `resource path resources\backend doesn't exist` 失败。
- [ ] 基础卫生：合并后设置 `$CandidateSha = git rev-parse HEAD`，运行
  `git diff --check "$CandidateSha^1" $CandidateSha`。
- [ ] GitHub Actions `Python package gate` 在候选提交对应的 `main` push 上为绿：一次构建产物、
  `twine check --strict`、内容白名单审计、源码绑定，以及 Windows 3.10–3.13 与 Ubuntu/macOS 3.13
  的 wheel/sdist 基础与 MCP 干净安装分片。远端结果不可用本机日志代替。

以上门禁必须在版本号和发布文档落定后重跑；历史通过记录只能作为参考，不能代替候选提交验证。

### 3. Python 包发布前置

- [ ] TestPyPI 站点侧为本仓库、`testpypi` environment 和 `publish-python-package.yml`
  配置 pending Trusted Publisher。
- [ ] PyPI 站点侧配置同名 pending Trusted Publisher。**不得**创建长期 API token 作为临时替代，
  也不得设置 `TWINE_PASSWORD`。
- [ ] 确认 GitHub `testpypi`、`pypi` environments 仍只允许 `main`，且 `pypi` 保留人工 reviewer。
- [ ] 本地反向核对身份门禁（在 `core.autocrlf=false` 的干净 checkout 或 `git archive` 产物中执行，
  避免 Windows 换行转换与 tag blob 不一致）：

  ```powershell
  python scripts/check_package_release.py --tag v3.4.0 --require-head-tag --require-ancestor-of origin/main
  ```

### 4. 构建链路预检

- [ ] 安装 CPython 3.13.15 x64，以它创建 GUID 命名的全新构建环境并设置 `$ReleasePython`；
  `scripts/build_installer.ps1` 会 fail-fast 拒绝其他实现、版本或 32 位解释器。
- [ ] 运行 `powershell -ExecutionPolicy Bypass -File scripts/build_installer.ps1 -Python $ReleasePython`；
  脚本以 `pip --require-hashes` 安装 `requirements-desktop.lock` 与 `requirements-build.txt`。
- [ ] 记录 `& $ReleasePython -m pip freeze`、Python 版本、Rust 版本与 `corepack pnpm@10.28.0 --version`。
- [ ] 确认构建脚本对 NSIS 3.11 zip 与 `nsis_tauri_utils.dll` 的 SHA-256 校验通过。
- [ ] 确认预检产物为 `desktop/src-tauri/target/release/bundle/nsis/BilibiliCrawler-Setup-3.4.0-x64.exe`，
  并完成安装与真机验收；PR 分支上的产物只证明构建链路可用，不得直接作为 Release 资产。
- [ ] 用 `Get-FileHash -Algorithm SHA256` 记录预检产物，供合并后的最终构建对比；不得把这个哈希
  写成正式发布哈希。
- [ ] Release notes 明确说明安装包未进行代码签名，Windows 可能显示 SmartScreen 提示。

### 5. Tauri 真机验收

这是发布阻断项，不能用 Python 单元测试、sidecar 子进程测试或包安装矩阵替代。

- [ ] 安装前读取 `HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\BilibiliCrawler`；
  带日期的 `.install-test\\BilibiliCrawler-smoke-*` 目录视为历史验收样本，不得作为新候选的覆盖升级目标。
- [ ] 在 Windows x64 上分别验证全新安装与**从 v3.3.0 覆盖升级**，确认 currentUser 安装位置正常；
  禁止用 `/UPDATE + /D=<新目录>` 模拟常规安装后直接判定通过。
- [ ] 安装后解析开始菜单和桌面 `BilibiliCrawler.lnk`，确认 `TargetPath` 与 `WorkingDirectory` 指向注册表
  `InstallLocation` 下的 v3.4.0 主程序；`IconLocation` 可显式指向该程序或为 `,0`，但不得指向旧安装。
  必须从快捷方式启动验收。
- [ ] 在当前 Windows 缩放下实机检查运行中任务栏图标并保存截图，同时解析 ICO/EXE 资源确认包含
  16/24/32 像素层；升级后验证快捷方式目标与 Explorer 图标缓存刷新。
- [ ] 启动桌面端，确认既有登录状态与凭据发现路径正常；全程不得在日志或 UI 中显示 API Key。
- [ ] 完成一次普通评论爬取，核对进度事件、完成事件、评论数量、CSV 与 run 目录。
- [ ] 触发空评论结果，确认依次收到 `stats`、`finished(count=0)`、`idle(100)`，不出现 `error` 或 `cancelled`。
- [ ] 爬取中点击停止，确认保留部分结果、只发送一次终态并可立即重试。
- [ ] 对评论运行执行分析，核对结构化结果、词云显示、`analysis.json` 与 Markdown 报告。
- [ ] 分析中点击停止，确认不会迟到发送 `finished`，并能立即重新分析。
- [ ] 从真实 UI 导出 CSV 与分析报告，确认路径可打开、内容完整。
- [ ] 用 canary API Key 完成一次分析，随后搜索该 run 目录下全部文件，确认 canary 零命中。
- [ ] 在 v3.3.0 中创建可识别的凭据和 run 标记后覆盖升级，确认两者仍存在且可读。
- [ ] 使用默认卸载选项卸载 v3.4.0，确认安装目录中的 `user-data` 与 `analysis-runs` 标记仍保留；
  记录结果后再由测试者手工清理这些测试数据。

#### v3.4.0 新增行为的真机验收

- [ ] 对已有报告的 run 重新分析并在请求过程中取消，确认上一份完整报告仍可在 UI 打开，
  run 未被整体标记为取消，且可立即再次分析。
- [ ] 故意配置错误的 provider/model 触发失败分析，确认 UI 给出可区分的失败原因，评论数据与
  `run_id` 保留；修正配置后只重新分析、不重新爬取，评论文件哈希不变。
- [ ] 长分析过程中观察进度文案含已用时间、批次与重试信息，且百分比不倒退、不伪造增长。
- [ ] 桌面端凭据与 run 目录在升级后仍走既有发现顺序；安装的 Python 包与桌面 sidecar 的用户数据
  目录互不干扰。

#### 候选产物真机证据

2026-09-02 在候选 `526e8cc` 上完成预检构建与真机验收。

- 预检安装包：`BilibiliCrawler-Setup-3.4.0-x64.exe`，53,497,031 字节，
  SHA-256 `4FE2306E5C58C5CF41D3E8E600963CA5C6A0FF26DEBD9E36C24280B786BD3921`，
  构建完成 2026-09-02T02:58:26+08:00，`build_installer.ps1` 耗时 4.77 分钟。
  **这是预检哈希，不是发布哈希**；第 6 节的最终构建另行记录。
- 构建环境：CPython 3.13.15 x64（GUID 命名的新建 venv）、rustc/cargo 1.95.0、
  pnpm 10.28.0、Windows 11 x64 10.0.26100。worktree 位于仓库同级的
  `BilibiliCommentsCrawler-worktrees\release-v3.4.0-final`。
- 自动化门禁（同一候选）：无 MCP 全量 299 项 OK（3 项预期跳过）；MCP 2.1.0 全量 330/330；
  desktop `install --frozen-lockfile`、`audit`（无告警）、`typecheck`、`build`、
  `test:unit` 13/13 均 exit 0；`build_backend.ps1` 后 `cargo check --locked` exit 0；
  `git diff --check 526e8cc^1 526e8cc` exit 0。
- 真机验收由维护者在本机 Windows 11 x64 上按本节及前瞻计划 P0 的顺序逐项执行，报告全部通过、
  未发现问题。本文不代为记录每一项的具体数值，逐项观察以维护者的验收记录为准。
- 已知偏差：安装包构建期间 Tauri CLI 以 LF 重写了 `desktop/src-tauri/Cargo.toml`，
  `git status` 因此显示 ` M`。该文件经 clean filter 的对象哈希为 `513c3717…`，与
  `526e8cc` 的 blob 逐字节相同，`git diff` 为空，属于行尾差异而非源码改动。

### 6. 发布

顺序固定：先桌面 Release，再附加 Python 资产，最后按 TestPyPI → PyPI 发布索引。
`publish-python-package.yml` 的 `github-release` 阶段会先 `gh release view <tag>`，要求 Release
已存在，且不覆盖同名资产。

- [ ] 更新本地 `main` 到 `origin/main`，确认工作区干净且没有未合并发布提交；设置
  `$CandidateSha = git rev-parse HEAD`。
- [ ] 从 `$CandidateSha` 创建全新干净 worktree，断言其中 `git rev-parse HEAD` 等于 `$CandidateSha`
  且 `git status --porcelain` 为空；在该 worktree 中重新运行第 2 节全部本机门禁。门禁内部有顺序依赖：
  Rust 检查排在 `build_backend.ps1` 之后，其余各项可先行。`build_installer.ps1` 会再次调用
  `build_backend.ps1`，重复构建 sidecar 是预期行为。
- [ ] worktree 放在短路径下（例如与仓库同级的 `BilibiliCommentsCrawler-worktrees\`）。`node_modules`
  与 Rust target 会叠加很深的相对路径，深目录下的创建或删除会遇到 Windows `Filename too long`。
- [ ] 在该 worktree 中使用全新 CPython 3.13.15 x64 构建环境重新运行 `scripts/build_installer.ps1`；
  只有这次构建生成的安装包才是最终 Release 资产。
- [ ] 设置 `$Installer = Resolve-Path 'desktop/src-tauri/target/release/bundle/nsis/BilibiliCrawler-Setup-3.4.0-x64.exe'`，
  记录文件大小、构建时间、构建主机环境、SHA-256 与 `$CandidateSha`，并再次断言 worktree HEAD 未变化、
  工作区仍干净（忽略的构建产物除外）。判据是**无内容变更**而不是 `git status` 输出为空：Tauri CLI
  会在构建中以 LF 重写 `desktop/src-tauri/Cargo.toml`，`core.autocrlf=true` 下会出现 ` M`。
  用 `git diff` 为空且 `git hash-object <file>` 等于 `git rev-parse HEAD:<file>` 判定内容未变；
  任何真实内容差异仍然作废本次构建。
- [ ] 生成校验文件：
  `$ChecksumFile = "$Installer.sha256"; $Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Installer).Hash.ToLowerInvariant(); "$Hash  $([IO.Path]::GetFileName($Installer))" | Set-Content -Encoding ascii -LiteralPath $ChecksumFile`，
  并在本地反向解析校验文件确认文件名与哈希匹配。
- [ ] 在最终提交创建 annotated tag：`git tag -a v3.4.0 -m "BilibiliCrawler v3.4.0"`，确认
  `git rev-parse 'v3.4.0^{}'` 等于 `$CandidateSha`。轻量标签会被发布门禁拒绝。
- [ ] 用 `git push origin refs/tags/v3.4.0` 推送标签，再用
  `git ls-remote origin refs/tags/v3.4.0 'refs/tags/v3.4.0^{}'` 确认远端 peeled SHA 仍等于候选提交。
- [ ] 创建 Draft 并上传桌面产物：
  `gh release create v3.4.0 --draft --verify-tag --title "BilibiliCrawler v3.4.0" --notes-file docs/RELEASE_NOTES_3.4.0.md $Installer $ChecksumFile`。
- [ ] 从默认分支手工运行 `Publish Python package`，`tag=v3.4.0`、`destination=github-release`。
  工作流从标签构建一次 wheel/sdist，执行身份、审计与六分片干净安装，然后按 wheel、sdist、
  `SHA256SUMS`、`python-package-manifest.json` 的顺序上传。
- [ ] 下载四个 Python 资产与安装包，反向验证 manifest、`SHA256SUMS`、tag peeled SHA 与安装包
  SHA-256；在 Draft 中补充文件大小、构建提交 SHA 与未签名提示。
- [ ] 公开 Release，验证页面、下载链接、安装启动与版本显示。
- [ ] 运行 `Publish Python package`，`destination=testpypi`；经 `testpypi` environment 审批与 OIDC 发布。
  工作流自动比对 GitHub 资产、索引 SHA-256、公共下载与干净安装 smoke。
- [ ] 运行 `Publish Python package`，`destination=pypi`；经 `pypi` environment 人工审批。工作流拒绝
  TestPyPI 缺失或哈希不同的候选，并在上传后复验 PyPI。
- [ ] 发布后在干净环境验证 `python -m pip install "bilibili-crawler[mcp]==3.4.0"`，确认
  `bilibili-crawler --help`、`doctor` 与 `bilibili-crawler-mcp` stdio 握手正常。

## 回滚方案

- 远端标签推送前发现问题：停止发布，修复后重新生成候选，不复用旧 SHA、旧安装包或旧 wheel。
- 远端标签一旦推送就不移动或删除；若在 Draft 公开前发现问题，删除 Draft、保留原标签，并以修复
  提交发布下一个补丁版本（例如 `v3.4.1`）。
- Release 已公开但安装包有问题：立即将 Release 标记为 pre-release 或撤下问题资产，发布说明置顶
  影响范围，并从新提交生成新版本；不移动或覆盖既有标签。
- **Python 索引不可回滚**：TestPyPI / PyPI 上传后不得重用同一版本号。发现问题时 yank 该版本并发布
  新版本；PyPI 阶段是整条链路中最后、也是唯一不可撤销的一步，必须在桌面 Release 与 TestPyPI 全部
  验证通过后才执行。
- 桌面契约出现回归：优先恢复 v3.3.0 下载入口，同时保留失败候选和日志用于复盘。

## 已知限制

- 安装包未做代码签名，Windows 可能显示 SmartScreen 提示。
- 持久化 run 不等于桌面重启恢复；启动恢复未实现前不对外作此承诺。
- 单个 run 不支持多进程并发写入；根目录兼容副本不是原子多文件读取入口，应使用 artifacts 版本路径。
- Windows 目录发布对短暂共享锁使用有限退避，根因（Defender / 索引器 / 文件监视器一类外部锁）
  未定位到具体进程；持续锁仍 fail-closed。
- 外部付费模型 live smoke 与真实 B 站 live smoke 为可选检查，不是本次发布门禁。

## 验收记录

> 每完成一节在此追加：执行时间、环境、命令、结果与日志路径（`.runlogs/` 不纳入提交）。

### 2026-09-02

- 第 1–2 节：在候选 `526e8cc` 上通过。两个隔离 venv 均由 CPython 3.13.15 x64 创建，
  分别校验 `mcp` 不可导入与 `mcp==2.1.0`。日志 `.runlogs/gate-{no-mcp,mcp}.log`。
- 第 3 节：GitHub `testpypi` / `pypi` environments 复核通过，均只允许 `main`，`pypi` 保留
  人工 reviewer。TestPyPI 与 PyPI 的 pending Trusted Publisher 由维护者配置完成；
  站点侧配置无公开只读接口，首次真正验证发生在发布工作流的 `testpypi` 阶段。
- 第 4 节：`build_backend.ps1` 与 `build_installer.ps1` 均 exit 0，
  日志 `.runlogs/build-{backend,installer}.log`。NSIS 3.11 工具链命中本地缓存。
- 第 5 节：真机验收由维护者执行并报告通过，详见上文候选产物真机证据。
- 过程中修正的两处清单缺陷：`cargo check` 缺少「sidecar 构建之后」的顺序前提（`5bd7440`），
  以及 worktree 干净判据应为无内容变更而非 `git status` 为空（本次）。
  另有一处依赖告警在候选中修复：`browserslist` 经 pnpm overrides 锁到 4.28.8（`cfd9601`）。
