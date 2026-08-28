# MCP 接入指南

让 agent 直接爬取并分析 B 站公开评论，无需启动桌面客户端。

---

## 这是什么

一个本地 stdio MCP 服务器，把「爬取评论 → LLM 舆情分析 → 导出报告」暴露成 7 个工具。
每次运行都会落盘成一个带 `run_id` 的目录，因此 MCP 进程重启后仍能按 `run_id` 继续分析。

桌面客户端不受影响：它继续走 `backend/sidecar.py`，本次改动没有修改那个文件。

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

解析顺序（先命中者生效）：

1. 环境变量 `BILIBILI_LLM_API_KEY` / `BILIBILI_LLM_BASE_URL` / `BILIBILI_LLM_MODEL`
2. `BILIBILI_AGENT_CREDENTIALS` 指向的 `credentials.json`
3. 自动探测桌面端的 `credentials.json`，依次尝试：
   - `<仓库>/.install-test/user-data/config/credentials.json`（源码调试布局）
   - `%LOCALAPPDATA%\BilibiliCrawler\user-data\config\credentials.json`（installMode=currentUser 的默认安装位置）
   - `%PROGRAMFILES%` 与 `%PROGRAMFILES(X86)%` 下的同名路径

**如果你已经在桌面端配过 key**，按默认位置安装的话会被自动发现，通常什么都不用做，
不必把明文 key 再抄一份进 MCP 宿主配置。装在非默认位置时用环境变量指过去：

```json
"env": { "BILIBILI_AGENT_CREDENTIALS": "D:\\MyApps\\BilibiliCrawler\\user-data\\config\\credentials.json" }
```

安装版的 `user-data` 目录始终在**安装目录旁边**；按默认的 currentUser 方式安装时，安装目录就是 `%LOCALAPPDATA%\BilibiliCrawler`，因此凭据文件位于 `%LOCALAPPDATA%\BilibiliCrawler\user-data\config\credentials.json`。
环境变量优先级高于凭据文件，方便临时切换 key。

API Key 不会写进 `manifest.json`、不会出现在日志（含异常堆栈）、也不会出现在工具返回值里；
上游报错里回显的 key 会被替换成 `***`。

---

## 工具

| 工具 | 用途 | 需要 LLM 凭据 |
|---|---|---|
| `crawl_and_analyze` | 主入口：爬取 + 分析 + 导出报告，一次完成 | 是 |
| `crawl_comments` | 只爬取，落盘 JSON 和 CSV | 否 |
| `analyze_run` | 对已有 `run_id` 重新分析（旧结果归档到 `archive/`） | 是 |
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

如果在窗口内没跑完，工具会带着 `done: false` 和 `run_id` 正常返回，
之后用 `get_task_status(run_id=...)` 继续查询即可。这样长任务不会被宿主的
单次调用超时打断。

---

## 运行目录

```text
<仓库>/analysis-runs/<run_id>/
  manifest.json     状态、计数、参数、产物清单
  comments.json     清洗后的评论
  comments.csv      Excel 可直接打开
  analysis.json     完整分析结果
  report.md         Markdown 报告
```

目录内所有文件都采用「临时文件 + 原子替换」写入，进程中途被杀不会留下截断的
`manifest.json` 或半截 CSV。若 CSV 导出失败，任务会在 `warnings` 里明确报告，
而不是静默地只留下 JSON。

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
