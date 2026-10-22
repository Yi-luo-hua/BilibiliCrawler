# v3.9.0 发布记录

> 状态：**2026-10-23 已公开发布至 GitHub Release**。发布说明见 [RELEASE_NOTES_3.9.0.md](RELEASE_NOTES_3.9.0.md)，下载见 [GitHub Release v3.9.0](https://github.com/Yi-luo-hua/BilibiliCrawler/releases/tag/v3.9.0)。

## 范围

- 基线为 v3.8.0，包含启动优化提交 `8de982d`。
- 桌面、CLI、MCP 和 Python 包由 `desktop/src-tauri/Cargo.toml` 派生版本 3.9.0。
- 按上一版范围发布至 GitHub Release：Windows x64 安装包、安装包 SHA-256、installer-payload-manifest.json、wheel、sdist、SHA256SUMS 和 python-package-manifest.json。
- Windows 后端使用独立 CPython 3.13.15 x64 和哈希锁定依赖重新构建；Python 发布资产由 annotated tag 工作流一次构建并审计。

## 已有启动优化验证

- 版本准备前，同一机器、同一快捷方式、保留缓存的启动平均由 7.41 秒降至 2.87 秒，三个优化后样本为 3.13、2.76、2.71 秒。
- 37 项前端测试、8 项 Rust release 测试、生产构建与类型检查通过。
- 独立配置目录和虚构密钥验证：启动不改写配置/凭据，实际编辑保存与重启恢复正常，凭据保持隐藏，窗口最大化/还原状态同步正常。
- 用户现有配置及凭据文件的内容和修改时间经核对保留。本机已安装 exe 以备份方式替换为优化构建；此操作不等同于 3.9.0 安装器覆盖升级验收。

## 本版发布门禁

| 检查 | 结果 |
|---|---|
| 本地回归与依赖审计 | Python unittest 运行 405 项，6 项按条件跳过，其余通过；前端 37/37；锁定依赖的 Rust release 测试 8/8。Vite 7.3.7 生产构建和 TypeScript 检查通过，pnpm audit 已知漏洞为 0。 |
| Windows 构建与包内文件 | 独立 CPython 3.13.15 x64 构建；7-Zip 完整性检查通过，解包 ProductVersion/FileVersion 均为 3.9.0。1,299 个后端文件逐一通过大小/哈希检查；相对官方 3.8.0 清单，0 移除、0 新增、3 内容变化。主程序与构建输出只存在 Tauri 三字节 UNK/NSS bundle type 标记差异。 |
| 包内后端与桌面启动 | 冻结 sidecar 发出 ready、渲染引擎就绪，并成功响应 session.status，正常退出。解包后的 3.9.0 桌面程序在独立配置与虚构密钥下正常显示界面，本次保留缓存的 ShellExecute 启动到渲染引擎就绪为 2.745 秒，其中渲染初始化 194 ms；启动配置/密钥写入为 0，文件哈希、修改时间和隐藏属性保持。该单次包验证不作为新的多次平均值。 |
| 候选提交 CI | [Python package gate 39814644325](https://github.com/Yi-luo-hua/BilibiliCrawler/actions/runs/39814644325) 7/7 项通过。 |
| 标签包审计和干净安装 | [发布工作流 39814792860](https://github.com/Yi-luo-hua/BilibiliCrawler/actions/runs/39814792860) 成功，8 项执行任务通过，2 项索引发布任务按范围跳过。Windows Python 3.10–3.13、Linux/macOS Python 3.13 的 wheel/sdist 基础和 MCP 安装均通过；下载后本地再次通过 31 个运行文件的标签源码绑定、manifest 和 SHA256SUMS 检查。 |
| 资产与公开更新发现 | 草稿阶段和公开后均反向下载全部七个资产，哈希匹配本地 Windows 构建或标签工作流原始文件，并匹配 GitHub asset digest。公开后 releases/latest 返回 v3.9.0、draft=false、prerelease=false；实际客户端 parseRelease/isNewerVersion 能从 3.8.0 识别更新及正确的 x64 安装包地址。 |

## 发布证据

- 实际构建提交和 annotated tag v3.9.0 的目标：`99bd4bf7d27c21caaa58a2bfe6863b69ad13b38b`，属于 main 历史。本记录在发布后以文档提交补齐，标签继续保持在实际构建提交。
- Windows 安装包 `BilibiliCrawler-Setup-3.9.0-x64.exe`：53,648,933 字节，SHA-256 `8f1e82f4c80f4702c922986f30f50d6971f52ad248f1441249092679a127927a`。
- Python wheel `bilibili_crawler-3.9.0-py3-none-any.whl`：121,393 字节，SHA-256 `2e7d19d703f0e0e8681b446b23a63e7bb1192f105c01c3d495f4398d7331d70f`。
- Python sdist `bilibili_crawler-3.9.0.tar.gz`：115,047 字节，SHA-256 `fc661371bc2462f661ff8f6ee3e27eeb5776aabd535a701f8027d7ae37283e63`。
- Python manifest 的 source_commit 与标签目标一致；wheel/sdist 只在标签工作流构建一次，后续校验和上传复用同一组产物。
- Windows 首轮清单检查发现本地旧版 3.6.0 egg-info 元数据被自动收集；已将其移出构建源后完整重建，最终发布包无此残留，清单与上版同为 1,299 个后端文件。
- GitHub Release 于 **2026-10-23 00:45:54（Asia/Shanghai）**公开，设为正式最新版本，包含安装包、安装包 SHA-256、payload 清单、wheel、sdist、SHA256SUMS 和 Python manifest 七个资产。

## 验收边界

本次未用本版安装包覆盖用户现有安装目录，未使用有效 B 站 Cookie 或付费 LLM 凭据完成真实爬取、分析和桌面报告导出。独立目录的包内桌面启动、回归测试及冻结后端 smoke 不能替代这些路径的验收。Windows 安装包未签名。

本次按 GitHub Release 范围发布，未同步至 TestPyPI/PyPI。
