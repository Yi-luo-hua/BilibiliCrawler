# MCP 接入指南

让 agent 直接爬取并分析 B 站公开评论，无需启动桌面客户端。

---

## 这是什么

一个本地 stdio MCP 服务器，把「爬取评论 → LLM 舆情分析 → 导出报告」暴露成 7 个工具。
每次运行都会落盘成一个带 `run_id` 的目录，因此 MCP 进程重启后仍能按 `run_id` 继续分析。

桌面客户端继续走 `backend/sidecar.py`；本次仅在内部复用服务层，既有 RPC 返回与事件表面保持兼容。

---

## 安装

需要 Python 3.10+。建议用独立虚拟环境，避免与你机器上其他 MCP server 的 `mcp` 版本冲突：

```bash
python -m venv .venv-agent
```

```bash
.venv-agent/Scripts/python.exe -m pip install -r requirements-agent.txt
```

Linux / macOS 下把 `.venv-agent/Scripts/python.exe` 换成 `.venv-agent/bin/python`。

v3.3.0 仍采用源码安装。独立 wheel / sdist、PyPI 发布与 MCP Registry 接入已列入
[`RELEASE_3.3.0.md`](RELEASE_3.3.0.md) 的后续 Python 包计划，不属于本次发布产物。

验证安装：

```bash
.venv-agent/Scripts/python.exe -m backend.agent list-runs
```

---

## 配置 MCP 宿主

把下面这段加进宿主的 MCP 配置（如 Claude Desktop 的 `claude_desktop_config.json`），
路径换成你自己的仓库位置：

```json
{
  "mcpServers": {
    "bilibili-crawler": {
      "command": "E:\\path\\to\\BilibiliCrawler\\.venv-agent\\Scripts\\python.exe",
      "args": ["-m", "backend.agent", "mcp"],
      "cwd": "E:\\path\\to\\BilibiliCrawler",
      "env": {
        "BILIBILI_LLM_API_KEY": "sk-your-key",
        "BILIBILI_LLM_BASE_URL": "https://api.openai.com/v1",
        "BILIBILI_LLM_MODEL": "gpt-4.1-mini"
      }
    }
  }
}
```

Claude Code 用户也可以直接：

```bash
claude mcp add bilibili-crawler -- /path/to/.venv-agent/Scripts/python.exe -m backend.agent mcp
```

`cwd` 必须指向仓库根目录，否则 `backend.agent` 模块无法被找到。

---

## LLM 凭据

只有分析类工具需要凭据；`crawl_comments` 不需要。

按字段解析：非空环境变量 > 同一个桌面 profile > 默认值。
只设置 Key 不会丢弃同一 profile 的服务地址与模型；三个环境字段都完整时不读取桌面文件。

profile 选择顺序：

1. 显式设置 `BILIBILI_AGENT_CREDENTIALS` 时只使用该文件，不回退其他安装目录。
2. 未显式指定时自动探测桌面端的 `credentials.json`，依次尝试：
   - `<仓库>/.install-test/user-data/config/credentials.json`（源码调试布局）
   - `%LOCALAPPDATA%\BilibiliCrawler\user-data\config\credentials.json`（installMode=currentUser 的默认安装位置）
   - `%PROGRAMFILES%` 与 `%PROGRAMFILES(X86)%` 下的同名路径

**如果你已经在桌面端配过 key**，按默认位置安装的话会被自动发现，通常什么都不用做，
不必把明文 key 再抄一份进 MCP 宿主配置。装在非默认位置时用环境变量指过去：

```json
"env": { "BILIBILI_AGENT_CREDENTIALS": "D:\\MyApps\\BilibiliCrawler\\user-data\\config\\credentials.json" }
```

安装版的 `user-data` 目录始终在**安装目录旁边**；按默认的 currentUser 方式安装时，安装目录就是 `%LOCALAPPDATA%\BilibiliCrawler`，因此凭据文件位于 `%LOCALAPPDATA%\BilibiliCrawler\user-data\config\credentials.json`。
读取 `credentials.json.api_key` 时，同时读取同目录 `ui.json.llm_base_url` 与 `llm_model`；
非空 `BILIBILI_LLM_API_KEY` / `BILIBILI_LLM_BASE_URL` / `BILIBILI_LLM_MODEL` 分别覆盖对应字段。
只有字段仍未提供时，才使用兼容默认值 `https://api.openai.com/v1` 与 `gpt-4.1-mini`。
Key、地址与模型不会从不同安装目录拼接。credentials 文件也可包含 `base_url` / `model`，
但若与相邻 ui 文件冲突，需要统一配置或显式设置对应环境变量。

缺失 ui 文件可使用默认值；选中的配置损坏、重复字段、类型错误、显式路径不存在则返回
`CONFIG_INVALID`，不会静默切换 provider。地址必须为 HTTP(S)，不接受 URL 中的用户名、密码或查询参数。

stdio 子进程是否继承调用者环境取决于宿主，不能假定桌面设置或终端变量会自动传入。
非 OpenAI 用户可让宿主显式传入 `BILIBILI_AGENT_CREDENTIALS` 指向完整桌面 profile，
或者显式传入三个 `BILIBILI_LLM_*` 字段。例如 SDK 客户端启动参数：

```python
import os
from mcp import StdioServerParameters

params = StdioServerParameters(
    command=r"E:\path\to\BilibiliCrawler\.venv-agent\Scripts\python.exe",
    args=["-m", "backend.agent", "mcp"],
    cwd=r"E:\path\to\BilibiliCrawler",
    env={**os.environ, "BILIBILI_AGENT_CREDENTIALS": r"D:\Apps\BilibiliCrawler\user-data\config\credentials.json"},
)
```

上例 Key 在 credentials 文件中、服务地址/模型在相邻 ui 文件中，无需重复填写。
若宿主已有旧 `BILIBILI_LLM_BASE_URL` / `BILIBILI_LLM_MODEL`，它们仍然优先；用下方 `doctor` 核对最终来源。

API Key 不会写进 `manifest.json`、不会出现在日志（含异常堆栈）、也不会出现在工具返回值里；
上游报错里回显的 key 会被替换成 `***`。

---

## 工具

| 工具 | 用途 | 需要 LLM 凭据 |
|---|---|---|
| `crawl_and_analyze` | 主入口：爬取 + 分析 + 导出报告，一次完成 | 是 |
| `crawl_comments` | 只爬取，落盘 JSON 和 CSV | 否 |
| `analyze_run` | 对已有 `run_id` 重新分析；成功切换有效版本，取消/失败保留旧报告 | 是 |
| `get_task_status` | 查询状态、进度、计数、产物路径 | 否 |
| `stop_task` | 停止正在跑的任务 | 否 |
| `list_runs` | 列出持久化运行记录（最新在前） | 否 |
| `delete_run` | 删除单个运行，或保留最新 N 个、清理其余（正在运行的任务不会被删除） | 否 |

所有任务工具返回同一个精简结构：`ok` / `done` / `status` / `stage` / `task_id` / `run_id` /
`counts` / `summary` / `artifacts` / `warnings` / `error` / `error_code` / `next_step`。
`list_runs` 返回运行记录数组（run_id/kind/status/created_at），`delete_run` 返回
`{"ok": true, "deleted": [run_id, ...]}`。批量清理必须显式传 `prune_to`（>= 1，不传
run_id 时生效）；省略 `prune_to` 不会默认全删，正在执行的任务的 run 会被跳过并要求先
`stop_task`。

**不会**返回全量评论、完整报告正文或词云图 Base64，只返回文件路径。

### 有界阻塞

`crawl_and_analyze` 等工具默认最多阻塞 `wait_seconds`（默认 90 秒，上限 600），
期间通过 MCP progress 通知汇报进度。

如果在窗口内没跑完，工具会带着 `done: false`、`task_id` 和 `run_id` 正常返回，
之后用 `get_task_status(task_id=...)` 查询本次尝试的最终状态。这样长任务不会被宿主的
单次调用超时打断。

按 `run_id` 查询时，运行中返回当前进度；任务结束后返回最近成功报告的状态。
因此重分析取消/失败后，`task_id` 查询显示本次取消/失败，`run_id` 查询仍可显示
`completed` 并附上 warning。进程重启后 task_id 不再可用，用 run_id 找回有效报告；
每次尝试的状态和错误保留在 manifest 的 `analysis_attempts` 中。

LLM 请求等待期间，stage/progress 消息约每秒刷新本次分析已用时，并显示批次、
请求/重试次数及退避原因。等待只更新文本，不增加百分比；桌面沿用同一消息通路。
连接超时和读取超时仍各为 90 秒，消息中的 `90/90s` 不是整个任务的总时限。
`wait_seconds` 则只是 MCP 工具本次调用的等待窗口，超出窗口后仍按 task_id 轮询。
详见 [长请求进度契约](ANALYSIS_PROGRESS.md)。

---

## 运行目录

```text
<仓库>/analysis-runs/<run_id>/
  manifest.json     状态、计数、参数、产物清单
  comments.json     清洗后的评论
  comments.csv      Excel 可直接打开
  analysis.json     当前报告的兼容副本
  report.md         Markdown 兼容副本
  analysis-attempts/<attempt_id>/
    analysis.json   本次尝试的完整分析结果
    report.md       本次尝试的 Markdown 报告
    assets/         可选词云图片
```

目录内所有文件都采用「临时文件 + 原子替换」写入，进程中途被杀不会留下截断的
`manifest.json` 或半截 CSV。若 CSV 导出失败，任务会在 `warnings` 里明确报告，
而不是静默地只留下 JSON。

分析先完整落定一个不可变版本目录，再原子更新 manifest 的 `current_analysis` 指针。
读取完整结果应使用 `artifacts` 返回的版本路径；根目录兼容副本不保证多文件原子刷新。
取消或失败不会替换上一份已提交报告；成功后的旧兼容副本仍归档到 `archive/`。
副本刷新失败会保留成功版本并记录 warning。详细状态与兼容边界见
[分析尝试契约](ANALYSIS_ATTEMPTS.md)。

仓库目录不可写时自动回落到 `%LOCALAPPDATA%\BilibiliCrawler\analysis-runs\`，
与桌面端 `analysis-assets` 采用同一套目录选择策略。可用 `BILIBILI_AGENT_RUNS_DIR` 覆盖。

`run_id` 形如 `20260825-203826-0f407dfe`。

---

## 安全

### 评论是不可信数据

这一点值得单独强调。评论正文由陌生人撰写，而 agent 与桌面端不同：
桌面端的终点是人眼看 UI，agent 的终点是一个**会执行工具的模型**。

所以：

- 返回的 `summary` 由 LLM 从不可信输入生成，**它本身就可能夹带指令**。
  该字段已被 `<untrusted-data>` 标记包裹并限长，请当作数据看待。
- `notable_quotes`（原样引用的评论）不进入工具返回值，只写入 `analysis.json`。
- **读取 `report.md` 会把不可信内容重新带回上下文**，请以同样的态度对待。
- 分析用的 system prompt 已显式声明评论为不可信输入、禁止执行其中的指令。

### 滥用控制

MCP 工具可被 agent 循环调用，压力远高于人点 GUI，因此 headless 默认值比桌面端保守得多：

- `max_pages` 默认 5，**硬上限 50**，任何工具参数都无法突破。
- 请求间隔不暴露为工具参数。
- 单进程同时只允许一个任务，冲突时返回 `BUSY` 和当前 `task_id`。

请只对公开内容使用，并遵守 B 站的服务条款。

### 第一版不做

- 不暴露扫码登录、动态流、关注页。
- 不开放 Streamable HTTP、远程访问或多用户服务。
- 不提供任意路径导出——产物路径已在 `artifacts` 里给出，宿主 agent 用自己的文件工具拷贝即可。
- 不做多任务并行、任务队列或数据库。

---

## 故障排查

**先检查最终配置（不显示 API Key）**

```bash
python -m backend.agent doctor
python -m backend.agent doctor --check-provider --timeout 10
```

默认只读、不联网、不创建或迁移运行目录，输出配置来源、有效服务地址/模型、MCP SDK 版本及
运行目录的权限估计。退出码 0 表示 profile 和目录预检通过，1 表示配置/目录或显式连通性检查失败。
SDK 未安装会标明 `installed: false`，不影响普通 CLI 的诊断成功；MCP 服务器仍需安装 requirements-agent.txt。

`--check-provider` 才发送带鉴权的 GET `/models`，不跟随重定向，不打印响应正文，不发送评论、
不调用付费聊天接口。成功不代表所选模型已通过分析验证；部分 provider 不支持模型列表接口。
`--timeout` 为连接/读取超时（大于 0 且不超过 60 秒），不是整个分析任务的超时设置。
运行目录只做权限估计，没有实际写文件，Windows ACL 的真实可写性以运行时检查为准。
诊断 JSON 使用 ASCII 转义，在 GBK 控制台和 UTF-8 宿主间均可解析；解析后中文字段正常。

**`[CONFIG_INVALID] LLM 配置错误`**
检查所选 credentials 文件及相邻 ui 文件的 UTF-8 JSON、字段类型与冲突。
若刚切换 provider，用三个显式环境字段完整指定配置，或修正同一个桌面 profile；不要只换 Key 后沿用旧地址。

**宿主显示服务器启动失败**
先手动跑一次，直接看 stderr：

```bash
.venv-agent/Scripts/python.exe -m backend.agent mcp
```

正常表现是进程挂起等待 stdin，stderr 打印一行 `starting bilibili-crawler MCP server on stdio`。
按 Ctrl+C 退出。

**`No module named backend`**
`cwd` 没有指向仓库根目录。

**`[NO_CREDENTIALS] 缺少 LLM API Key`**
`crawl_comments` 不需要凭据，可以先用它验证链路；分析类工具见上面的「LLM 凭据」。

**爬取成功、分析失败**
评论和 run_id 会保留；按返回的 `next_step` 修正配置或等待，再调用
`analyze_run(run_id="...")`，无需重新爬取。CLI 也会给出对应 `analyze-run` 命令。

| error_code | 含义与操作 |
|---|---|
| `LLM_AUTH` | 401/403；检查 Key、服务权限及 doctor 配置 |
| `LLM_MODEL` | provider 明确指出模型参数错误；核对模型名/权限 |
| `LLM_ENDPOINT` | 路由、方法或重定向不被接受；核对 base_url，普通 404 不断言模型不存在 |
| `LLM_REQUEST_INVALID` | 其他请求参数错误；检查 provider 支持能力 |
| `LLM_TLS` | 证书/TLS 失败；修复证书或代理，不关闭证书验证 |
| `LLM_NETWORK` / `LLM_TIMEOUT` | 网络/超时；已发送的请求可能消费额度，人工确认后再重试 |
| `LLM_RATE_LIMIT` | 限流或额度不足；等待或检查账户额度 |
| `LLM_UNAVAILABLE` | 服务暂时不可用；等待恢复 |
| `LLM_RESPONSE_INVALID` | 响应 JSON/内容格式错误；检查模型输出能力 |

每个聊天请求最多发送三次，包括明确拒绝 `response_format` 时的一次兼容降级。
只有暂时性限流、部分服务错误和连接超时自动重试；读取超时、连接中断、鉴权、配置、
TLS、额度不足、解析错误不自动重放。超过 10 秒的 Retry-After 交由用户稍后重试。
批次结果已经完成而总结整合失败时保留已有结果，并记录 warning。
详见 [Provider 错误与恢复契约](PROVIDER_RECOVERY.md)。

**`[BUSY] 已有任务正在运行`**
本进程同时只跑一个任务。用返回里的 `task_id` 调 `stop_task`，或等它结束。

**`[NOT_FOUND] 找不到 run`**
`run_id` 写错，或运行目录被清理了。用 `list-runs` 查看现有的：

```bash
.venv-agent/Scripts/python.exe -m backend.agent list-runs
```

**怀疑 stdout 被日志污染**
所有日志都写 stderr。如果你自己改了代码，注意任何 `print()` 到 stdout 都会破坏 JSON-RPC 流。
`tests/test_agent_service.py` 里有一条断言专门守这个。

---

## 命令行

不接 MCP 也能直接用：

```bash
.venv-agent/Scripts/python.exe -m backend.agent crawl-comments "BV1GJ411x7h7" --max-pages 1
```

```bash
.venv-agent/Scripts/python.exe -m backend.agent crawl-and-analyze "https://www.bilibili.com/video/BV1GJ411x7h7"
```

```bash
.venv-agent/Scripts/python.exe -m backend.agent analyze-run 20260825-203826-0f407dfe
```

结果 JSON 走 stdout，进度日志走 stderr，方便管道处理。

---

## 测试

```bash
.venv-agent/Scripts/python.exe -m unittest discover -s tests
```

未安装 MCP SDK 时 `tests/test_mcp_server.py` 会整体跳过，其余测试照常运行。
