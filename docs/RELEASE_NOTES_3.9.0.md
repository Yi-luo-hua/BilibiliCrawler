# BilibiliCrawler v3.9.0

本版重点修复桌面启动等待，减少启动时的重复写入和窗口状态查询。

## 启动优化

- 恢复配置和 API Key 后不再立即重复保存；实际编辑后仍自动保存。
- 隐藏凭据文件直接使用 Windows 文件属性 API，保留其他属性，避免同步启动 `attrib.exe` 与控制台进程造成数秒等待。
- 配置和密钥并行读取。标题栏复用窗口句柄，按窗口尺寸变化同步最大化状态。
- 同机保留缓存的三次快捷方式启动对照中，“渲染引擎就绪”平均从 7.41 秒提前到 2.87 秒，约减少 61%。这是本机实测，具体时间随设备、负载和缓存状态变化。

## 验证与下载

构建依赖 Vite 升级到 7.3.7，修复 [GHSA-587h-7wmj-h5pm](https://github.com/advisories/GHSA-587h-7wmj-h5pm) 涉及的 Windows 开发服务器路径检查问题。

新增 Windows 回归测试，验证中文路径下的隐藏属性、重复调用、其他文件属性与文件内容保留。独立配置下验证了密钥与配置编辑保存、重启恢复和窗口最大化/还原状态。

GitHub Release 提供 Windows x64 安装包、安装包 SHA-256、后端文件清单，以及 Python wheel/sdist 和校验文件。应用版本统一由 Cargo.toml 派生为 3.9.0。升级前请退出程序并运行安装包。

构建、产物检查和实际覆盖范围记录在 [v3.9.0 发布记录](https://github.com/Yi-luo-hua/BilibiliCrawler/blob/main/docs/RELEASE_3.9.0.md)。本次不涉及爬取节奏或 LLM 请求策略调整；Windows 安装包未签名。
