# Python 可安装包边界（F）

基线 `86f0eae`。本批实现安装边界，不发布到 PyPI、不合并 main、不变更 Cargo 版本。G 再做 wheel/sdist 内容与 Python 3.10–3.13 干净环境矩阵，H 处理公开包名及发布权限。

- 唯一运行实现位于 `bilibili_crawler`。checkout 中的 `src`、`config`、`utils`、`backend` 旧模块只保留薄兼容层；旧/新导入必须共享模块、类型与状态，不能产生两份凭据注册表或 MCP service。wheel 不安装这些通用顶层名字。
- 保留 `python -m backend.agent`、直接 `python backend/sidecar.py`、原桌面协议及构建入口。新增 `python -m bilibili_crawler`、`bilibili-crawler`、`bilibili-crawler-mcp`。包内不通过 sys.path 回到 checkout。
- 本地分发名暂定 `bilibili-crawler`，不表示该名称已在 PyPI 注册。元数据版本由 `desktop/src-tauri/Cargo.toml` 的 package.version 派生，构建时解析；安装后的 CLI 不依赖 Cargo 文件或 Rust 工具链。
- 基础安装支持 CLI/文本分析，核心依赖为 requests 和 Pillow（持久化层校验图片需要）；`mcp` extra 锁定当前 MCP 2.1.0；`analysis` extra 提供分词/词云，`desktop` extra 提供桌面所需 QR/分词/词云组件。不改已锁定桌面依赖。
- 运行时静态词表通过 importlib.resources 加载，并随包及 PyInstaller 产物收集；不得从 cwd 或 checkout 寻找资源。无外置中文字体时沿用现有降级，不打包机器字体。
- 普通安装默认 run/analysis-assets 位于用户数据目录：Windows LOCALAPPDATA/BilibiliCrawler，macOS ~/Library/Application Support/BilibiliCrawler，Linux XDG_DATA_HOME/bilibili-crawler（默认 ~/.local/share）。不得尝试向 site-packages 或 cwd 写入。
- 源码 checkout 保留现有根目录数据与开发 profile 发现，避免旧 run 失联；冻结桌面仍保留原稳定目录与复制迁移行为。环境变量 BILIBILI_AGENT_RUNS_DIR/BILIBILI_AGENT_CREDENTIALS 保持最高优先级；不自动移动或删除用户数据。
- 新安装 profile 默认位于平台配置目录（Windows 用户数据/config；macOS 用户数据/config；Linux XDG_CONFIG_HOME/bilibili-crawler）。credentials/ui 必须保持同目录、按字段覆盖；保留 Windows 桌面默认安装位置的发现。只读 doctor 不创建目录或配置。
- 词云的 matplotlib 缓存使用平台用户缓存目录，显式 MPLCONFIGDIR 优先；不写入安装代码目录。其余已有第三方临时缓存保持原规则。
- F 验收：旧/新导入身份、旧 CLI/桌面协议全量回归、安装布局路径隔离、词表读取、版本/依赖元数据、当前 Python 的最小安装与两种入口；真实外网和多版本发布矩阵不能由本批离线测试替代。

本机安装 smoke 可复现命令（在仓库根目录运行；构建环境须已有 setuptools/wheel）：

```powershell
python -X utf8 -m pip wheel --no-deps --no-build-isolation --wheel-dir .runlogs/f-artifacts .
python -X utf8 scripts/check_package_install.py .runlogs/f-artifacts/bilibili_crawler-3.3.0-py3-none-any.whl
```

checker 将 wheel 安装到临时目录，在无关 cwd 中运行实际命令；使用合成凭据和外部服务夹具，
走完真实服务层的爬取、分析、落盘与脱敏检查。核心流程阻断可选依赖导入，安装有 MCP SDK 时
额外验证两种入口的真实 stdio 握手。它复用当前解释器依赖，输出
`clean_dependency_environment: false`，不是 G 的干净依赖环境验收。版本变化后需替换产物文件名。
