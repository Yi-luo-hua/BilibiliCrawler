# 安装器跨构建覆盖残留评估

结论先行：机制真实存在且已确认，但**至今没有在任何已发布版本的升级中实际发生过**。推荐方案 A′
（PREINSTALL 钩子按条件清理 `_internal`），但不必抢在下个版本之前做；触发条件明确，可以在真正
需要时再落地。

## 一、机制（已确认）

证据取自本机构建生成的 `desktop/src-tauri/target/release/nsis/x64/installer.nsi`（449 KB，由
Tauri 内置模板生成，仓库没有自定义 NSIS 脚本）。

1. **卸载清单是构建期静态展开的。** `Section Uninstall` 为打包时的每个文件生成一条 `Delete`、
   为每个目录生成一条 `RMDir`。全文**没有任何 `RMDir /r`**，所有 `RMDir` 都是具名且非递归的。
   因此卸载器只能删除**它自己那次构建打进去的文件**。
2. **安装段不做预清理。** `Section Install` 只有 `SetOutPath $INSTDIR` 加逐个 `File`，就地覆盖。
3. **升级路径常常根本不卸载。** 重装页把是否卸载交给用户选择；而在 update 模式下
   （`$UpdateMode = 1`）代码直接 `Goto reinst_done`，**总是跳过卸载**。

三者相加，残留集合 = （旧构建打包的文件）−（新构建打包的文件）。它既活过升级，也活过之后的卸载
——因为新卸载器的清单里根本没有这些路径。

## 二、影响面

`_internal` 是 PyInstaller onedir 的运行时目录，位于 sidecar 的 `sys.path` 上，当前 1299 个文件、
89 个顶层条目。残留文件是**可被 import 的**，风险按严重度排序：

1. **模块遮蔽**：某依赖改名、拆分或换了发行方式时，旧模块仍可导入并可能胜出，运行的是老代码。
2. **元数据欺骗**：`service/diagnostics.py:82` 调用 `importlib.metadata.version("mcp")`，
   `agent.py:130` 调用 `importlib.util.find_spec("mcp")`。残留的 `*.dist-info` 或包目录会让这类
   探测报告一个实际已不存在的依赖。当前打包产物里只有 1 个 dist-info（numpy），暴露面很小。
3. **ABI 不匹配**：Python 小版本变化后残留的 `.pyd` 与新 `python3XX.dll` 不匹配。这类失败很响，
   且通常只在导入到该模块时才发生。
4. **纯占用磁盘**：没有任何代码引用的孤儿文件，最常见也最无害。

## 三、实际发生过吗

没有。查证如下：

- `requirements-desktop.lock` 在 `v3.3.0 → v3.4.0` 之间**无任何变化**。
- 该锁文件从 `v3.2.0` 到 `v3.3.0` 只有新增行，**移除的依赖数为 0**。
- `requirements-build.txt` 的 `pyinstaller==6.17.0` 在 3.3.0 与 3.4.0 之间未变，打包布局稳定。
- 当前已安装的 3.4.0（`%LOCALAPPDATA%\BilibiliCrawler`）与新构建产物逐文件比对，
  **仅存在于安装目录的文件数为 0**。

也就是说：迄今为止没有任何依赖被移除过，所以残留的触发条件从未被满足。发布清单里记录的那次
观察，来自**开发循环内的同版本候选覆盖**——重新构建的 sidecar 内容不同——而不是用户升级路径。

**触发条件很明确**：某次构建不再打包上一版打包过的文件。首次发生只会是这三种情况之一：移除一个
依赖、升级 PyInstaller 导致布局变化、或更换 Python 小版本。

## 四、方案对比

安装目录是 `%LOCALAPPDATA%\BilibiliCrawler`，其中**程序文件与用户数据同级共存**：

```
BilibiliCrawler\
├─ bilibilicrawler_desktop.exe   程序
├─ uninstall.exe                 程序
├─ resources\                    程序（含 backend\sidecar\_internal）
├─ analysis-runs\                用户数据
├─ analysis-assets\              用户数据
├─ user-data\                    用户数据
└─ cache\                        用户数据
```

任何清理方案都必须严格避开后四者。这是评估的硬约束。

### A：安装前清理程序资源目录

Tauri 提供 `NSIS_HOOK_PREINSTALL`（模板 L628-629 已插入宏点），配置 `nsis.installerHooks` 指向
一个 `.nsh` 即可。朴素实现是在钩子里 `RMDir /r "$INSTDIR\resources\backend"`。

- **成本**：低。十余行 NSIS + 配置项 + 一条升级回归。
- **致命风险**：`docs/RELEASE_3.3.0.md` 的真机验收记录写明，v3.2.0 及更早版本把运行数据放在
  `resources/backend/sidecar/_internal/analysis-runs`，由首次启动时的迁移搬到稳定目录。安装器在
  应用启动**之前**运行，朴素递归删除会在迁移发生前销毁这些尚未迁移的用户数据。
- 结论：方向对，朴素实现不可接受。

### A′：按条件清理（推荐）

同一个钩子，但加一条判定：**`_internal` 下存在 `analysis-runs` 或 `analysis-assets` 时跳过清理**，
把机会让给应用的迁移逻辑；下次升级时它们已不在 `_internal`，清理即可正常进行。

- **成本**：与 A 相当，多一次 `IfFileExists` 判定。
- **风险**：可控。跳过时行为与今天完全一致（即最坏情况不劣于现状）；执行时删除的是纯程序子树。
- **需要的验收**：从 v3.2.0 带遗留 run 覆盖升级（断言跳过、数据仍在、首启迁移成功）、从 v3.3.0+
  覆盖升级（断言清理执行、残留归零）、以及卸载后用户数据仍保留。

### B：版本化资源目录

改为 `resources\backend-<version>`，各版本互不混合。

- **成本**：高。要改 Rust 侧 sidecar 路径解析、bundler 资源配置与构建脚本，且版本号要贯穿三处。
- **风险**：残留问题不是消失而是**放大**——旧版本的整棵目录（约 1300 文件）会完整留下，除非再写
  一套清理。用一个大残留换掉一个小残留。
- 结论：不推荐。

### C：仅文档约束

在发布说明里写明「升级建议先卸载再安装」。

- **成本**：接近零。
- **风险**：把正确性外包给用户操作，而升级路径在 update 模式下本就跳过卸载，用户未必看得到提示。
- 结论：不足以单独作为方案，但适合作为 A′ 落地前的过渡说明。

## 五、建议

1. **采纳 A′**，不列为下个版本的阻断项。触发条件明确且当前未满足，没有抢做的理由。
2. **在触发条件出现时立刻落地**：任何一次改动 `requirements-desktop.lock` 移除依赖、升级
   PyInstaller、或更换 Python 小版本的 PR，都应同时带上 A′ 及其升级回归。
3. **不采纳 B。**
4. C 作为 A′ 落地前的一句发布说明即可，不单独立项。
