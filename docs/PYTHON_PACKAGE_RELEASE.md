# Python 包发布治理（H）

更新时间：2026-09-02。G 已完成；本文件只管理 GitHub/Python 包发布链路，不把尚未执行的
远端上传写成完成。

## 已确定的发布身份与边界

- 分发名固定为 `bilibili-crawler`，导入名固定为 `bilibili_crawler`。2026-09-01 查询 PyPI
  JSON API 返回 404，说明当时没有同名公开项目；这不是名称预留，首次发布成功前仍可能变化。
- Python 包继续与桌面端使用同一个 Cargo 版本。`pyproject.toml` 不另设版本，wheel/sdist
  元数据、`v<version>` 标签和 `desktop/src-tauri/Cargo.toml` 必须一致。
- 已公开的 `v3.3.0` 标签指向 `6ae33df`，早于 A–G 和 Python 包实现。当前分支构建出的
  3.3.0 产物不能追加到该 Release；必须先在后续发布批次确定新版本并完成桌面/包共同验收。
- GitHub Release 资产顺序固定为 wheel、sdist、`SHA256SUMS` 和
  `python-package-manifest.json`。工作流不覆盖同名资产，避免发布后静默替换。
- TestPyPI/PyPI 仅使用 GitHub OIDC Trusted Publishing 和受保护 environment，不设置
  `TWINE_PASSWORD`、API token 或其他长期发布密钥。

## 已完成的自动化

- [x] `scripts/check_package_release.py` 统一读取公开包名和 Cargo 版本，校验 annotated tag
  指向当前构建提交且该提交可从 `origin/main` 到达，并生成包含 source commit、大小和
  SHA-256 的发布 manifest/checksum。
- [x] 远端仓库门禁按文件名和 SHA-256 比对 TestPyPI/PyPI JSON API，拒绝缺失、重复或
  内容不同的产物。
- [x] `.github/workflows/python-package.yml` 在 PR、`main` push 和手工触发时构建一次产物，
  运行 `twine check --strict`、内容白名单审计，并分片执行 Windows Python 3.10–3.13 与
  Ubuntu/macOS Python 3.13 的 wheel/sdist 基础和 MCP 干净安装验证。
- [x] `.github/workflows/publish-python-package.yml` 提供三个显式阶段：上传 GitHub Release
  资产、Trusted Publishing 到 TestPyPI、Trusted Publishing 到 PyPI。后两阶段分别验证
  上一层存在逐字节/同哈希产物，上传后从公共索引下载 wheel 并执行 MCP 安装 smoke。只有
  GitHub Release 阶段从标签构建一次；后续阶段复用并核验这些 immutable 资产，避免归档
  时间戳导致同一源码的重复构建哈希不同。
- [x] 所有第三方 Actions 固定到核验过的完整提交 SHA；构建 job 只读仓库，只有 GitHub
  资产 job 获得 `contents: write`，只有索引发布 job 获得 `id-token: write`。
- [x] 构建与 `twine` 工具链由 `requirements-package-build.txt` 完整哈希锁定，构建使用
  `--no-isolation`，避免 PEP 517 再解析浮动 backend；产物审计将 wheel、sdist 与标签
  提交的 Git blob 中 30 个运行文件逐字节比较，避免工作树换行转换或构建时修改影响依据。

## 后续任务与完成标准

1. **远端配置（部分完成）**：GitHub `testpypi`、`pypi` environments 已创建，均只允许
   `main`；`pypi` 已要求 `Yi-luo-hua` reviewer。仍须在 TestPyPI 和 PyPI 为仓库、
   environment、工作流文件配置 pending Trusted Publisher。不得创建长期 token 作为临时替代。
2. **候选版本**：根据 A–H 的用户可见变化确定下一个 lockstep 版本，更新 Cargo、桌面配置、
   lockfile 和 release notes；完成桌面发布门禁后创建指向候选提交的 annotated tag。
3. **GitHub 资产**：从默认分支手工运行 `Publish Python package`，选择
   `github-release`。下载四个资产并反向验证 manifest、checksum、tag peeled SHA。
4. **TestPyPI**：选择 `testpypi`；必须由对应 environment 审批和 OIDC 发布。工作流自动
   验证 GitHub 资产、索引 SHA-256、公共下载及干净安装 smoke。
5. **PyPI**：TestPyPI 精确产物验证通过后选择 `pypi`。生产 environment 应要求人工审批；
   工作流拒绝 TestPyPI 缺失或哈希不同的候选，并在上传后复验 PyPI。
6. **稳定后评估**：至少一个正式版本验证升级、卸载和入口稳定后，再决定是否增加
   `server.json`、MCP Registry 或独立 Python 版本。它们不阻塞 H 的首次包发布。

## 本地复核

发布脚本不持有凭据。身份与现有候选产物可按以下方式检查：

```powershell
python scripts/check_package_release.py
python scripts/check_package_release.py `
  --wheel .runlogs/rename-fix-artifacts/bilibili_crawler-3.3.0-py3-none-any.whl `
  --sdist .runlogs/rename-fix-artifacts/bilibili_crawler-3.3.0.tar.gz `
  --manifest .runlogs/python-package-manifest.json `
  --checksums .runlogs/SHA256SUMS
```

Windows 工作树可能因 Git CRLF 转换而与 tag blob 不同；`--source-ref` 是发布 CI 的显式门禁，
本地验证该门禁时应从 `git archive` 或 `core.autocrlf=false` 的干净 checkout 构建，不应把换行
差异放宽为文本等价。

`check_package_release.py --tag vX.Y.Z --require-head-tag --require-ancestor-of origin/main` 会拒绝
轻量标签、版本不一致、标签未指向当前提交或提交不属于默认分支。远端索引验证只读取公开
JSON API，不上传文件，也不读取本机 PyPI 凭据。
