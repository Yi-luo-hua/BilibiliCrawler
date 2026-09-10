# v3.6.0 发布准备与验收清单

> 状态：**v3.6.0 已于 2026-09-10 公开发布**，标签指向 `492b85f`。
> 33/70 已勾选；下文保留原清单。**未勾选项中有一批是维护者决定跳过的**，逐条见末尾验收记录的
> 「未执行的验收项」——那些是跳过，不是通过。面向用户的说明见
> [v3.6.0 发布说明](RELEASE_NOTES_3.6.0.md)，逐步操作见
> [v3.6.0 真机验收操作手册](ACCEPTANCE_RUNBOOK_3.6.0.md)。
> 本清单在标签推送前持续更新：**每有新工作合入候选，必须在第 5 节补上它自己的真机验收项**，
> 否则不得进入第 6 节。

## 发布后：未执行的验收项

以下为**维护者决定跳过**，不是通过。发布已于 2026-09-10 完成，这些路径当时只由回归测试覆盖。

### 一、必须有人做决定或提供凭据（24 项中的主要部分）

| 项目 | 数量 | 卡在哪 |
|---|---|---|
| 分析成功路径（结果与词云、`analysis.json`、Markdown 报告、导出、报告溯源、主题排行导出图、`temperature` 降级） | 7 | 需要 LLM 凭据；`temperature` 那条还需要一个会拒绝该字段的 provider。**canary 泄露验收已单独通过，但只覆盖失败路径** |
| 「发现新版本 → 下载」及依赖它的「任务运行期间禁用下载入口」 | 2 | 需要用临时 3.4.0 构建实测，见手册 3.6 |
| 断网检查更新 | 1 | 需要改动网络连通性 |
| TestPyPI / PyPI Trusted Publisher 复核 | 1 | 只能在 PyPI 账户设置里看；**两处发布均已实际成功，等价于验证了它有效** |
| 真实 412 风控下的爬取 | 1 | 两次真实爬取未触发，已记为跳过；日常遇到时补录即可 |

### 二、可以直接继续做的（无额外前置）

空评论结果、任务栏图标截图与升级后图标缓存、既有登录状态与凭据发现、连续快速点击检查更新、
Star 按钮打开浏览器、动态爬取分页失败、主评论分页真实失败与「爬取并分析」不发 LLM 请求、
默认卸载后数据保留的复验。

### 三、第 6 节发布动作

**已全部完成**，证据见末尾验收记录。其中两条本版新增的硬约束都已线上核实：资产名逐字节匹配
更新检查拼出的地址；v3.5.0 客户端不会收到提示（它没有这个功能），是已知的单向限制。

## 发布边界

- 目标版本：`v3.6.0`。分发名 `bilibili-crawler`，导入名 `bilibili_crawler`。
- 版本模型不变：桌面、CLI、MCP 与 Python 包共用同一版本号，唯一来源是
  `desktop/src-tauri/Cargo.toml` 的 `[package].version`（`setup.py` 直接读取它）。
- 产物：Windows x64 NSIS 安装包、Python wheel / sdist、`installer-payload-manifest.json`。
- 本版**不改动安装器行为**。v3.5.0 的 PREINSTALL 清理原样保留，因此第 5 节把它降为回归项而非
  新行为验收项——但 v3.5.0 发布时跳过的两条「运行中升级」验收仍未执行，本版补做。
- 本版新增**应用自身发起的出站网络请求**（`api.github.com`）。这是桌面端第一次在 B 站 API 与
  LLM provider 之外访问第三方服务，第 5 节为此新增独立验收。
- 本版**改变了爬取任务的成功 / 失败判定**：分页请求失败不再静默截断，主评论/动态分页失败判为
  失败并保留部分数据，子评论失败降为警告。这是本版影响面最大的一处，第 5 节为此新增独立验收。
- 本版**改变了分析请求的重试形状**：provider 在 `param` 中指明 `temperature` 时会移除该字段重发
  一次。降级只发生一次并共用既有的三次请求预算，不新增预算、不改超时。
- 不在范围：静默安装、自动重启、代码签名、增量更新、Python 独立版本号、MCP Registry 登记。
- 不在范围也无法在此修复：经 CLIProxyAPI 的 Antigravity 通道的 HTTP 400
  （`status: FAILED_PRECONDITION`）。已确认为上游区域限制而非参数问题，依据见
  [Provider 错误与原 run 恢复契约](PROVIDER_RECOVERY.md)。**不得把它当作本版 `temperature`
  降级的验收目标。**

## 发布阻断项

### 1. 仓库与版本预检

- [x] 发布分支基于最新 `origin/main`，工作区干净，没有待合并 PR 或阻断 Issue。
- [x] `desktop/src-tauri/Cargo.toml` 与 `Cargo.lock` 中的根包版本均为 `3.6.0`。
- [x] `python scripts/check_package_release.py` 通过，输出为 `bilibili-crawler` / `3.6.0`。
- [x] README 更新日志、`docs/RELEASE_NOTES_3.6.0.md` 与本清单一致；发布日期只在验收完成后填写。
- [x] `docs/FORWARD_PLAN.md` 中没有本版承诺但未完成的任务；已转入本清单的条目在那边已移除。
- [x] 用 `git ls-remote origin refs/tags/v3.6.0 'refs/tags/v3.6.0^{}'` 确认远端没有同名标签。
- [x] 记录候选提交 SHA：`$CandidateSha = git rev-parse HEAD`。

### 2. 自动化门禁

- [x] 两个全新隔离 venv（GUID 命名，`assert sys.prefix != sys.base_prefix`）：无 MCP 环境只装
  `requirements.txt` 并断言 `mcp` 不可导入，MCP 环境装 `requirements-agent.txt` 并断言
  `mcp==2.1.0`；两者各跑 `python -X utf8 -m unittest discover -s tests -q`。
- [x] 桌面：`corepack pnpm@10.28.0 run test:unit`、`run typecheck`、`run build`、`audit`。
- [x] Rust：`cargo test --locked --manifest-path desktop/src-tauri/Cargo.toml`。
- [x] Rust 检查：**必须在 sidecar 构建完成之后**。先
  `powershell -ExecutionPolicy Bypass -File scripts/build_backend.ps1 -Python $ReleasePython`，
  再 `cargo check --locked --manifest-path desktop/src-tauri/Cargo.toml`。
- [x] 基础卫生：`git diff --check "$CandidateSha^1" $CandidateSha`。
- [x] GitHub Actions `Python package gate` 在候选提交对应的 `main` push 上为绿。

### 3. 产物清单比对

v3.5.0 起清单随 Release 提供，本版不必再从安装包重建基线。

- [x] 从 v3.5.0 的 Release 下载 `installer-payload-manifest.json` 作为基线，核对
  `schema`、`root` 与 `version`。**它不含 `source_commit`**——按设计不带时间戳与提交，
  这样内容相同的两次构建产出逐字节相同的清单，可以直接比对。与提交绑定的是同一 Release 里的
  `python-package-manifest.json`，第 6 节的反向核验用它。
- [x] 比对本次构建：`python scripts/check_installer_payload.py --tree
  desktop/src-tauri/resources/backend --version 3.6.0 --baseline v350-payload-manifest.json`。
- [x] 若报告存在被移除的路径，逐条确认第 5 节的清理回归覆盖它们，再以 `--allow-removed` 记录结论。
  **不得在未确认的情况下直接加该参数。**

### 4. Python 包发布前置

- [x] 复核 GitHub `testpypi`、`pypi` environments 仍只允许 `main`，`pypi` 保留人工 reviewer。
- [ ] TestPyPI / PyPI 的 Trusted Publisher 仍然有效。
- [ ] 本地身份门禁（在 `core.autocrlf=false` 的干净 checkout 或 `git archive` 产物中执行）：
  `python scripts/check_package_release.py --tag v3.6.0 --require-head-tag --require-ancestor-of origin/main`

### 5. 构建链路与 Tauri 真机验收

- [ ] 用 CPython 3.13.15 x64 创建 GUID 命名的全新构建环境作为 `$ReleasePython`。
- [ ] `powershell -ExecutionPolicy Bypass -File scripts/build_installer.ps1 -Python $ReleasePython`
  成功，产出 `BilibiliCrawler-Setup-3.6.0-x64.exe` 与 `installer-payload-manifest.json`。
- [x] Release notes 说明安装包未代码签名，Windows 可能显示 SmartScreen 提示。

以下为真机验收，不能用自动化测试替代。三条阻断项的逐步操作、判据与本机的先决条件见
[v3.6.0 真机验收操作手册](ACCEPTANCE_RUNBOOK_3.6.0.md)。**开发机的注册表已被隔离测试污染，
不先按手册第 0 节处理，升级与清理两条验收都会作用在错误的目录上。**

#### 爬取完整性（本版改变了成功 / 失败判定，影响面最大）

自动化测试用夹具制造失败；这里要的是真实网络下的表现，尤其是风控。

- [x] 正常爬取一个公开视频（含子评论）：任务成功，没有出现 `reply_failures` 或不完整警告。
  行为与 v3.5.0 一致，本版的改动不应在顺利路径上产生任何新提示。**注：以 headless 方式验证，
  未经桌面界面。**
- [ ] 爬一个评论量足够大、能真实触发 412 风控的视频：任务**仍然完成**，日志出现「N 条评论的
  回复未能获取」，`manifest.json` 的 `warnings` 与 `counts.reply_failures` 都记到同一个数字，
  `comments.csv` 里主评论完整。**任务不得因此判为失败。**
  **未通过也未失败——两次真实爬取都没能触发风控，见验收记录。按手册 3.3 记为跳过。**
- [ ] 主评论分页真实失败（可断网或用无效/私密目标制造）：任务判为失败并提示结果不完整；
  run 目录里已取得的部分评论与 CSV 仍在，重启桌面端后 `run_id` 仍可读。
- [ ] 同一失败 run 走「爬取并分析」：确认**没有**发出 LLM 请求（provider 侧无调用记录、
  无额度消耗）。
- [x] 爬取中途点停止：终态是「已取消」而不是「失败」，部分结果照常保存，可立即重试。
- [ ] 动态爬取分页失败：部分动态保留在会话中并可导出 CSV。

#### 分析报告溯源与 provider 降级

- [ ] 对视频 A 完成分析并导出 Markdown；再爬视频 B，重新导出**同一份**分析报告，确认头部的
  来源、UP 主、Run ID 仍指向 A，评论署名与 A 匹配。
- [ ] 导出的主题排行图中，长标签不与柱体重叠，数值有独立空间；含 emoji 的标签不被从中间截断。
- [ ] 指向一个会拒绝 `temperature` 的模型（如 OpenAI 推理模型）完成一次最小分析：确认自动降级
  后成功，进度出现「采样参数兼容降级」。**这是本版 `temperature` 降级唯一有效的验收目标；
  CLIProxyAPI/Antigravity 的 400 不是。**
- [ ] 若无此类 provider 可用，记录跳过，并在验收记录中写明该路径仅由回归夹具覆盖。

#### 版本显示与更新检查（本版新增功能）

- [x] 从快捷方式启动安装版，标题栏应用名下显示 `v3.6.0`，与安装包版本一致；不显示
  「正在读取版本…」或「版本读取失败」。
- [x] 侧栏「检查更新」在 v3.6.0 尚未公开时点击，提示「当前已是最新版本」（此时线上最新为
  v3.5.0，数字比较不提示降级），且**不出现下载按钮**。
- [ ] **发现新版本与下载的完整路径**：这条无法用 v3.6.0 自身验证——线上没有比它更新的正式版。
  用临时候选验证：把 `Cargo.toml` 的版本改成 `3.4.0` 单独构建一个**不发布**的安装包，安装后
  点击检查更新，确认三点：提示发现 v3.5.0、「更新说明」展开为 v3.5.0 的 Release body、
  「下载安装更新」在默认浏览器打开
  `https://github.com/Yi-luo-hua/BilibiliCrawler/releases/download/v3.5.0/BilibiliCrawler-Setup-3.5.0-x64.exe`
  且能真正下载完成。验证后卸载该临时版本并还原 `Cargo.toml`。
- [ ] 断网点击检查更新，显示可重试的失败提示，界面不卡死；恢复网络后再次点击可成功。
- [ ] 连续快速点击检查更新，不产生重复请求、不出现两条互相覆盖的结果。
- [ ] 爬取或分析任务运行期间，下载入口禁用并提示等待任务结束；任务结束后恢复可用。
- [ ] 「Star」按钮在默认浏览器打开项目 GitHub 页面，**不在应用内打开**，且不尝试代替用户点星。
- [ ] 全程日志与 UI 不出现 API Key；更新检查的请求不携带任何本地凭据（可用抓包或代理确认
  只发出一个 `GET https://api.github.com/repos/Yi-luo-hua/BilibiliCrawler/releases/latest`）。
- [x] 窗口高度压到 `minHeight`（720）时侧栏可滚动，版本区与 Star 按钮不被裁掉、不遮挡导航。

#### 常规项（v3.5.0 未复验，本版补做）

- [x] 全新安装与从 v3.5.0 覆盖升级均正常，currentUser 安装位置正确。
- [x] 解析开始菜单与桌面 `BilibiliCrawler.lnk`，`TargetPath` 与 `WorkingDirectory` 指向注册表
  `InstallLocation` 下的 v3.6.0 主程序；必须从快捷方式启动验收。
- [ ] 任务栏图标实机检查并保存截图；升级后验证快捷方式目标与图标缓存刷新。
- [ ] 既有登录状态与凭据发现路径正常。
- [x] 普通评论爬取：进度事件、完成事件、评论数量、CSV 与 run 目录均正确。
- [ ] 空评论结果依次收到 `stats`、`finished(count=0)`、`idle(100)`，无 `error` / `cancelled`。
- [x] 爬取中停止保留部分结果、只发送一次终态、可立即重试。
- [ ] 分析结果、词云、`analysis.json` 与 Markdown 报告均正确；分析中停止无迟到终态。
- [ ] 从真实 UI 导出 CSV 与分析报告，路径可打开、内容完整。
  **CSV 半边已通过（见验收记录）；分析报告需 LLM 凭据，未做。**
- [x] canary API Key 分析后扫描该 run 全部文件，零命中。
- [x] 默认卸载后安装目录中的 `user-data`、`analysis-runs`、`analysis-assets` 仍保留。

#### 安装器清理回归（行为未改动，v3.5.0 跳过的两条在此补做）

- [x] **清理生效**：在 v3.5.0 安装目录的 `_internal` 下人为放入一个标记文件，覆盖安装 v3.6.0 后
  确认该文件已被删除，且应用可正常启动。
- [x] **遗留用户数据保留**：在 `_internal` 下建立 `analysis-runs` 与 `analysis-assets` 标记目录，
  并另放一个标记文件。覆盖安装后确认两个数据目录与标记文件全部仍在（存在遗留数据时整次跳过清理）。
  任一数据目录丢失即为发布阻断。
- [x] **运行中升级并取消**（v3.5.0 跳过）：保持应用运行时启动升级，在「应用正在运行」提示上选择
  取消，确认安装目录未被破坏、原版本仍可启动。
- [x] **运行中升级并继续**（v3.5.0 跳过）：同上但选择确定，确认应用被关闭、清理与安装完成、
  新版本可启动。

### 6. 发布

顺序与 v3.5.0 相同：标签 → Draft（安装包 + 校验文件 + 产物清单）→ 工作流 `github-release` 附加
Python 资产 → 反向核验 → 公开 → `testpypi` → `pypi`。

- [ ] 从候选提交创建全新干净 worktree（放在仓库同级短路径下，避免 `Filename too long`），断言
  HEAD 与工作区状态，重跑第 2 节全部本机门禁。
- [ ] 在该 worktree 中用全新 CPython 3.13.15 x64 环境重新运行 `build_installer.ps1`；只有这次构建
  的产物是最终 Release 资产。
- [ ] 记录安装包大小、SHA-256、构建时间与环境；再次断言 worktree HEAD 未变、工作区无**内容**变更
  （Tauri CLI 会以 LF 重写 `Cargo.toml`，用 `git diff` 为空且 `git hash-object` 等于
  `git rev-parse HEAD:<file>` 判定，而不是 `git status` 输出为空）。
- [ ] 生成 `.sha256` 校验文件并反向解析核对。
- [ ] 创建 annotated tag：`git tag -a v3.6.0 -m "BilibiliCrawler v3.6.0"`，确认
  `git rev-parse 'v3.6.0^{}'` 等于候选提交；推送后用 `git ls-remote` 复核远端 peeled SHA。
- [ ] `gh release create v3.6.0 --draft --verify-tag --title "BilibiliCrawler v3.6.0"
  --notes-file docs/RELEASE_NOTES_3.6.0.md $Installer $ChecksumFile $PayloadManifest`。
- [ ] **资产名必须是 `BilibiliCrawler-Setup-3.6.0-x64.exe`。** 更新检查按这个名字逐字节比对
  下载地址，改名会让已安装的旧版本查到新版本却拿不到下载入口（表现为「安装包尚未就绪」）。
- [ ] 手工运行 `Publish Python package`，`tag=v3.6.0`、`destination=github-release`。
- [ ] 下载全部资产反向核验 manifest、`SHA256SUMS`、tag peeled SHA 与安装包 SHA-256；在 Draft 中
  补充文件大小、构建提交与未签名提示。
- [ ] 公开 Release，验证页面、下载链接、安装启动与版本显示。
- [ ] **公开后**用一台装有 v3.5.0 的机器确认它**不会**收到更新提示——v3.5.0 没有这个功能。
  更新检查从 v3.6.0 起才生效，这是已知的单向限制，不是故障。
- [ ] `destination=testpypi`，经 environment 审批与 OIDC 发布。
- [ ] `destination=pypi`，经人工审批。**PyPI 上传不可撤销，版本号不可重用。**
- [ ] 干净环境验证 `python -m pip install "bilibili-crawler[mcp]==3.6.0"`，确认
  `bilibili-crawler --help`、`doctor` 与 `bilibili-crawler-mcp` stdio 握手正常。

## 回滚方案

- 标签推送前发现问题：停止发布，修复后重新生成候选，不复用旧 SHA 或旧产物。
- 标签一旦推送就不移动、不删除；Draft 公开前发现问题则删除 Draft、保留标签，以修复提交发下一个
  补丁版本。
- Release 已公开但安装包有问题：标记 pre-release 或撤下资产，说明置顶影响范围，从新提交发新版本。
  **注意**：撤下资产会让已安装 v3.6.0 的客户端在检查更新时看到版本但拿不到下载入口；把 Release
  标记为 pre-release 则会让它们直接看不到该版本（`parseRelease` 拒绝 `prerelease`）。两种处理的
  客户端表现不同，选定后写进公告。
- **更新检查本身出问题不阻断已发布产物**：它是纯客户端的只读查询，失败只影响提示，不影响爬取与
  分析。若线上 tag 命名不再匹配 `vX.Y.Z`，客户端会提示「无法识别版本号」，修复方式是发布端保持
  标签命名，而不是给客户端放宽校验。
- **PyPI 不可回滚**：版本号不可重用，只能 yank 并发新版本。因此 PyPI 是整条链路最后一步。

## 已知限制

- 安装包未代码签名，Windows 可能显示 SmartScreen 提示。
- 更新为**手动检查、手动下载、手动安装**：不静默安装、不自动重启、不做增量更新。下载完成后需要
  用户自行退出应用并运行安装程序。
- 只接受 `draft=false && prerelease=false` 且标签严格匹配 `^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$`
  的 Release；预发布版与带后缀的标签一律不提示。
- 下载入口要求资产名、大小、`state=uploaded` 与 `browser_download_url` 同时匹配按标签拼出的
  github.com 地址。任一不符只提示版本、不给下载链接，这是刻意的 fail-closed。
- `api.github.com` 对未认证请求限流（每 IP 每小时 60 次）。触发后提示稍后重试，不做退避重排。
- 更新检查走 webview 的 `fetch`。`tauri.conf.json` 当前 `csp: null`；**若将来启用 CSP，必须把
  `https://api.github.com` 加入 `connect-src`**，否则该功能会静默失效。
- 需要的 Tauri 权限已由现有 capability 覆盖（`core:default` → `core:app:default` →
  `allow-version`；`opener:default` → `allow-open-url` + `allow-default-urls` 的 https scope），
  本版未新增 capability。收紧权限时不要漏掉这两项。
- v3.5.0 及更早版本没有更新检查，只能由用户自己去 Release 页面发现新版本。
- 安装器清理的其余限制与 v3.5.0 相同，见 [v3.5.0 清单](RELEASE_3.5.0.md) 的「已知限制」。
- 持久化 run 不等于桌面重启恢复。

## 验收记录

> 每完成一节在此追加：执行时间、环境、命令、结果与日志路径（`.runlogs/` 不纳入提交）。

### 2026-09-10：第 1、2 节完成，第 3–6 节未开始

**候选提交** `247b99da2adee9076f5d34b11670b5e5927f07f7`。`HEAD == origin/main`，工作区干净，
0 个待合并 PR、0 个开放 Issue，远端无 `v3.6.0` 标签。

**第 1 节**：`Cargo.toml` 与 `Cargo.lock` 根包版本均为 `3.6.0`；`check_package_release.py` 输出
`bilibili-crawler` / `3.6.0`，`source_commit` 等于候选提交。README 更新日志、
`RELEASE_NOTES_3.6.0.md` 与本清单已在同一提交中对齐；`FORWARD_PLAN.md` 无本版承诺而未完成的任务。

**第 2 节**（环境：Windows 11 x64、**Python 3.13.0**、Node v24.11.1、pnpm 10.28.0、cargo 1.95.0）：

| 门禁 | 结果 |
|---|---|
| ENV A 隔离 venv（`requirements.txt`） | 隔离断言通过；`mcp` 不可导入；**334 tests OK (skipped=3)** |
| ENV B 隔离 venv（`requirements-agent.txt`） | 隔离断言通过；`mcp 2.1.0`；**365 tests OK**（无跳过） |
| desktop | `install --frozen-lockfile` 锁文件最新；`test:unit` **35/35**；`typecheck` 干净；`build` 成功；`audit` 无已知漏洞 |
| `cargo test --locked` | **7 passed; 0 failed** |
| `git diff --check 247b99d^1 247b99d` | 干净 |
| Actions `Python package gate` | 候选提交对应的 `main` push 为 **success**（run 34387386922） |

两个 venv 均为 GUID 命名的全新环境。跳过数的差异是预期形状：ENV A 少的 3 项正是 MCP 相关用例，
ENV B 装了 `mcp` 后全部执行，因此总数从 334 升到 365。

**用的是 Python 3.13.0，不是发布构建固定的 3.13.15。** 第 2 节没有钉 Python 版本——3.13.15 只约束
第 5 节的安装包构建。第 6 节要求在干净 worktree 中重跑第 2 节全部门禁，届时会与发布环境一并复核。

**第 3 节**：已从 v3.5.0 的 Release 下载 `installer-payload-manifest.json` 作为基线并核对结构
（`schema=1`、`root=backend`、`version=3.5.0`、1296 条目）。同 Release 的
`python-package-manifest.json` 的 `source_commit` 等于标签 `v3.5.0` 的 peeled SHA
`16a7b4a0bc544c80c178658db6d1ef55e9db7d86`。比对本次构建需要先产出新清单，未做。

**第 4 节**：`testpypi` 与 `pypi` environments 复核通过——两者的部署分支策略均只允许 `main`，
`pypi` 保留 `required_reviewers`（Yi-luo-hua）。Trusted Publisher 的有效性只能在 PyPI / TestPyPI
的账户设置里确认，GitHub API 看不到，未复核。

**尚未开始**：第 5 节全部真机验收、第 6 节发布。第 4 节的 Trusted Publisher 复核需登录
PyPI / TestPyPI，GitHub API 看不到。

### 2026-09-10：候选构建，第 2 节收尾与第 3 节完成

**这次构建的产物不用于发布。** 用的是仓库里既有的 `build/desktop-release-venv`
（`cpython|3.13.15|64`，由 `build_backend.ps1` 以 `--require-hashes` 拉到当前锁文件状态），
不是第 5 节要求的 GUID 命名全新环境。目的有三个：确认候选内容能真的构建出来、拿到第 3 节的
增删对比、产出一个可安装的包供真机验收使用。最终 Release 资产必须按第 6 节在干净 worktree 中
用全新环境重建。

**第 2 节收尾**：`build_installer.ps1` 内部先跑 `build_backend.ps1` 重建 sidecar，之后
`cargo check --locked` 通过（45s）。这满足了「Rust 检查必须在 sidecar 构建之后」的排序要求；
此前树里那份 sidecar 早于候选内容，没有用它代替。

**第 3 节比对结果**：

```
payload files: 1296
baseline 3.5.0 -> 3.6.0: 0 removed, 0 added, 3 changed
```

三个变化的文件是 `sidecar/sidecar.exe`、`sidecar/_internal/base_library.zip`、
`sidecar/_internal/numpy-2.5.2.dist-info/RECORD`，与 v3.4.0 → v3.5.0 那次完全同一组——它们是
每次构建都会变的非确定性产物。**0 removed 意味着本版不遗留任何旧路径**，因此不需要
`--allow-removed`，第 5 节的清理回归也没有额外路径要覆盖。

**候选产物**：

| | |
|---|---|
| 文件 | `BilibiliCrawler-Setup-3.6.0-x64.exe` |
| 大小 | 53,519,718 字节 |
| SHA-256 | `591c714684a2590b62c29247aa04836766fbbfba68e7d38a8918c12638978c10` |
| 构建完成 | 2026-09-10 12:42:13 +08:00 |
| 构建自 | `551ddb582cf4c3e7a958e223774254bfd61530ad` |

构建后 `HEAD` 未变；`git status` 显示 `desktop/src-tauri/Cargo.toml` 有改动，但
`git diff` 为空且 `git hash-object` 等于 `git rev-parse HEAD:<file>`（均为
`383a768711683893aee152efce57baee2a7ef0b1`）——只是 Tauri CLI 的 LF 重写，内容未变，与第 6 节
预告的判据一致。

**顺带修正**：第 5 节要求「Release notes 说明安装包未代码签名」，但
`RELEASE_NOTES_3.6.0.md` 里没有这句（v3.5.0 的说明文件同样漏了）。已补入构建与验证一节。

### 2026-09-10：安装器清理回归通过（隔离静默安装）

方法与 v3.5.0 相同：`/S /D=` 静默安装到隔离目录 `E:\Cache\11-temp\bcc-accept-3.6.0\install`，
**不涉及正式安装**。测试前备份用户数据并 `reg export` 两个 HKCU 键，测试后 `reg import` 还原。

先用 v3.5.0 装出基线（SHA-256 `f254bc95…21b8a`，与 Release 附带的校验文件一致），再用本次候选包
覆盖安装。

| 场景 | 断言 | 结果 |
|---|---|---|
| 守卫成立 | `_internal\analysis-runs\marker.txt` 保留 | 通过 |
| 守卫成立 | `_internal\analysis-assets\marker.txt` 保留 | 通过 |
| 守卫成立 | **payload 位置的普通标记文件也保留** | 通过 |
| 守卫成立 | 无 `_internal.old-payload` 残留 | 通过 |
| 守卫成立 | 覆盖后主程序为 3.6.0 且存在 | 通过 |
| 守卫不成立 | 清掉两个遗留目录后再覆盖，**标记文件被删除** | 通过 |
| 守卫不成立 | payload 重建（`sidecar.exe` 存在）、无 `.old-payload` 残留 | 通过 |

第三行是「整次跳过」与「排除两个目录后照删」的分界：后者意味着 v3.5.0 刻意消除的重命名窗口
回来了。最后两行是反向验证——**只做守卫成立那一组无法与「清理功能整个没跑」区分**，两者现象
相同。原清单缺这一组，已在
[v3.6.0 真机验收操作手册](ACCEPTANCE_RUNBOOK_3.6.0.md) 第 2.3 节补上。

**测试后复核**：注册表两个键已还原为测试前的值；正式安装仍为 3.4.0，`analysis-runs` 为
37 文件 / 5,135,277 字节，与测试前备份逐字节一致。备份保留在
`E:\Cache\11-temp\bcc-backup-20260910-130104`。

**这两条是隔离验证，不能替代第 1 节意义上的真实升级**：真实安装位置、快捷方式、升级提示显示的
旧版本号都未覆盖，仍在待做。

### 2026-09-10：爬取顺利路径通过；风控路径未触发，记为跳过

两次真实网络爬取，目标 `BV18UbY6SEH9`，`include_replies=True`，`MAX_REPLY_WORKERS=4` 默认并发，
写入独立的 runs 目录（`BILIBILI_AGENT_RUNS_DIR`），未经桌面界面。

| 最大页数 | 评论数 | 耗时 | 终态 | `counts.reply_failures` | `warnings` |
|---|---|---|---|---|---|
| 30 | 2177（884 主 + 1293 回复） | ~25s | completed | 字段不存在 | 空 |
| 150 | 2871（1262 主 + 1609 回复） | ~31s | completed | 字段不存在 | 空 |

**顺利路径判据成立**：任务完成、没有 `reply_failures` 字段、没有 warnings、`comments.csv` 正常
产出（546,914 / 700,065 字节）。本版的改动没有在顺利路径上添加任何新提示，两个量级都验证了。

**风控路径未触发**：两次都在评论被取完之前没有遇到 412。第二次把页数从 30 提到 150 也只是把
评论从 2177 拉到 2871——该视频的评论量就到这里，再加页数不会产生更多请求。**没有继续加压去
逼出限速**：那既不是这个工具的正常用法，也不会让结论更可靠。

按手册 3.3 记为**跳过，不是通过**。该路径目前只由
`tests/test_crawl_integrity.py::test_reply_failure_completes_the_crawl_and_is_reported_as_a_warning`
覆盖——夹具能证明「回复拉取返回空响应时任务仍完成并记警告」，**不能证明真实的 412 会走进那条
分支**。两者之间隔着 `BilibiliAPI._request` 把 412 重试耗尽压成 `None` 这一步，那一步没有被真实
流量验证过。

后续若在日常使用中偶然遇到（日志出现「N 条评论的回复未能获取」），请把 `manifest.json` 的
`counts.reply_failures` 与 `warnings` 记到这里，即可补上这条。

### 2026-09-10：真实升级验收通过（GUI 全程实机）

在开发机的正式安装位置 `%LOCALAPPDATA%\BilibiliCrawler` 上完成，全程看着安装程序页面操作。

**先证实了本文档 §0.1 的判断。** 在**未清理**注册表的状态下启动 v3.5.0 安装程序：欢迎页之后出现
「Already Installed — An older version of BilibiliCrawler is installed」（来自那条 3.1.1 的陈旧记录，
默认选项会去运行早已不存在的 `uninstall.exe`），继续下一步，**安装目标目录显示
`E:\Cache\11-temp\bcc-isolated-test\install1`**——正是那个不存在的隔离测试路径。取消，未安装任何
东西。这条不是推断，是屏幕上读到的。

清除 `HKCU\Software\local\BilibiliCrawler` 与 `HKCU\...\Uninstall\BilibiliCrawler` 之后重新执行：

| 步骤 | 观察 | 结果 |
|---|---|---|
| v3.5.0 安装 | 不再出现 Already Installed 页；目标目录 `C:\Users\...\AppData\Local\BilibiliCrawler` | 通过 |
| v3.5.0 启动 | 从**开始菜单快捷方式**启动，标题栏应用名下是「评论 / 动态」 | 基线成立 |
| v3.6.0 升级 | 出现 Already Installed 页，正确识别为「older version」 | 通过 |
| — 卸载阶段 | 卸载程序显示 `Uninstalling from: ...\AppData\Local\BilibiliCrawler`，「Delete the application data」**默认未勾选** | — |
| — 卸载后 | `analysis-runs` 37 文件 / 5,135,277 字节、`analysis-assets` 7 / 1,408,336、`user-data` 4 / 2,223,284 **全部保留**，主程序已删除 | 通过 |
| — 安装阶段 | 目标目录仍为 `%LOCALAPPDATA%\BilibiliCrawler` | 通过 |
| v3.6.0 启动 | 从开始菜单快捷方式启动，标题栏显示 **`v3.6.0`**，非「正在读取版本…」或「版本读取失败」 | 通过 |
| 检查更新 | 点击后提示「**当前已是最新版本。**」，**未出现下载按钮** | 通过 |

升级后复核：注册表 `DisplayVersion` = 3.6.0、`InstallLocation` = `%LOCALAPPDATA%\BilibiliCrawler`；
开始菜单与桌面两个 `BilibiliCrawler.lnk` 的 `TargetPath` / `WorkingDirectory` 均指向该位置；
`analysis-runs` 仍是 8 个 run 目录、37 文件、5,135,277 字节，与升级前逐字节一致。
（`user-data` 比最初备份多 33 字节，是 v3.5.0 启动时写入的窗口/配置状态，不是数据损失。）

**一处清单措辞需要修正**：原来要求确认「升级提示显示的旧版本是 3.5.0」。NSIS 模板的
Already Installed 页**只说 "An older version"，不打印版本号**，无法从该页读出 3.5.0。实际可核的是
注册表 `DisplayVersion` 与该页把它归类为 older 而非 newer/same。手册已按此改写。

**测试后的注册表状态是正确的，没有还原污染备份**：两个键现在都指向真实安装位置。备份仍保留在
`E:\Cache\11-temp\bcc-backup-20260910-130104`，仅供追溯，不应重新导入。

**机器现在装的是候选包，不是发布包。** 第 6 节的 Release 资产仍需在干净 worktree 中用全新构建
环境重建。

### 2026-09-10：运行中升级两条（v3.5.0 跳过）与界面爬取通过

**运行中升级并取消。** 应用与 sidecar 同时在跑时启动安装包，走到 PREINSTALL 弹出
「BilibiliCrawler is running! Click OK to kill it」，选**取消**：安装中止（"Installation Aborted —
BilibiliCrawler is running! Please close it first then try again"），应用继续运行未被杀。核对安装
目录：

| 断言 | 结果 |
|---|---|
| 主程序仍在且为 3.6.0 | 通过 |
| payload 文件数 = 1296（与本次构建清单一致） | 通过 |
| `_internal` 存在、`sidecar.exe` 存在 | 通过 |
| 无 `_internal.old-payload` 残留 | 通过 |
| 三个用户数据目录字节不变 | 通过 |

**没有出现半删除的安装目录**——这正是钩子把 `CheckIfAppIsRunning` 放在任何删除动作之前所要保证
的性质，v3.5.0 发布时没有验证过。

**运行中升级并继续。** 同样场景选**确定**：应用被关闭，清理与安装正常完成，payload 仍为 1296
文件、无 `.old-payload` 残留、无残留进程，从开始菜单快捷方式可正常启动。

**顺带确认的一处措辞差异**：Already Installed 页在**同版本**重装时会打印版本号
（"BilibiliCrawler 3.6.0 is already installed"），在**旧版本**升级时只说 "An older version"，不打印。
所以升级前的版本只能从注册表核。

**界面爬取（评论爬取页，含子评论，3 页）**：

| 断言 | 结果 |
|---|---|
| 界面显示「完成：461 条」，统计 461 总 / 90 主 / 371 回复（90+371=461） | 通过 |
| run 目录产出 `comments.csv` 120,680 字节、`comments.json`、`manifest.json` | 通过 |
| `manifest.json` 的 `status=completed`、`counts` 与界面一致、无 `reply_failures`、无 warnings | 通过 |
| `target.title` 正确记录视频标题 | 通过 |
| 界面「导出 CSV」保存的文件与 run 目录内的 `comments.csv` **SHA-256 完全一致**（462 行 = 461 条 + 表头） | 通过 |

**爬取中停止**（改 100 页后启动，7 秒后点停止）：`manifest.json` 记 `status=cancelled`、
`error_code=CANCELLED`、`error` 为空、`stage=任务已取消`，884 条部分数据保留并写出 232,314 字节的
CSV，「开始任务」立即可再次点击。**终态是已取消而不是失败。**

> 一处非阻断的界面观察：点停止后，右上角状态区显示的是「完成：884 条」而不是「已取消」。
> 终态数据本身是正确的（manifest 记 cancelled），只是这个标签会让人误以为正常跑完。属于既有
> 行为，非本版引入，记录备查。

**窗口压到 `minHeight`（900×720）**：侧栏出现滚动条，滚动后「检查更新」与「Star」完整可见，
不被裁切、不遮挡导航。

**未做**：分析相关的全部验收（分析结果、词云、`analysis.json`、Markdown 报告、canary API Key
扫描、导出分析报告）需要 LLM 凭据，本轮未执行。空评论结果、任务栏图标截图、既有登录状态、
断网与连点检查更新、下载入口在任务运行期间禁用、Star 打开浏览器，均未执行。

本版进入候选的工作（用于核对第 5 节是否覆盖齐）：

| PR | 内容 | 第 5 节对应小节 |
|---|---|---|
| #35 / #37 | 爬取完整性、部分数据保留、子评论失败降级 | 爬取完整性 |
| #35 | 报告溯源与主题排行导出 | 分析报告溯源与 provider 降级 |
| #38 | `temperature` 降级 | 分析报告溯源与 provider 降级 |
| #39 / #40 | 版本显示、更新检查、Star、错误文案收紧 | 版本显示与更新检查 |

### 2026-09-10：本轮收尾与环境还原

真机验收暂停于此，已清理本会话产生的临时产物：

- 隔离静默安装目录 `E:\Cache\11-temp\bcc-accept-3.6.0`、两个 GUID 隔离 venv（405 MB）、
  下载的 v3.5.0 安装包与基线清单、临时脚本——全部删除。
- 正式 `analysis-runs` 里本会话跑出的两个测试 run 已删除；该目录已还原为会话开始时的
  **8 个 run / 37 文件 / 5,135,277 字节**。
- 仓库内 `analysis-runs` 中本会话产生的 105 个 pytest 测试 run、`build/sidecar`（PyInstaller
  工作目录，每次构建重建）已删除。**`build/desktop-release-venv` 保留**——它是 CPython 3.13.15
  发布构建环境，第 5、6 节还要用。
- 为验证更新下载路径临时构建过版本号 3.4.0 的二进制，已重新构建回 3.6.0；`Cargo.toml`
  与工作区干净。该验证因授权被拒未完成。

保留未删：`E:\Cache\11-temp\bcc-backup-20260910-130104`（8.4 MB，测试前的用户数据与注册表备份）。
数据已确认完好且逐字节一致，此备份仅供追溯；其中的两个 `.reg` 是**污染前的旧值，不应重新导入**。

仓库内 `.install-test\`（726 MB，7 个 smoke/验收安装目录）是既有的、非本会话产生，未处理。
其中 `BilibiliCrawler-smoke-20260727-183100` 只剩 `user-data\`，是此前指向错误注册表项的那个目录，
该注册表项已在本轮清除。

### 2026-09-10：canary 凭据泄露验收通过

在装好的 3.6.0 上实机执行。该安装包是候选构建（`591c7146…`）；候选构建源 `551ddb5` 与发布构建源
`492b85f` 之间**只有 `docs/` 三个文件的差异**，可执行内容等价，因此结论适用于发布产物。

**方法**：把 API Key 换成一个合成标记串（`sk-CANARY-<32 hex>-DONOTUSE`，51 字符，不对应任何真实
凭据），对 351 条评论发起分析。请求打到 `https://api.deepseek.com/v1` 得到 **HTTP 401**——
**这正是最该验的路径**：provider 在 401 响应体里回显 Key 是最常见的泄露形态，成功路径反而碰不到它。
测试前 `credentials.json` 已备份，测试后按 SHA-256 还原，真实 Key（35 字符）完好。

**结果**：

| 位置 | 命中 |
|---|---|
| 本次 run 目录（`manifest.json` / `comments.json` / `comments.csv`） | **0** |
| `%LOCALAPPDATA%\BilibiliCrawler` 全树 | 1，仅 `user-data\config\credentials.json` |
| `%LOCALAPPDATA%\com.local.bilibilicrawler`（Tauri 应用数据） | 0 |
| `%LOCALAPPDATA%\BilibiliCrawler\cache` | 0 |
| 界面「运行日志」 | 0 |

唯一命中是凭据存储文件本身，按设计如此，不是泄露。

**这次测到了写入路径，不是空跑**：`manifest.json` 确实记录了本次失败——
`status=failed`、`error_code=LLM_AUTH`、`error` 为固定安全说明
「LLM 请求失败: LLM 鉴权或访问权限失败（HTTP 401），请检查 API Key 与服务权限。」。
错误确实落了盘，落盘内容里没有 Key，也没有远端响应正文。界面日志显示同一句固定文案。

**未覆盖**：成功分析所产出的 `analysis.json`、Markdown 报告与词云未参与本次扫描——它们需要一个
可用的 provider。本次只证明了**失败路径**不泄露；成功路径的产物由 `scrub` 边界与回归测试覆盖，
未经真机扫描。

### 2026-09-10：v3.6.0 已发布

**标签** `v3.6.0`（annotated，对象 `f192ec23…`），peeled SHA `492b85f4f75c15b7b7c1a9d8e147fb39b80c04a2`，
推送后经 `git ls-remote` 复核远端 peeled 一致。

**发布构建**：从候选提交开的干净 worktree（`E:\bcc-rel360`，detached），构建环境是 `uv` 新建的
GUID 命名 CPython 3.13.15 x64（隔离断言通过）。第 2 节全部门禁在该 worktree 内重跑：
ENV A 334 OK (skipped=3)、ENV B 365 OK、desktop `test:unit` 35/35 + typecheck + build +
audit 无漏洞、`cargo check --locked`（在 `build_backend.ps1` 之后）、`git diff --check` 干净、
Actions gate 在候选提交上 success。venv 门禁使用本机 Python 3.13.0——第 2 节未钉版本，
3.13.15 只约束安装包构建。

**产物**：

| 文件 | 大小 | SHA-256 |
|---|---|---|
| `BilibiliCrawler-Setup-3.6.0-x64.exe` | 53,533,440 | `5a73e1d9c1aad2d8acf44d09e1fec8cd663709d12a16226d9777a28f0f11192b` |
| `bilibili_crawler-3.6.0-py3-none-any.whl` | 117,314 | `96a839653713d317048ec820ea65c3045cf81fbada652195b3482de15ab95cf2` |
| `bilibili_crawler-3.6.0.tar.gz` | 117,583 | `d1b86cad3471e2ba16da020fcdb151a33a5d241364742da99c420613f1dc5c9d` |

构建完成 2026-09-10 14:39:38 +08:00。构建后 worktree HEAD 未变；`Cargo.toml` 的 LF 重写按内容
判据核实（`git diff` 为空且 blob hash 等于 `HEAD:<file>`，均为 `383a7687…`）。

**产物清单比对**：`0 removed, 0 added, 3 changed`，与 v3.4.0 → v3.5.0 同一组非确定性文件
（`sidecar.exe`、`base_library.zip`、numpy 的 `RECORD`）。**0 removed 意味着本版不遗留任何旧路径**，
因此未使用 `--allow-removed`。

**发布链路**：标签 → Draft（安装包 + 校验文件 + 产物清单）→ 工作流 `github-release` 附加四个
Python 资产 → 反向核验 → 公开 → `testpypi` → `pypi`（经人工审批）。

**反向核验**：下载全部七个资产后，`python-package-manifest.json` 的 `source_commit` 等于标签
peeled SHA；`SHA256SUMS` 与实算一致；安装包哈希三处一致（本地构建 / `.sha256` / 下载后实算）；
`installer-payload-manifest.json` 与本地构建逐字节相同。

**三处产物哈希一致**：GitHub Release = TestPyPI = PyPI，wheel 与 sdist 均核对通过。

**发布后验证**：干净 venv 安装 `bilibili-crawler[mcp]==3.6.0`，`pip check` 无破损，
版本 3.6.0 / mcp 2.1.0；`--help` 与只读 `doctor`（`ok:true`）正常；`bilibili-crawler-mcp` stdio
握手成功，协议 `2025-11-25`，发现 7 个工具。

**更新检查契约线上核实**（只有公开后才能做）：`releases/latest` 的 `draft=false`、
`prerelease=false`、tag 匹配严格 semver、资产名与 `state=uploaded`、`size>0`，且
`browser_download_url` **逐字节等于**客户端按 tag 拼出的地址。这是本版最容易踩的约束，线上成立。

#### 发布过程中的问题

- **候选提交在构建过程中被推进过一次。** 第一次发布构建跑在 `3601d4d` 上，构建期间合入了发布
  说明的修复，main 变成 `492b85f`。标签必须指向候选提交，而 `3601d4d` 里的说明仍是候选版措辞，
  照那样打标签会让 Release 正文与被标签的源码不一致。该次产物作废，worktree 与构建全部重做。
  **教训：构建启动后到打标签之前不要再合并任何东西。**
- **发布说明差点带着候选版措辞发出去。** 第 6 节把 `RELEASE_NOTES_3.6.0.md` 原样作为
  `--notes-file`，而当时它的标题是「v3.6.0 桌面候选版」、正文有「本版尚未公开发布」。发布前改写。
- **第 4 节「或 git archive 产物」这条走不通。** `check_package_release.py` 会调
  `git rev-parse HEAD`，裸解包没有 `.git` 直接报错。有效路径只有干净 worktree。另外本机
  `core.autocrlf=true` 与该节要求的 `false` 不符，但该脚本判据全部来自 git ref，不受影响；
  另用 `git archive` 展开独立确认了被标签内容的版本与说明标题。
- **PyPI `/simple` 索引传播窗口仍会导致本机首次安装失败。** 工作流内的验证 job 一次通过
  （其 `/simple` 等待步骤生效），但本机首次 `pip install`（已带 `--no-cache-dir`）报
  `No matching distribution found`；查 `/simple` 确认 3.6.0 已在索引中，重试即成功。
  属客户端侧几十秒级的传播窗口，非发布问题。v3.5.0 记录的同类现象在客户端侧仍然存在。
- **仓库根目录的 `bilibili_crawler.egg-info` 是陈旧的（Version 3.5.0）。** 在仓库目录内执行
  `importlib.metadata.version('bilibili-crawler')` 会读到它，一度让 wheel 验证误报 3.5.0。
  在中立目录重验为 3.6.0。任何版本相关检查都不要在仓库根目录跑。

#### 未执行的验收项

见上方「发布后：未执行的验收项」。最值得注意的是**分析成功路径的产物从未真机验证**——
`analysis.json`、Markdown 报告、词云均只由回归测试覆盖。canary 凭据泄露验收已通过，但它覆盖的是
HTTP 401 失败路径；成功路径产出的文件未经真机扫描。
