# v3.6.0 发布准备与验收清单

> 状态：**候选，未发布。第 1、2、3 节已完成（2026-09-10），候选构建已产出安装包。**
> 剩下的是第 5 节真机验收与第 6 节发布；真机验收未开始，见末尾验收记录。
> 面向用户的说明见 [v3.6.0 桌面候选版说明](RELEASE_NOTES_3.6.0.md)。
> 本清单在标签推送前持续更新：**每有新工作合入候选，必须在第 5 节补上它自己的真机验收项**，
> 否则不得进入第 6 节。

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
- [ ] 主评论分页真实失败（可断网或用无效/私密目标制造）：任务判为失败并提示结果不完整；
  run 目录里已取得的部分评论与 CSV 仍在，重启桌面端后 `run_id` 仍可读。
- [ ] 同一失败 run 走「爬取并分析」：确认**没有**发出 LLM 请求（provider 侧无调用记录、
  无额度消耗）。
- [ ] 爬取中途点停止：终态是「已取消」而不是「失败」，部分结果照常保存，可立即重试。
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

- [ ] 从快捷方式启动安装版，标题栏应用名下显示 `v3.6.0`，与安装包版本一致；不显示
  「正在读取版本…」或「版本读取失败」。
- [ ] 侧栏「检查更新」在 v3.6.0 尚未公开时点击，提示「当前已是最新版本」（此时线上最新为
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
- [ ] 窗口高度压到 `minHeight`（720）时侧栏可滚动，版本区与 Star 按钮不被裁掉、不遮挡导航。

#### 常规项（v3.5.0 未复验，本版补做）

- [ ] 全新安装与从 v3.5.0 覆盖升级均正常，currentUser 安装位置正确。
- [ ] 解析开始菜单与桌面 `BilibiliCrawler.lnk`，`TargetPath` 与 `WorkingDirectory` 指向注册表
  `InstallLocation` 下的 v3.6.0 主程序；必须从快捷方式启动验收。
- [ ] 任务栏图标实机检查并保存截图；升级后验证快捷方式目标与图标缓存刷新。
- [ ] 既有登录状态与凭据发现路径正常。
- [ ] 普通评论爬取：进度事件、完成事件、评论数量、CSV 与 run 目录均正确。
- [ ] 空评论结果依次收到 `stats`、`finished(count=0)`、`idle(100)`，无 `error` / `cancelled`。
- [ ] 爬取中停止保留部分结果、只发送一次终态、可立即重试。
- [ ] 分析结果、词云、`analysis.json` 与 Markdown 报告均正确；分析中停止无迟到终态。
- [ ] 从真实 UI 导出 CSV 与分析报告，路径可打开、内容完整。
- [ ] canary API Key 分析后扫描该 run 全部文件，零命中。
- [ ] 默认卸载后安装目录中的 `user-data`、`analysis-runs`、`analysis-assets` 仍保留。

#### 安装器清理回归（行为未改动，v3.5.0 跳过的两条在此补做）

- [x] **清理生效**：在 v3.5.0 安装目录的 `_internal` 下人为放入一个标记文件，覆盖安装 v3.6.0 后
  确认该文件已被删除，且应用可正常启动。
- [x] **遗留用户数据保留**：在 `_internal` 下建立 `analysis-runs` 与 `analysis-assets` 标记目录，
  并另放一个标记文件。覆盖安装后确认两个数据目录与标记文件全部仍在（存在遗留数据时整次跳过清理）。
  任一数据目录丢失即为发布阻断。
- [ ] **运行中升级并取消**（v3.5.0 跳过）：保持应用运行时启动升级，在「应用正在运行」提示上选择
  取消，确认安装目录未被破坏、原版本仍可启动。
- [ ] **运行中升级并继续**（v3.5.0 跳过）：同上但选择确定，确认应用被关闭、清理与安装完成、
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

本版进入候选的工作（用于核对第 5 节是否覆盖齐）：

| PR | 内容 | 第 5 节对应小节 |
|---|---|---|
| #35 / #37 | 爬取完整性、部分数据保留、子评论失败降级 | 爬取完整性 |
| #35 | 报告溯源与主题排行导出 | 分析报告溯源与 provider 降级 |
| #38 | `temperature` 降级 | 分析报告溯源与 provider 降级 |
| #39 / #40 | 版本显示、更新检查、Star、错误文案收紧 | 版本显示与更新检查 |
