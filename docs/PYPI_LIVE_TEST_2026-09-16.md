# PyPI 包实测记录（2026-09-16）

从 PyPI 安装 `bilibili-crawler[mcp,analysis]`，在干净 venv 中用真实 B 站数据和真实模型跑完
CLI 与 MCP 两条通路，并用浏览器里的已登录账号做对照验证。补上 [MCP 实测记录](MCP_LIVE_TEST_2026-09-15.md)
「未覆盖」一节留下的三项：`pip install` 后的两个入口、动态 / 专栏链接、AV 号。

## 环境

- Windows 11，CPython 3.13.0，新建 venv（不复用仓库 `.venv`，工作目录在 checkout 之外）。
- `pip install "bilibili-crawler[mcp,analysis]"` → **3.6.0**（PyPI 当前可见 3.4.0 / 3.5.0 / 3.6.0），
  `pip check` 无冲突；`mcp==2.1.0`、`jieba 0.42.1`、`wordcloud 1.9.6`。
- 全程 `BILIBILI_AGENT_RUNS_DIR` 指向临时目录；仓库 `analysis-runs/` 与
  `%LOCALAPPDATA%\BilibiliCrawler\analysis-runs` 均只读不写（后者只跑过 `doctor` / `list-runs`）。
- LLM：自动发现的桌面 profile，`deepseek-v4-flash`。
- 对照通路：浏览器中已登录的 B 站账号（Lv6），直接调同一批 Web API 比对返回字段。
- 样例：视频 `BV15QtG6PEzh`（`av117196336399081`，评论 1630 条）、
  专栏 `cv53029809`、动态 `t.bilibili.com/1248537385154641922`（120 评论）与
  `t.bilibili.com/1248549574233030659`（0 评论）。

## 结果

| 场景 | 结果 |
|---|---|
| 干净 venv 安装 `[mcp,analysis]`、`pip check` | 通过 |
| `doctor`（MCP / runs 目录 / profile 发现） | 通过：`ok: true`，不显示 Key |
| `doctor --check-provider` | 通过：GET /models 200 |
| `list-runs` / `status --run-id` / `status` 无参 | 通过（无参返回 `INVALID_INPUT`，符合设计） |
| 完整 URL、裸 `BV15QtG6PEzh`、`av117196336399081` | 通过：三种写法都命中同一视频 |
| 专栏 `https://www.bilibili.com/read/cv53029809` | 通过：12 条 |
| 动态 `https://t.bilibili.com/1248537385154641922` | 通过：85 条（主 60 + 回复 25） |
| 分页：`--max-pages 5 --no-replies` | 通过：150 条、150 个唯一 ID、0 重复，6.3s |
| 楼中楼：1 页含回复 | 通过：181～184 条（主 30 + 回复 151～154），8s |
| `--sort-mode 2` 热度排序 | 通过：前 3 条与登录态站内 `mode=2` 顺序逐条一致 |
| CSV 导出 | 通过：UTF-8 BOM + CRLF + 中文表头，Excel 可直接打开 |
| `analyze-run --sample-size 20` | 通过：18s，summary 已包 `<untrusted-data>` |
| `analyze-run --strategy all` | 通过：181 条 / 3 批 / 84s（但见问题 5） |
| `crawl-and-analyze` 专栏端到端 | 通过：12 条爬取 + 分析，18s |
| `analyze-run` 指向无评论的 run | 通过：`NOT_FOUND`，提示先完成爬取 |
| MCP：`bilibili-crawler-mcp` 控制台脚本（本次新覆盖） | 通过：握手成功，7 工具 |
| MCP：`crawl_comments` / `list_runs` / `get_task_status` | 通过 |
| MCP：并发二次调用 | 通过：`[BUSY]` |
| MCP：运行中 `delete_run` | 通过：拒绝并提示先 stop |
| MCP：`stop_task` → cancelling → cancelled；重复 stop | 通过：终态幂等 |
| MCP：进度通知 | 通过：单调、中文正常（但见问题 10） |
| MCP：`analyze_run` 传 `../../etc` | 通过：`INVALID_INPUT` |
| API Key 泄露扫描（42 个 run 文件 + stderr） | 通过：0 处命中 |
| 包资源 `stopwords.txt` | 通过：随包安装，32 词 |
| 默认用户数据目录解析 | 通过：`%LOCALAPPDATA%\BilibiliCrawler\analysis-runs`（但见问题 3） |

## 修复状态（2026-09-16，同日在 main 上修复）

下表按本文档的问题编号。修复针对源码，PyPI 上的 3.6.0 仍是上述行为，需下个版本发布后生效。

| # | 问题 | 状态 |
|---|---|---|
| 1 | CLI/MCP 无法登录，地域地图必空 | 已修：新增 `BILIBILI_COOKIE` / `--cookie`，并在爬取和分析两处给出 warning，报告空段落改为说明文字 |
| 2 | `delete_run` 不传 run_id 报错 | 已修：`run_id: str = ""` |
| 3 | `delete_run` 会删到桌面数据 | 已缓解：工具描述、instructions 与 MCP.md 写明作用域，并给出隔离办法；目录本身未改 |
| 4 | `[analysis]` extra 名不副实 | 已修（文档）：README 与包边界文档写明它只服务桌面/sidecar，安装示例改为 `[mcp]` |
| 5 | 多批深度分析用「；」硬接 | 已修：改为按批分段落，去重，不再出现 `。；` |
| 6 | 0 评论被判为链接问题 | 已修：目标解析成功时给出「目标可访问但没有评论」 |
| 7 | 无法识别的输入留下空壳 run | 已修：受理阶段返回 `INVALID_INPUT`，不创建 run |
| 8 | `serverInfo.version` 为空 | 已修：懒解析版本号后传给 `MCPServer` |
| 9 | BUSY 文案重复 task_id | 已修 |
| 10 | 进度通知停在 14% | 已修：终态补一条 100% |
| 11 | 回复正文带「回复 @用户名 :」 | 已修：只在分析侧剥离，导出的 CSV/JSON 保持原文 |
| 12 | 没有 `--version` | 已修：`--version` + `doctor.version` |
| 13 | GBK 控制台帮助乱码 | 未改代码（强制 UTF-8 会让 936 控制台反而更糟），README 给出 `-X utf8` / `PYTHONIOENCODING` 办法 |
| 14 | README 功能清单是桌面的 | 已修（文档）：PyPI 段落写明 CLI/MCP 的能力边界 |

回归：`python -m unittest discover -s tests` 由 366 增至 404 个测试全绿；新增
`tests/test_bilibili_cookie.py`（含 loopback HTTP 真实往返）与
`tests/test_analysis_presentation.py`。Cookie 与分析呈现的新测试都验证过「去掉修复即变红」。

改动后用真实 B 站数据复验：无法识别的输入与空间链接在受理阶段被拒且不建 run；匿名爬取
184 条带出 warning，进度收在 100%；`--strategy all` 的报告里 `。；` 出现 0 次，地域段落有说明；
MCP 侧 `serverInfo.version='3.6.0'`、`delete_run` 的 `required` 为空、BUSY 只提一次 task_id。
另用一个**无效** Cookie 打真实接口，确认请求带 Cookie 不影响爬取，且会提示「会话可能已失效」。

未验证：**有效** Cookie 打真实 api.bilibili.com 能否拿到属地。SESSDATA 是 HttpOnly，
浏览器里取不到，测试用的是 loopback 往返 + 登录态浏览器对同一接口的对照。自行确认：

```powershell
$env:BILIBILI_COOKIE = "<浏览器里 bilibili.com 的完整 Cookie>"
bilibili-crawler crawl-comments "https://www.bilibili.com/video/BV15QtG6PEzh/" --max-pages 1
# warnings 为空即为成功；comments.json 里 ip_location 应有值
```

## 问题

### 1. CLI / MCP 拿不到评论 IP 归属地，地域地图必然为空（高）

- 现象：`ip_location` 在 181 条评论里 **181 条为空**；分析产物
  `ip_location_coverage: 0.0`、`region_counts: []`、`overseas_region_counts: [{未知: 181}]`。
- 对照：浏览器登录态下请求同一个 `x/v2/reply/main`，前 10 条 `reply_control.location` **10/10 有值**
  （贵州 / 上海 / 四川 / 陕西 …）。用装好的包以匿名身份请求同一接口，10/10 为 `None`。
  所以不是解析问题，是登录态问题。
- 根因：`AgentService.__init__` 固定 `BilibiliAPI()` 匿名实例
  （[agent_service.py:261](../bilibili_crawler/service/agent_service.py)）。桌面 sidecar 走
  `self._services.api`（[sidecar.py:87](../bilibili_crawler/sidecar.py)），扫码登录后同一个对象带 Cookie；
  CLI / MCP 这条路没有任何注入点——没有 `--cookie` 参数、没有 MCP 工具字段、没有环境变量，
  sidecar 登录成功也只把 cookie `emit` 给桌面前端，不落盘。
- 影响：`region_map` 是默认开启的 6 个模块之一，pip 用户拿到的 `report.md` 里
  `### 国内 / 地图数据` 永远是空段落。README 只写「建议先扫码登录」，没说 CLI/MCP 根本无法登录。
- 建议：给 CLI 加 `--cookie` / 环境变量（如 `BILIBILI_COOKIE`），MCP 侧至少让 `region_map`
  在覆盖率为 0 时写一条 `warnings`，报告里替换空段落为说明文字。

### 2. `delete_run` 不传 run_id 仍然报错（中，2026-09-15 问题 1 未修复）

- 在**已发布的 3.6.0**上复现：`delete_run(prune_to=50)` →
  `1 validation error for delete_runArguments / run_id Field required`；`required=['run_id']`。
- [MCP.md:161](MCP.md) 仍写「不传 run_id 时生效」。绕行仍是显式传 `run_id=""`（实测可用）。
- 与上次记录一致，改 `run_id: str = ""` 即可。

### 3. MCP 的 `delete_run` 默认会删到桌面应用的数据（中，新增）

- pip 安装的 CLI 默认 runs 目录是 `%LOCALAPPDATA%\BilibiliCrawler\analysis-runs`，
  而桌面应用就安装在 `%LOCALAPPDATA%\BilibiliCrawler`（同目录下有 `bilibilicrawler_desktop.exe`、
  `uninstall.exe`）。本机实测：不设环境变量时 `list-runs` 直接列出桌面产生的 10 条 run。
- 因此一个接入 MCP 的 agent 调用 `delete_run(run_id="", prune_to=N)` 做「清理自己的 run」时，
  删掉的是用户桌面应用里的历史分析。工具描述里没有这层提示。
- 建议：`delete_run` 的批量分支明确说明作用域，或让 MCP 默认使用独立子目录。

### 4. `[analysis]` extra 装了词云，但 CLI / MCP 永远不会生成词云（中，新增）

- README 写「词云/分词选 `analysis`」，[PYTHON_PACKAGE_BOUNDARY.md](PYTHON_PACKAGE_BOUNDARY.md)
  写「`analysis` extra 提供分词/词云」。
- 实际 `AGENT_CHART_KEYS`（[models.py:80](../bilibili_crawler/service/models.py)）**刻意排除**
  `word_cloud`，注释写明「agent 用不了 PNG」。CLI 的 `analyze-run` 没有模块开关，
  MCP 工具也没有 `chart_keys` 参数，所以这个 extra 在包的两个入口上完全无效。
- 实测产物 `word_counts: []`、无 `word_cloud_image` 字段。
- 直接调 API 验证能力本身是好的：`_build_word_counts` + `_build_word_cloud_image` 产出
  169 KB PNG，字体自动落到 `C:\Windows\Fonts\simhei.ttf`，冷启动 11.7s。
- 代价：`[analysis]` 会拖进 numpy + matplotlib + fontTools（约 25 MB wheel），对 CLI/MCP 用户是纯负担。
- 建议：要么给 CLI/MCP 一个显式开关，要么在 README 和 boundary 文档里写明这个 extra 只服务桌面/sidecar。

### 5. `strategy="all"` 多批时深度分析只是把几段文字用「；」拼起来（中，新增）

- `_compact_analysis_segments`（[analysis_processor.py:1366](../bilibili_crawler/processor/analysis_processor.py)）
  对多批结果只做 `"；".join(clean[:5])`。
- 181 条 / 3 批的实测报告里，社会学一节是三段各自独立写成的分析被直接串联，出现
  `…作为群体归属标志。；评论将大学重新定义为…` 这种 `。；` 断口，且三段反复论证同一件事
  （「蓄水池 / 筛选器」出现三次），直引号 `'` 与全角 `“` 混用。
- 对比：`summary` 走的是 `_compact_summary`，有一次真正的汇总调用（进度里能看到「总结整合」），
  输出连贯。`deep_analysis` 和 `custom_results` 没有这一步。
- 建议：深度分析与自定义模块也走一次归并，或至少按批分小标题呈现，别用「；」硬接。

### 6. 评论数为 0 的目标被判成失败，且错误文案误导（低，新增）

- 实测动态 `t.bilibili.com/1248549574233030659`（站内评论数确实是 0）：
  `status: failed`、`CRAWL_FAILED`、`没有爬到任何评论，请检查链接是否为公开可访问的视频/动态/专栏。`
- 链接是公开可访问的，只是没人评论。CLI 退出码 1，agent 会当成链接有问题去重试。
- 注：这是 agent policy 的 `empty_crawl_is_success: false`，桌面侧是 true。至少应把文案
  和「目标不可访问」区分开。

### 7. 无法识别的输入也会留下 failed run 目录（低，2026-09-15 问题 3 未修复）

- `"not a url at all"`、`"BV1111111111"`、`https://space.bilibili.com/946974` 三种输入
  都先建 run 目录再以 `CRAWL_FAILED` 结束，错误统一是「无法解析目标内容的OID，请检查链接或网络」。
- 本次 8 个 run 目录里有 2 个是这种空壳。

### 8. `serverInfo.version` 仍为空（低，2026-09-15 问题 5 未修复）

- 3.6.0 的 initialize 返回 `name='bilibili-crawler' version=''`。宿主看不到服务版本。

### 9. BUSY 文案里 task_id 出现两次（低，2026-09-15 问题 4 未修复）

- 原文：`[BUSY] 已有任务正在运行（task_id=task-…），… 请等待其完成或先调用 stop_task。（当前任务 task_id=task-…）`

### 10. `crawl_comments` 的进度通知最高只到 14%（低，新增）

- 纯爬取任务的三条通知是 8% / 12% / 14%，随后工具直接返回 `done: true`。
  百分比预算是按「爬取 + 分析」整条链路划分的，只爬取时宿主的进度条会停在 14% 然后跳完成。

### 11. 回复正文保留「回复 @用户名 :」前缀（低，新增）

- 151 条回复里 57 条（38%）的 `content` 以 `回复 @某某 :` 开头。
- 后果一：词频里 `回复` 排到第 2（仅次于「大学」），词云被污染；32 词的 `stopwords.txt` 里没有它。
- 后果二：被 @ 的用户名会随正文一起进入发给 LLM 的文本。
- 建议：入库时剥掉该前缀（或单独存成字段），并把「回复」加入停用词。

### 12. CLI 没有 `--version`，包没有 `__version__`（低，新增）

- `bilibili-crawler --version` → argparse 报 `the following arguments are required: command`，退出码 2。
- `import bilibili_crawler; bilibili_crawler.__version__` → 属性不存在。
- 用户只能靠 `pip show bilibili-crawler` 确认装了哪个版本，报 issue 时不方便。

### 13. GBK 控制台下中文帮助乱码（信息）

- PowerShell（UTF-8 输出）正常；在代码页 936 的终端（如 Git Bash）里
  `bilibili-crawler --help` 的中文子命令说明全是乱码。
- `doctor` 用 `ascii_safe=True` 专门规避了这个问题，argparse 的 help 没有同等保护。

### 14. README 的功能清单是桌面应用的，pip 用户会错配预期（信息）

- README 列了「动态爬取：支持用户空间动态和关注页动态流」「扫码登录」「可视化图表」「词云图」，
  紧接着就是 `pip install "bilibili-crawler[mcp,analysis]"`。
- 实际 pip 包的 CLI/MCP 只做评论爬取 + 文本分析：`DynamicCrawler` 打进了 wheel 但没有任何入口
  （`AgentService` 只用 `CommentCrawler`），`https://space.bilibili.com/946974` 实测报
  `CRAWL_FAILED`；扫码登录只在 sidecar 里，图表数据只到 JSON，没有渲染。
- 建议：PyPI 那一段单独说明 CLI/MCP 的能力边界。

## 观察（非缺陷）

- 匿名爬取速度不错：1 页含楼中楼 181 条 8s，5 页不含回复 150 条 6.3s。
- `strategy="all"` 181 条 84s、3 批，超过 MCP 默认 `wait_seconds=90` 的余量很小，
  实际用 MCP 跑全量基本都要转轮询。
- 协议版本本次协商到 `2025-11-25`（上次记录是 `2026-07-28`），由客户端 SDK 决定，不是服务端问题。
- 同一视频两次 1 页爬取拿到 181 / 184 条，是评论区自然增长，不是去重问题
  （5 页 150 条唯一 ID 无重复）。
- `run_id` 路径穿越、未知 task_id、运行中删除、重复 stop 这些边界仍然守得住，
  与 2026-09-15 的结论一致。

## 未覆盖

- 桌面应用本体（本次只测 pip 包的 CLI / MCP 两个入口）。
- 扫码登录流程与登录态下的完整爬取（只用浏览器验证了接口层面的字段差异）。
- 真实 provider 故障下的各 `LLM_*` 错误码。
- Windows 以外的平台；Python 3.10 / 3.11 / 3.12 上的已发布产物。
