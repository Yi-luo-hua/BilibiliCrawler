# BilibiliCrawler v3.7.0

本版修复评论抓取与全量分析的完整性问题，并扩展 CLI/MCP 的爬取和分析能力。

## 评论抓取

- 修复楼中楼只抓第一页的问题。B 站回复接口每页最多返回 20 条，旧版只查看不存在的 `cursor` 字段，因此一条主评论下超过 20 条的回复会被静默截断。现在按 `page.count` 翻页，并在没有总数时以空页或重复页结束。
- CLI/MCP 不再限制主评论最多 50 页；`max_pages=0` 表示抓完整个评论区。默认仍为 5 页。楼中楼回复全部抓取，不计入该页数。
- 桌面端仍使用自己的页数输入范围，`0` 的完整爬取模式只适用于 CLI/MCP。

## 分析

- 修复桌面端选择“全量分析”后，服务层把它当作抽样处理的问题。现在全量分析会处理本次取得的全部评论。
- CLI/MCP 的 `sample_size` 和 `batch_size` 只需为正整数；超过 2000 条的抽样会提示预期耗时和费用，不会自动缩小样本。完整评论文本送入 LLM，主题、风险、洞察、代表评论、总结、词云词数、时间趋势及各批深度分析结果不再被共享分析层截断。
- `crawl_and_analyze` 可选择 `strategy`；分析入口支持 `batch_size`、`chart_keys`（包括 `word_cloud`）与 `custom_modules`。词云需要安装 `analysis` extra，例如 `pip install "bilibili-crawler[mcp,analysis]==3.7.0"`。
- 桌面端的图表展示范围和自定义模块选择规则保持原有行为。互动排行仍展示前 10 条；词云渲染仍有 30 秒保护超时。

## CLI/MCP 修复

- 增加 `BILIBILI_COOKIE` 与 CLI `--cookie`。B 站只在带有效会话的请求中返回 IP 属地；匿名或会话失效时会给出相应提示。Cookie 不自动保存，并按凭据规则从日志与运行产物中脱敏。
- 修复 `delete_run` 不传 `run_id` 时无法按 `prune_to` 清理的问题；无效目标在受理时就会被拒绝，空评论目标会给出准确提示。
- 纯爬取任务的最终进度现在到达 100%；多批分析报告按实际批次分段并去重。分析前会从回复正文中去掉“回复 @用户”前缀，导出的原始评论不变。
- 测试运行目录已隔离；各测试模块可单独运行。

## 使用与限制

Windows x64 安装包、Python wheel 和 sdist 随 [GitHub Release](https://github.com/Yi-luo-hua/BilibiliCrawler/releases) 提供。普通 CLI 不需要 MCP 依赖；MCP 使用 `bilibili-crawler[mcp]`；需要词云时再加 `analysis` extra。升级桌面端时请退出应用并运行新安装包。

请求间隔、单次爬取请求超时和重试次数，以及 LLM 请求的超时和重试次数保持原有保护值。大量评论的完整爬取和分析可能耗时较长，并产生 LLM 费用。B 站接口自身的每页数量、目标类型及登录要求仍然适用。

**Windows 安装包未做代码签名**，Windows 可能显示 SmartScreen 提示；可核对 Release 中的 SHA-256 校验文件。构建、验证结果与未覆盖的路径记录在 [v3.7.0 发布记录](RELEASE_3.7.0.md)。
