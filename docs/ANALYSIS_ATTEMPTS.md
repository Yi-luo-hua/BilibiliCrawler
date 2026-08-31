# 分析尝试与有效报告的状态契约

基线：P0 `7658ace`。本批修复“已有报告的 run 在重分析取消/失败后被降级”的行为。

## 持久化模型

按需升级被分析的 run 的 manifest 到 `schema_version: 2`，不批量改写历史目录。

- `analysis_attempts[]`：每次分析的 `attempt_id`（复用 task_id）、`status`、`started_at`、`finished_at`、`error`、`error_code`、`artifacts`、`counts`、`summary`、`warnings`。
- `current_analysis`：最近一次成功提交的尝试及其产物、计数、摘要和完成时间。没有成功报告时为空。
- 每次分析先完整写入 `analysis-attempts/<attempt_id>/`，只在全部文件就绪后将 staging 目录改名为最终目录；结果目录不再覆盖。
- 只有任务终态为 completed 时才通过一次原子 manifest 替换切换 `current_analysis`。取消/失败的结果可以保存在该尝试目录，但不得替换已完成报告。
- 有有效报告时，run 顶层 status/counts/artifacts/error 保持已完成报告的状态；本次尝试的失败或取消独立记录。没有有效报告时继续保留首次分析的失败/取消与已付费结果保留语义。
- 所有 manifest 产物引用相对 run；读取引用时再次验证路径边界，防止目录拷贝失效或越界读取。

## 调用方与兼容性

- `get_status(task_id=...)` 返回本进程内指定任务/尝试的状态；task_id 不跨重启恢复。重启后用 run_id 查询有效报告，尝试历史保留在 manifest。
- `get_status(run_id=...)` 在本进程存在仍运行的任务时返回其进度，终态后返回 run 的有效状态；最近一次尝试取消/失败时以 warning 说明。无需改变 MCP 字段或桌面 RPC。
- `load_analysis()` 和 `artifacts()` 以 manifest 指向的完整版本为准，不从不同版本拼接文件。重启后未完成的尝试不会覆盖旧报告；已有报告仍可读取。
- 根目录 `analysis.json` / `report.md` / `assets` 保留兼容副本，成功发布后刷新，旧副本继续进入 archive。它们不是多文件原子读取入口；跨进程消费者必须使用 `artifacts` 返回的版本路径。刷新兼容副本失败不撤销已提交版本，并给出 warning。
- 旧 run 首次重分析时，仅将状态为 completed 的现有分析文件复制为一个不可变 legacy 版本，再关联至 manifest；取消/失败时保留的产物不推定为成功。原文件不删除，不改变评论文件。
- `RunStore.save_analysis()` 原调用保持可用；新可选 `attempt_id` 参数用于版本化保存。自定义 store 重写此方法时需转发该可选参数。
- manifest 刷新失败保留已落盘结果与原有效指针，通过 warning 告知；不把已经确定的任务终态重写成另一个终态。这沿用既有暂时性写入错误处理约定。
- 本批不新增跨进程并发写锁。同一 run 不支持由多个服务进程同时修改，和现有单任务服务边界一致。

## 验收场景

1. 完成 → 重分析中取消：尝试 cancelled、run completed，旧报告和评论哈希不变。
2. 完成 → 重分析失败：错误只归属新尝试，旧有效产物不变。
3. 取消发生在处理器进入前、请求中、返回后、staging 和提交前：无迟到成功；已付费结果可在尝试记录中定位。
4. 成功重分析：一次切换有效版本，旧版本仍可读取；去掉词云不留下当前版本的旧图路径。
5. staging 写失败、manifest 替换失败、提交后兼容副本刷新失败：有效入口只返回完整旧版本或完整新版本。
6. 在版本目录落定但 manifest 尚未替换时模拟中断，再用新 store/service 读取：旧有效版本仍在；没有有效版本的未完成 run 沿用中断错误提示。
7. 旧 manifest 按需升级、复制 run 到新路径后恢复、所有尝试/归档与返回值的凭据脱敏。
8. Python 无 MCP/有 MCP 全量、桌面契约与 TypeScript 检查；此批不做新安装包或外部付费模型调用。
