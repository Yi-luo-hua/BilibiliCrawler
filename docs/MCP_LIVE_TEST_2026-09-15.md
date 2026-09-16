# MCP 实测记录（2026-09-15）

用真实 B 站数据和已配置的模型，通过 SDK stdio 客户端逐个调用 7 个工具，记录行为与问题。

## 环境

- Windows 11，Python 3.13.0，`mcp==2.1.0`；源码 checkout（main `b7f8082`），未 `pip install`。
- LLM：桌面 profile 自动发现，`deepseek-v4-flash`。
- 样例：`https://www.bilibili.com/video/BV15QtG6PEzh/?`
- 运行目录用 `BILIBILI_AGENT_RUNS_DIR` 指向临时目录；仓库 `analysis-runs/` 测试前后均为 1211 个条目，未被写入。

## 方法

- 进程 1：`python -m bilibili_crawler mcp`，跑正常流程、并发、取消、边界输入。
- 进程 2：关闭进程 1 后以 `python -m backend.agent mcp` 重启，验证按 `run_id` 恢复与批量清理。
- 另跑 `scripts/smoke_mcp_stdio.py`（默认与 `--live`）和 5 个 MCP 离线测试模块。
- 收尾扫描：API Key 是否出现在 stderr、run 目录文件、工具返回中（只比对，不输出）。

## 结果

| 场景 | 结果 |
|---|---|
| 初始化与发现：7 工具、inputSchema/outputSchema、annotations、instructions，协议 `2026-07-28` | 通过 |
| `crawl_comments` 样例 URL，1 页含楼中楼 | 通过：196 条（主 30 + 回复 166），7.8s，JSON/CSV 均 196 行 |
| 带 `?p=1&spm_id_from=...&vd_source=...` 的 URL | 通过 |
| `analyze_run` 抽样 20 | 通过：19.6s，summary 已包 `<untrusted-data>`（230 字） |
| `analyze_run` `strategy="all"` | 通过：196 条 82s，79 条进度通知 |
| `crawl_and_analyze` 2 页、热度排序、不含楼中楼 | 通过：60 条，24s |
| `wait_seconds=0` 有界返回 | 通过：`done=false`，next_step 给出 task_id 轮询方式 |
| 并发：运行中再 crawl / analyze | 通过：`[BUSY]` |
| 运行中 `delete_run` 该 run | 通过：拒绝并提示先 stop |
| `stop_task` → cancelling → cancelled；重复 stop | 通过：3 秒内终态，重复调用返回终态 |
| 进度通知 | 通过：百分比单调，中文正常 |
| 参数夹紧：max_pages 0→1、999→50，sort_mode 99→3，wait -5→0，sample 0→20，strategy 非法→sample | 行为如代码所写，但无提示（见问题 2） |
| 类型错误 `max_pages="abc"` | 通过：校验错误 |
| 非法/穿越 run_id：`does-not-exist`、`../../etc`、`../sentinel-dir` | 通过：`INVALID_INPUT`，哨兵目录完好 |
| 未知 task_id / run_id / stop | 通过：`NOT_FOUND` / `INVALID_INPUT` |
| `delete_run` 单删、重复删 | 通过：目录删除；重复删 `NOT_FOUND` |
| `delete_run` 批量：`run_id=""` + `prune_to=2`；`prune_to` 0 / -3 | 通过：删 6 留 2；非正数被拒 |
| `delete_run` 批量：不传 run_id | **失败**（问题 1） |
| 重启后按 run_id 查询已完成 / 已取消的 run | 通过；旧 task_id 返回 `NOT_FOUND`（符合设计） |
| Key 泄露扫描 | 通过：0 处命中 |
| stdout / stderr | 通过：客户端无协议解析告警；stderr 为 UTF-8，无替换字符 |
| `smoke_mcp_stdio.py`（默认） | 通过：跳过，不读凭据 |
| `smoke_mcp_stdio.py --live`（1 页、样本 20） | 通过：30 条，36s，completed |
| 离线测试 `test_mcp_server/stdio/stdio_fixture/smoke_cli/smoke_live` | 38 个中 1 个导入错误（问题 6）；按文档 `discover -s tests` 方式通过；`analysis-runs/` 增量 0 |

## 问题

### 1. `delete_run` 不传 run_id 无法批量清理（中）

- 复现：`delete_run(prune_to=2)` 返回 `1 validation error for delete_runArguments / run_id Field required`。
- 原因：[mcp_server.py:355](../bilibili_crawler/mcp_server.py) 的 `run_id: str` 没有默认值，inputSchema 的 `required` 为 `["run_id"]`。
- 与文档矛盾：[MCP.md:161](MCP.md) 写"不传 run_id 时生效"，工具 docstring 写"不传 run_id 或传空串时生效"。
- 现有绕行：显式传 `run_id=""`。
- 建议：改为 `run_id: str = ""`，补一条不传 run_id 的测试。

### 2. 无效参数被静默改写（低）

- `strategy="bogus"` 按 sample 跑，`sort_mode=99` 按时间排序，`sample_size=0` 变 20，`max_pages=0` 变 1；返回里没有 warning。
- schema 中 `strategy` 是任意 string、`sort_mode` 是任意 integer，调用方只能从 docstring 得知合法值。
- 建议：schema 用枚举（`"sample" | "all"`、`2 | 3`），发生夹紧时写入 `warnings`。

### 3. 无法识别的链接也会留下 failed run（低）

- `"not a url at all"` 和 `"BV1111111111"` 都先创建 run 目录，再以 `CRAWL_FAILED` 结束。
- 两者错误相同：`无法解析目标内容的OID，请检查链接或网络`；next_step 只有通用的"请检查 error 说明后重试"。后者 stderr 另有 `code=-400 请求错误`。
- 影响：agent 试错会堆积空的 failed run；明显的格式错误也被归因到网络。
- 建议：受理阶段对无法识别的输入直接返回 `INVALID_INPUT`；区分"格式无法识别"与"目标不存在"。

### 4. 错误的返回通道不一致（低）

- 任务执行中失败（如 `CRAWL_FAILED`）返回结构化结果，带 `error_code`。
- 受理前失败（`BUSY` / `NOT_FOUND` / `INVALID_INPUT`）只返回错误文本，错误码在 `[CODE]` 前缀里；参数类型错误连前缀都没有，是 pydantic 英文原文。
- [MCP.md:158](MCP.md) 的"所有任务工具返回同一个精简结构"容易被理解成错误也有 `error_code` 字段。
- `BUSY` 文本中 task_id 出现两次（服务层消息一次，`_fail` 后缀一次）。
- 建议：文档说明两种错误通道；去掉 BUSY 的重复后缀。

### 5. serverInfo.version 为空（低）

- initialize 返回 `name='bilibili-crawler' version=''`；[mcp_server.py:187](../bilibili_crawler/mcp_server.py) 构造 `MCPServer` 时未传版本，宿主看不到服务版本。

### 6. `test_mcp_server` 依赖 discover 的 sys.path（低，仅测试）

- `python -m unittest tests.test_mcp_server` 报 `ModuleNotFoundError: test_provider_recovery`（[test_mcp_server.py:224](../tests/test_mcp_server.py) 同目录导入）。
- `python -m unittest discover -s tests -p test_mcp_server.py` 为 28/28 通过。文档规定用 discover，只影响按模块单独运行。

### 7. 仓库 `analysis-runs/` 中有 1211 个历史测试残留（信息）

- 全部符合测试夹具特征：`params.url` 为 `BV1xx411c7mD`（1045）或 `BV1xx`（166），最新一批创建于 2026-09-15 14:08，早于 #53 合并。
- 本次 MCP 测试前后增量为 0。
- 已于同日经确认清理：逐项按上述特征复核后移入回收站，`analysis-runs/` 现为空目录。

## 观察（非缺陷）

- 任务结束后不带参数调用 `get_task_status` 返回 `INVALID_INPUT`"当前没有活动任务"，符合 docstring。
- 1 页含楼中楼（196 条）的全量分析用时 82s，已接近默认 `wait_seconds=90`；默认 5 页含楼中楼的全量分析通常需要转轮询（文档已说明）。
- `list_runs` 同时返回 structuredContent 和逐条 TextContent（SDK 默认行为），列表越长宿主上下文重复越多。

## 未覆盖

- 动态、专栏链接和 AV 号（样例只有视频）。
- 真实 provider 故障下的各 `LLM_*` 错误码（离线测试已覆盖）。
- `pip install` 后的 `bilibili-crawler-mcp` 入口（本机未安装包）。
