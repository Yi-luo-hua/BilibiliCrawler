# Python 产物与干净安装验收（G）

基线 `3614a34`。本批只增加可复现的产物/安装门禁，修复门禁发现的打包缺陷。
不更改版本，不公开发包，不合并 main，不修改桌面协议或引入生产测试开关。

- `python -m build` 默认先构建 sdist，再从 sdist 构建 wheel；构建环境与运行验收环境分离。
- `twine check --strict` 验证两个产物的发布元数据。它不代表公开包名可用或发布权限已就绪。
- `check_package_artifacts.py` 不导入或解压产物：核对完整文件白名单、版本、依赖/extra、入口、license、RECORD 哈希，以及 wheel/sdist 运行文件逐字节一致。新增包文件必须显式更新白名单。
- 内容扫描拒绝常见 Key/私钥、具值 cookie、个人目录和本机 checkout 路径；不读取用户凭据来做比对。它不能证明任意编码/未知格式的秘密均被识别。通用系统字体探测路径与文档占位路径不是机器私有目录。
- 拒绝重复、路径穿越、符号/硬链接、非普通文件及超限成员。产物不得包含测试夹具、缓存、历史 run、用户配置、旧通用命名空间或未列明的资源。
- `check_package_matrix.py` 要求显式提供 Python 3.10、3.11、3.12、3.13 四个解释器；每版本分别从 wheel 和 sdist 创建全新 venv，基础安装通过后再安装该本地产物的 `[mcp]` extra，共 8 个 venv / 16 个阶段。基础阶段必须没有 MCP；不允许全局/user-site 依赖、editable 安装或 repo PYTHONPATH。
- 安装阶段从 PyPI 下载声明依赖；每阶段记录 `pip list`、`pip check` 和 smoke。运行阶段仅使用合成凭据与 loopback HTTP：实际 CLI help、doctor、list-runs、包资源、默认用户目录、真实爬取/分析/落盘及两种 MCP stdio 入口。爬取/分析仅替换外部 HTTP 地址和响应，不替换爬虫、分析器或服务层。
- 默认串行验证解释器，避免构建与业务 smoke 同时大量访问磁盘；可显式 `--jobs 2` 至 `--jobs 4` 并发。失败仍导致非零退出、报告 `ok: false`，独立成功版本及失败原因保留；没有自动重试或降级为跳过。
- 基础环境不安装 jieba/wordcloud/qrcode；它们是可选渲染/桌面功能，桌面完整发布和真实 B 站/付费模型验收不由此矩阵代替。
- 产物、工具环境、测试 venv 与日志都放在项目 `.runlogs/`，不提交二进制/依赖，不修改全局环境；最终报告包含产物 SHA-256 与逐阶段证据。H 另行处理发布权限、公开名称与 CI 发布流程。

示例（PowerShell，替换四个解释器路径）：

```powershell
python -m venv .runlogs/g-build-env
.runlogs/g-build-env/Scripts/python.exe -m pip install build twine
.runlogs/g-build-env/Scripts/python.exe -m build --outdir .runlogs/g-artifacts
.runlogs/g-build-env/Scripts/python.exe -m twine check --strict .runlogs/g-artifacts/*
python scripts/check_package_artifacts.py .runlogs/g-artifacts/bilibili_crawler-3.3.0-py3-none-any.whl .runlogs/g-artifacts/bilibili_crawler-3.3.0.tar.gz --version 3.3.0 --report .runlogs/g-audit.json
python scripts/check_package_matrix.py --wheel .runlogs/g-artifacts/bilibili_crawler-3.3.0-py3-none-any.whl --sdist .runlogs/g-artifacts/bilibili_crawler-3.3.0.tar.gz --version 3.3.0 --python <python310> --python <python311> --python <python312> --python <python313> --work-dir .runlogs/g-matrix
```

F 的 `check_package_install.py <wheel>` 仍只代表借用当前依赖的本机 smoke；G 使用其
`--installed --expect-mcp yes|no` 模式，在已创建的独立 venv 内验收。仅有某阶段/某版本通过
不能把整张矩阵标记完成。当前命令验证 Windows；其他 OS 的路径逻辑测试不等于系统实测。

## 本机产物记录（2026-09-01，未发布）

build 1.6.0 / twine 7.0.0；版本仍为 Cargo 派生的 3.3.0。累计 review 修复后重新从
当前源码构建；验收脚本与测试不进入包。完整库存见本机 `.runlogs/fix-audit.json`。

| 产物 | 文件数 | SHA-256 |
|---|---:|---|
| `bilibili_crawler-3.3.0-py3-none-any.whl` | 36 | `c4b59ad991822e2cc358c8c64d199402bbfdfe9837d8e7b9aa226ff4341b1c32` |
| `bilibili_crawler-3.3.0.tar.gz` | 44 | `9d01433c20da50971b5b5b534784b0c9432fc03f898fc6be91b7fca72ce65f53` |

两次四解释器并发运行在 Python 3.10/sdist 的 `stage.rename(destination)` 遇到 WinError 5；
现有日志与源码复核无法确定根因。单独复跑三次通过仍不代表并发问题解决，后续应在失败时
捕获文件系统事件/句柄证据。并发日志与串行最终结论分别保留，不修改生产持久化逻辑来处理此风险。

## Windows 串行矩阵结果

最终从头创建 8 个新 venv，16/16 阶段通过，没有复用前两轮的测试环境；报告为
`.runlogs/fix-matrix/matrix-o02f4wde/report.json`（`jobs: 1`、`ok: true`、`errors: []`）。
报告记录各阶段完整依赖版本，开始与结束时的产物 SHA-256 一致。

| CPython | wheel 基础 | wheel + MCP | sdist 基础 | sdist + MCP |
|---|---|---|---|---|
| 3.10.20 | 通过 | 通过 | 通过 | 通过 |
| 3.11.16 | 通过 | 通过 | 通过 | 通过 |
| 3.12.14 | 通过 | 通过 | 通过 | 通过 |
| 3.13.15 | 通过 | 通过 | 通过 | 通过 |

每阶段均验证 help/doctor/list-runs、包资源、用户目录、`pip check`、真实 HTTP 爬取与
原 run 分析、评论哈希不变和全 run canary 零命中。MCP 阶段另验证 console/module 两个
stdio 入口的 7 工具握手。基础环境确实没有 MCP/jieba/wordcloud/qrcode；所有分发来自 venv。
这份通过记录不关闭上面的并发 WinError 5 风险，也不代表 macOS/Linux 实机或公开发布完成。
