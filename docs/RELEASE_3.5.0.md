# v3.5.0 发布准备与验收清单

> 状态：**v3.5.0 已于 2026-09-03 公开发布**，标签指向 `16a7b4a`。下文保留原发布准备清单；
> 未勾选项中，部分是执行时按顺序完成的模板项，另有两类验收由维护者决定跳过——具体见末尾验收记录的
> 「未执行的验收项」。面向用户的说明见 [v3.5.0 发布说明](RELEASE_NOTES_3.5.0.md)，
> 安装器残留的机制与方案依据见 [安装器跨构建覆盖残留评估](INSTALLER_RESIDUE.md)。

## 发布边界

- 目标版本：`v3.5.0`。分发名 `bilibili-crawler`，导入名 `bilibili_crawler`。
- 版本模型不变：桌面、CLI、MCP 与 Python 包共用同一版本号，唯一来源是
  `desktop/src-tauri/Cargo.toml` 的 `[package].version`。
- 产物：Windows x64 NSIS 安装包、Python wheel / sdist，**外加本版新增的
  `installer-payload-manifest.json`**（打包产物清单，供下一版比对）。
- 本版包含**首个会修改安装目录既有文件的安装器行为**（PREINSTALL 清理）。第 5 节为此新增四条
  升级验收，均为发布阻断项。
- 不在范围：安全退役旧 `_internal` 用户数据（迁移仍只复制不删除）、MCP Registry 登记、
  Python 独立版本号。

## 发布阻断项

### 1. 仓库与版本预检

- [ ] 发布分支基于最新 `origin/main`，工作区干净，没有待合并 PR 或阻断 Issue。
- [ ] `desktop/src-tauri/Cargo.toml` 与 `Cargo.lock` 中的根包版本均为 `3.5.0`。
- [ ] `python scripts/check_package_release.py` 通过，输出为 `bilibili-crawler` / `3.5.0`。
- [ ] README 更新日志、`docs/RELEASE_NOTES_3.5.0.md` 与本清单一致；发布日期只在验收完成后填写。
- [ ] 用 `git ls-remote origin refs/tags/v3.5.0 'refs/tags/v3.5.0^{}'` 确认远端没有同名标签。
- [ ] 记录候选提交 SHA：`$CandidateSha = git rev-parse HEAD`。

### 2. 自动化门禁

- [ ] 两个全新隔离 venv（GUID 命名，`assert sys.prefix != sys.base_prefix`）：无 MCP 环境只装
  `requirements.txt` 并断言 `mcp` 不可导入，MCP 环境装 `requirements-agent.txt` 并断言
  `mcp==2.1.0`；两者各跑 `python -X utf8 -m unittest discover -s tests -q`。
- [ ] 桌面：`corepack pnpm@10.28.0 run test:unit`、`run typecheck`、`run build`、`audit`。
- [ ] Rust：`cargo test --locked --manifest-path desktop/src-tauri/Cargo.toml`（含安装器与自定义
  模块的单元测试）。
- [ ] Rust 检查：**必须在 sidecar 构建完成之后**。先
  `powershell -ExecutionPolicy Bypass -File scripts/build_backend.ps1 -Python $ReleasePython`，
  再 `cargo check --locked --manifest-path desktop/src-tauri/Cargo.toml`。
- [ ] 基础卫生：`git diff --check "$CandidateSha^1" $CandidateSha`。
- [ ] GitHub Actions `Python package gate` 在候选提交对应的 `main` push 上为绿。

### 3. 产物清单比对（本版新增）

- [ ] 取上一版基线：从 v3.4.0 的 Release 下载安装包，用 7-Zip 解出 `resources\backend`，
  再 `python scripts/check_installer_payload.py --tree <解出的 backend> --version 3.4.0
  --out v340-payload-manifest.json`。v3.4.0 早于本功能，没有随发布提供清单，只能这样重建；
  v3.5.0 起清单随 Release 提供，后续版本直接下载即可。
- [ ] 比对本次构建：`python scripts/check_installer_payload.py --tree
  desktop/src-tauri/resources/backend --version 3.5.0 --baseline v340-payload-manifest.json`。
- [ ] 若报告存在被移除的路径，逐条确认第 5 节的清理验收覆盖它们，再以 `--allow-removed` 记录结论。
  **不得在未确认的情况下直接加该参数。**

### 4. Python 包发布前置

- [ ] 复核 GitHub `testpypi`、`pypi` environments 仍只允许 `main`，`pypi` 保留人工 reviewer。
- [ ] TestPyPI / PyPI 的 Trusted Publisher 仍然有效（v3.4.0 已配置并成功发布过）。
- [ ] 本地身份门禁（在 `core.autocrlf=false` 的干净 checkout 或 `git archive` 产物中执行）：
  `python scripts/check_package_release.py --tag v3.5.0 --require-head-tag --require-ancestor-of origin/main`

### 5. 构建链路与 Tauri 真机验收

- [ ] 用 CPython 3.13.15 x64 创建 GUID 命名的全新构建环境作为 `$ReleasePython`。
- [ ] `powershell -ExecutionPolicy Bypass -File scripts/build_installer.ps1 -Python $ReleasePython`
  成功，产出 `BilibiliCrawler-Setup-3.5.0-x64.exe` 与 `installer-payload-manifest.json`。
- [ ] Release notes 说明安装包未代码签名，Windows 可能显示 SmartScreen 提示。

以下为真机验收，不能用自动化测试替代。

#### 常规项

- [ ] 全新安装与从 v3.4.0 覆盖升级均正常，currentUser 安装位置正确。
- [ ] 解析开始菜单与桌面 `BilibiliCrawler.lnk`，`TargetPath` 与 `WorkingDirectory` 指向注册表
  `InstallLocation` 下的 v3.5.0 主程序；必须从快捷方式启动验收。
- [ ] 任务栏图标实机检查并保存截图；升级后验证快捷方式目标与图标缓存刷新。
- [ ] 既有登录状态与凭据发现路径正常；全程日志与 UI 不显示 API Key。
- [ ] 普通评论爬取：进度事件、完成事件、评论数量、CSV 与 run 目录均正确。
- [ ] 空评论结果依次收到 `stats`、`finished(count=0)`、`idle(100)`，无 `error` / `cancelled`。
- [ ] 爬取中停止保留部分结果、只发送一次终态、可立即重试。
- [ ] 分析结果、词云、`analysis.json` 与 Markdown 报告均正确；分析中停止无迟到终态。
- [ ] 从真实 UI 导出 CSV 与分析报告，路径可打开、内容完整。
- [ ] canary API Key 分析后扫描该 run 全部文件，零命中。
- [ ] 默认卸载后安装目录中的 `user-data`、`analysis-runs`、`analysis-assets` 仍保留。

#### 自定义分析模块（本版新增功能）

- [ ] 新建自定义模块后重启桌面端，标题与提示词完整保留。
- [ ] 启用后完成一次分析，结果区出现文本卡片，导出的 Markdown 含同名章节。
- [ ] 删除该模块后重新打开该次分析的历史报告，章节标题仍与运行时一致。
- [ ] 不启用任何自定义模块时，分析输出与 v3.4.0 一致。

#### 安装器清理（本版新增行为，四条均为阻断项）

- [ ] **清理生效**：在 v3.4.0 安装目录的 `_internal` 下人为放入一个标记文件，覆盖安装 v3.5.0 后
  确认该文件已被删除，且应用可正常启动。
- [ ] **遗留用户数据保留**：在 `_internal` 下建立 `analysis-runs` 与 `analysis-assets` 标记目录，
  并另放一个标记文件。覆盖安装后确认三点：两个数据目录**仍在**、**标记文件也仍在**（存在遗留数据时
  整次跳过清理，不是只排除那两个目录）、首次启动后迁移正常。任一数据目录丢失即为发布阻断。
- [ ] **运行中升级并取消**：保持应用运行时启动升级，在「应用正在运行」提示上选择取消，确认
  安装目录未被破坏、原版本仍可启动。
- [ ] **运行中升级并继续**：同上但选择确定，确认应用被关闭、清理与安装完成、新版本可启动。
- [ ] **sidecar 预热期间升级**：删除 matplotlib 字体缓存（`%LOCALAPPDATA%\BilibiliCrawler\cache`
  下的 matplotlib 目录）后启动应用，使 sidecar 进入 30–120 秒的冷预热；**在预热完成前**启动升级，
  在「应用正在运行」提示上选择确定。确认三点之一成立且安装目录始终可用：清理因探测到占用而跳过
  （日志/结果表现为旧文件仍在），或等待后清理正常执行。**不得出现被部分删除、新版本无法启动的
  安装目录。** 这条直接验证"只关主程序不足以释放 sidecar 句柄"的处理是否有效。

### 6. 发布

顺序与 v3.4.0 相同：标签 → Draft（安装包 + 校验文件 + 产物清单）→ 工作流 `github-release` 附加
Python 资产 → 反向核验 → 公开 → `testpypi` → `pypi`。

- [ ] 从候选提交创建全新干净 worktree（放在仓库同级短路径下，避免 `Filename too long`），断言
  HEAD 与工作区状态，重跑第 2 节全部本机门禁。
- [ ] 在该 worktree 中用全新 CPython 3.13.15 x64 环境重新运行 `build_installer.ps1`；只有这次构建
  的产物是最终 Release 资产。
- [ ] 记录安装包大小、SHA-256、构建时间与环境；再次断言 worktree HEAD 未变、工作区无**内容**变更
  （Tauri CLI 会以 LF 重写 `Cargo.toml`，用 `git diff` 为空且 `git hash-object` 等于
  `git rev-parse HEAD:<file>` 判定，而不是 `git status` 输出为空）。
- [ ] 生成 `.sha256` 校验文件并反向解析核对。
- [ ] 创建 annotated tag：`git tag -a v3.5.0 -m "BilibiliCrawler v3.5.0"`，确认
  `git rev-parse 'v3.5.0^{}'` 等于候选提交；推送后用 `git ls-remote` 复核远端 peeled SHA。
- [ ] `gh release create v3.5.0 --draft --verify-tag --title "BilibiliCrawler v3.5.0"
  --notes-file docs/RELEASE_NOTES_3.5.0.md $Installer $ChecksumFile $PayloadManifest`。
- [ ] 手工运行 `Publish Python package`，`tag=v3.5.0`、`destination=github-release`。
- [ ] 下载全部资产反向核验 manifest、`SHA256SUMS`、tag peeled SHA 与安装包 SHA-256；在 Draft 中
  补充文件大小、构建提交与未签名提示。
- [ ] 公开 Release，验证页面、下载链接、安装启动与版本显示。
- [ ] `destination=testpypi`，经 environment 审批与 OIDC 发布。
- [ ] `destination=pypi`，经人工审批。**PyPI 上传不可撤销，版本号不可重用。**
- [ ] 干净环境验证 `python -m pip install "bilibili-crawler[mcp]==3.5.0"`，确认
  `bilibili-crawler --help`、`doctor` 与 `bilibili-crawler-mcp` stdio 握手正常。

## 回滚方案

- 标签推送前发现问题：停止发布，修复后重新生成候选，不复用旧 SHA 或旧产物。
- 标签一旦推送就不移动、不删除；Draft 公开前发现问题则删除 Draft、保留标签，以修复提交发下一个
  补丁版本。
- Release 已公开但安装包有问题：标记 pre-release 或撤下资产，说明置顶影响范围，从新提交发新版本。
- **安装器清理若在真机验收中造成任何数据损失，立即停止发布**：该行为直接删除安装目录下的文件，
  不能带着疑问发布。回退方式是移除 `tauri.conf.json` 的 `installerHooks` 配置后重新构建。
- **PyPI 不可回滚**：版本号不可重用，只能 yank 并发新版本。因此 PyPI 是整条链路最后一步。

## 已知限制

- 安装包未代码签名，Windows 可能显示 SmartScreen 提示。
- **只要 `_internal` 下仍存在 `analysis-runs` 或 `analysis-assets`，安装器就整次跳过清理**，
  不是只保留这两个目录。判据是「旧目录是否存在」而不是「是否已迁移」：迁移是**复制而非移动**，
  即使迁移成功源目录依然保留，因此这批机器会持续跳过清理，行为与升级前完全一致。这是为消除数据
  丢失路径而接受的代价。安全退役旧目录是独立任务，涉及删除用户数据，不在本版范围。
- 产物清单只覆盖 `resources/backend` 子树，不含主程序与 Tauri 自身文件。
- 安装器清理在删除前会探测 `_internal` 是否被占用，最多等待 10 秒。sidecar 正处于冷启动预热
  （字体缓存首次构建，30–120 秒）时探测会失败，本次升级**跳过清理**——结果与升级前一致，不是故障。
- 预清理无法让解压失败变得无害：它把失败形态从"残留旧文件"变成"缺少文件"。NSIS 解压失败仍会弹出
  重试/取消，用户取消则安装目录不完整。已消除的是最主要的诱因（占用中的文件），不是全部。
- 持久化 run 不等于桌面重启恢复。

## 验收记录

> 每完成一节在此追加：执行时间、环境、命令、结果与日志路径（`.runlogs/` 不纳入提交）。

### 2026-09-03：v3.5.0 已发布

**候选**：`16a7b4a`。干净 worktree 位于仓库同级短路径，`git status --porcelain` 仅有 `Cargo.toml`
的行尾重写（两侧 blob 均为 `961462de…`，`git diff` 为空，内容未变）。

**第 2 节门禁**（全部在该 worktree 内重跑）：无 MCP 318 项 OK（3 项预期跳过）、MCP 2.1.0 349/349、
desktop `install --frozen-lockfile` / `audit`（无告警）/ `typecheck` / `build` / `test:unit` 27/27、
`build_backend.ps1` 后 `cargo check --locked`、`cargo test --locked` 7/7、`git diff --check` 干净。

**第 3 节产物清单**：以 v3.4.0 安装包解出的 `resources\backend` 重建基线，比对结果
**0 removed / 0 added / 3 changed**（`base_library.zip`、`sidecar.exe`、numpy 的 `RECORD`），
本次发布不遗留任何文件。

**产物**：`BilibiliCrawler-Setup-3.5.0-x64.exe`，53,515,796 字节，
SHA-256 `f254bc95c4a3bdd222d26b4cd0e425edde2f148a9ce9d2efb5f75e8222121b8a`，
构建完成 2026-09-02T22:24:01+08:00。`.sha256` 已反向解析核对。

**安装器清理的隔离回归**（静默安装至隔离目录 `/S /D=`，不涉及正式安装；测试前备份并于测试后还原了
HKCU 卸载项与桌面快捷方式，真实 3.4.0 安装与其 10 个 run 目录经确认完好）：

| 场景 | 断言 | 结果 |
|---|---|---|
| 清理生效 | 陈旧文件与陈旧目录被删、产物重建 | 通过（1295 文件重建，主程序完好） |
| 遗留数据守卫 | `analysis-runs`、`analysis-assets` **与另置的标记文件**全部保留 | 通过（三者皆在，数据内容未改写） |
| 占用时跳过 | 独占锁住 `python313.dll` 后标记文件保留 | 通过（耗时 16.6s vs 正常 8.1s，与 10s 探测预算吻合） |
| 解锁后恢复 | 释放句柄后清理恢复 | 通过（标记被删，无残留 `.old-payload`） |

**发布链路**：annotated tag `v3.5.0` → `16a7b4a`（远端 peeled SHA 已核）→ Draft（安装包 + 校验文件 +
产物清单）→ 工作流 `github-release` 附加四个 Python 资产 → 下载全部资产反向核验（manifest 的
`source_commit` 等于标签指向的提交，manifest = `SHA256SUMS` = 实算，安装包哈希三处一致）→ 公开 →
`testpypi` → `pypi`（经人工审批）。PyPI / TestPyPI / GitHub Release 三处产物哈希一致。

**发布后验证**：干净 venv 从 PyPI 安装 `bilibili-crawler[mcp]==3.5.0`，`pip check` 无破损，
`--help` 与只读 `doctor` 正常（`ok:true`，识别 MCP 2.1.0），`bilibili-crawler-mcp` stdio 握手成功，
协议 `2025-11-25`，发现 7 个工具。

#### 未执行的验收项

以下为维护者决定跳过，**不是通过**：

- 第 5 节安装器验收的「运行中升级并取消」与「运行中升级并继续」。隔离回归覆盖了清理、守卫、占用
  跳过与解锁恢复，但「进程检查前置是否真的关闭了半删除窗口」需要真实窗口交互，未验证。
- 第 5 节的常规功能真机验收（快捷方式与图标、爬取、空结果、停止重试、分析与词云、导出、canary
  零命中、v3.4.0 覆盖升级、卸载后用户数据保留）。这些代码路径相对 v3.4.0 未改动，但本版未复验。

#### 发布过程中发现的问题

- **工作流的等待步骤 gate 错了对象**：`Wait for exact repository hashes` 轮询 JSON API，而其后的
  安装步骤从 `/simple` 索引下载，两者传播速度不同。TestPyPI 与 PyPI 各因此失败一次（上传均已成功，
  索引同步后重跑失败 job 即通过，未重复上传）。已在收尾提交中增加针对 `/simple` 的等待步骤。
- 本机首次从 PyPI 安装失败，原因是 pip 的用户级 HTTP 缓存中存有旧索引页；`--no-cache-dir` 后正常。
  与发布产物无关。
