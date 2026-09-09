# v3.6.0 发布准备与验收清单

> 状态：**候选，未发布。** 面向用户的说明见 [v3.6.0 桌面候选版说明](RELEASE_NOTES_3.6.0.md)。
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
- 不在范围：静默安装、自动重启、代码签名、增量更新、Python 独立版本号、MCP Registry 登记。

## 发布阻断项

### 1. 仓库与版本预检

- [ ] 发布分支基于最新 `origin/main`，工作区干净，没有待合并 PR 或阻断 Issue。
- [ ] `desktop/src-tauri/Cargo.toml` 与 `Cargo.lock` 中的根包版本均为 `3.6.0`。
- [ ] `python scripts/check_package_release.py` 通过，输出为 `bilibili-crawler` / `3.6.0`。
- [ ] README 更新日志、`docs/RELEASE_NOTES_3.6.0.md` 与本清单一致；发布日期只在验收完成后填写。
- [ ] `docs/FORWARD_PLAN.md` 中没有本版承诺但未完成的任务；已转入本清单的条目在那边已移除。
- [ ] 用 `git ls-remote origin refs/tags/v3.6.0 'refs/tags/v3.6.0^{}'` 确认远端没有同名标签。
- [ ] 记录候选提交 SHA：`$CandidateSha = git rev-parse HEAD`。

### 2. 自动化门禁

- [ ] 两个全新隔离 venv（GUID 命名，`assert sys.prefix != sys.base_prefix`）：无 MCP 环境只装
  `requirements.txt` 并断言 `mcp` 不可导入，MCP 环境装 `requirements-agent.txt` 并断言
  `mcp==2.1.0`；两者各跑 `python -X utf8 -m unittest discover -s tests -q`。
- [ ] 桌面：`corepack pnpm@10.28.0 run test:unit`、`run typecheck`、`run build`、`audit`。
- [ ] Rust：`cargo test --locked --manifest-path desktop/src-tauri/Cargo.toml`。
- [ ] Rust 检查：**必须在 sidecar 构建完成之后**。先
  `powershell -ExecutionPolicy Bypass -File scripts/build_backend.ps1 -Python $ReleasePython`，
  再 `cargo check --locked --manifest-path desktop/src-tauri/Cargo.toml`。
- [ ] 基础卫生：`git diff --check "$CandidateSha^1" $CandidateSha`。
- [ ] GitHub Actions `Python package gate` 在候选提交对应的 `main` push 上为绿。

### 3. 产物清单比对

v3.5.0 起清单随 Release 提供，本版不必再从安装包重建基线。

- [ ] 从 v3.5.0 的 Release 下载 `installer-payload-manifest.json` 作为基线，核对其中的
  `source_commit` 等于标签 `v3.5.0` 指向的提交。
- [ ] 比对本次构建：`python scripts/check_installer_payload.py --tree
  desktop/src-tauri/resources/backend --version 3.6.0 --baseline v350-payload-manifest.json`。
- [ ] 若报告存在被移除的路径，逐条确认第 5 节的清理回归覆盖它们，再以 `--allow-removed` 记录结论。
  **不得在未确认的情况下直接加该参数。**

### 4. Python 包发布前置

- [ ] 复核 GitHub `testpypi`、`pypi` environments 仍只允许 `main`，`pypi` 保留人工 reviewer。
- [ ] TestPyPI / PyPI 的 Trusted Publisher 仍然有效。
- [ ] 本地身份门禁（在 `core.autocrlf=false` 的干净 checkout 或 `git archive` 产物中执行）：
  `python scripts/check_package_release.py --tag v3.6.0 --require-head-tag --require-ancestor-of origin/main`

### 5. 构建链路与 Tauri 真机验收

- [ ] 用 CPython 3.13.15 x64 创建 GUID 命名的全新构建环境作为 `$ReleasePython`。
- [ ] `powershell -ExecutionPolicy Bypass -File scripts/build_installer.ps1 -Python $ReleasePython`
  成功，产出 `BilibiliCrawler-Setup-3.6.0-x64.exe` 与 `installer-payload-manifest.json`。
- [ ] Release notes 说明安装包未代码签名，Windows 可能显示 SmartScreen 提示。

以下为真机验收，不能用自动化测试替代。

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

- [ ] **清理生效**：在 v3.5.0 安装目录的 `_internal` 下人为放入一个标记文件，覆盖安装 v3.6.0 后
  确认该文件已被删除，且应用可正常启动。
- [ ] **遗留用户数据保留**：在 `_internal` 下建立 `analysis-runs` 与 `analysis-assets` 标记目录，
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

### 尚未开始

候选分支 `codex/desktop-version-updates` 的自动化检查已在开发机通过（desktop `test:unit` 30/30、
`tsc --noEmit` 干净），但这不属于第 2 节——第 2 节要求在隔离环境中按发布口径重跑。真机验收一项未做。
