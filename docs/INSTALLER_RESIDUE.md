# 安装器跨构建覆盖残留评估

结论先行：机制真实存在且已从生成的 NSIS 脚本确认。**并且已经发生过**——比对两个正式安装包的产物
清单，v3.3.0 → v3.4.0 就地升级会留下 3 个文件（见第三节）。触发它的不是任何声明变更，而是构建
环境差异，这一点决定了任何基于锁文件的预判都无效。推荐方案 A′（PREINSTALL 条件清理），但其设计
尚不完整，落地前必须先解决两个已知问题：迁移不删除旧源导致跳过条件可能永久成立，以及钩子早于
运行进程检查。

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
   探测报告一个实际已不存在的依赖。
3. **ABI 不匹配**：Python 小版本变化后残留的 `.pyd` 与新 `python3XX.dll` 不匹配。这类失败很响，
   且通常只在导入到该模块时才发生。
4. **纯占用磁盘**：没有任何代码引用的孤儿文件，最常见也最无害。

## 三、已经发生过（实测）

**判据**：新旧两次发布的产物清单中，存在只属于旧清单的路径。

### 取证方法

从 GitHub Release 下载两个正式安装包，用 `7z l -slt` 列出各自的打包清单，排除 NSIS 自身的
`$PLUGINSDIR` 与绝对路径条目后比对。

- `BilibiliCrawler-Setup-3.3.0-x64.exe`，53,600,679 字节，
  SHA-256 `6d59a13023836ade76eb43b42fd6bec894f2ad158a4f822c641661753f58f802`，应用文件 1299 个。
- `BilibiliCrawler-Setup-3.4.0-x64.exe`，53,480,344 字节，
  SHA-256 `60202e26bc29799104f3eb610fa1e196219f469f05467bd2215046277978d715`（与发布记录一致），
  应用文件 1297 个。

### 结果

**仅存在于 v3.3.0 的路径 3 条**，即 3.3.0 → 3.4.0 就地升级后留在磁盘上的残留：

```
resources\backend\sidecar\_internal\api-ms-win-core-fibers-l1-1-1.dll
resources\backend\sidecar\_internal\api-ms-win-core-kernel32-legacy-l1-1-1.dll
resources\backend\sidecar\_internal\api-ms-win-core-sysinfo-l1-2-0.dll
```

仅存在于 v3.4.0 的路径 1 条，是 F 批新增的包内资源，属于预期：
`resources\backend\sidecar\_internal\bilibili_crawler\resources\stopwords.txt`。

### 根因：构建环境差异，不体现在任何声明文件里

这三个是 Windows API-set 转发 DLL。PyInstaller 是否收集它们，取决于构建机的 UCRT / SDK 状态，
而**不取决于任何被声明的东西**：

- `requirements-desktop.lock` 在两个版本之间**完全没有变化**；
- `requirements-build.txt` 的 `pyinstaller==6.17.0` 也没有变化。

两个版本的差异只在于构建环境本身：v3.3.0 在原有环境构建，v3.4.0 在全新创建的 CPython 3.13.15
venv 中构建。旁证是本机当前的 `resources/backend` 工作树里这三个文件**存在**（属于更早那次构建），
而 3.4.0 安装包里没有。

这条根因有两个直接推论：

1. 「锁文件没变所以产物清单没缩小」是**无效推断**——本文早期版本正是这样推断的，被自己的产物证伪。
2. **无法从声明层预判**。要可靠检测，只能比对实际产物清单；把上一版发布的产物清单作为资产留存，
   下次构建后自动 diff，是唯一可行的自动化方向。

### 本次残留的严重度

低，但不为零。API-set 转发 DLL 通常由加载器经 apiset schema 解析，磁盘上多出同名文件一般不参与
解析；但应用目录先于系统目录被搜索，这仍属于第二节列出的「模块遮蔽」风险类别，在不实测的前提下
无法断言完全无害。当前没有观察到由此引发的故障报告。

受影响范围是**执行过 3.3.0 → 3.4.0 就地升级的用户**。本机已安装的 3.4.0 不受影响，因为真机验收前
做过备份、卸载、移走旧 sidecar 目录后重装的清理流程。

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

- **成本**：低。十余行 NSIS + 配置项 + 升级回归。
- **致命风险**：`docs/RELEASE_3.3.0.md` 的真机验收记录写明，v3.2.0 及更早版本把运行数据放在
  `resources/backend/sidecar/_internal/analysis-runs`，由首次启动时的迁移搬到稳定目录。安装器在
  应用启动**之前**运行，朴素递归删除会在迁移发生前销毁这些尚未迁移的用户数据。
- 结论：方向对，朴素实现不可接受。

### A′：按条件清理（推荐方向，但设计未完成）

同一个钩子，加一条判定：**`_internal` 下存在 `analysis-runs` 或 `analysis-assets` 时跳过清理**，
把机会让给应用的迁移逻辑。

跳过时行为与今天完全一致，因此最坏情况不劣于现状。但以下两点必须在落地前解决，否则方案不成立：

**问题 1：跳过条件可能永久成立。** 迁移是**复制而非移动**：`service/paths.py` 的
`_migrate_frozen_output` 文档字符串写着 "Copy legacy PyInstaller output into stable storage
without overwrites"，异常分支注释写着 "The legacy copy remains untouched and can be retried next
start"，`RELEASE_3.3.0.md` 的验收记录也明确写着"旧源仍保留"。所以 `_internal\analysis-runs` 一旦
存在就不会自行消失，这批用户将**永远跳过清理**。

  可选处理：(a) 明确接受这一限制，把它写进发布说明——这批用户与今天现状相同；(b) 另做一套安全退役
  流程，在迁移确认成功（逐文件哈希比对）后删除旧源，再由后续升级正常清理。(b) 是独立任务，涉及删除
  用户数据，必须单独评估，不能顺手塞进安装器改动里。**不能为了让清理生效而直接去掉保护判断。**

**问题 2：钩子早于运行进程检查。** 生成脚本中 `NSIS_HOOK_PREINSTALL` 在 L629，
`CheckIfAppIsRunning` 在 L632——**钩子先执行**。若应用正在运行，清理会先删掉部分运行时文件，之后
才轮到进程检查；用户在该提示上取消，就会留下一个被部分删除、无法启动的安装。方案必须补上：清理前
自行确认进程已退出（或把清理移到进程检查之后）、删除失败时的处理策略（放弃清理而非半途而废），
以及一条"应用运行中执行升级并在提示处取消"的回归。

- **落地前需要的验收**：带遗留 run 的 v3.2.0 覆盖升级须跳过清理且数据完好、v3.3.0+ 覆盖升级须执行
  清理且残留归零、卸载后用户数据仍保留、以及上述"运行中升级后取消"不留下半删除状态。

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

## 五、落地实现（v3.5.0）

方案 A′ 已实现，`desktop/src-tauri/installer-hooks.nsh` 经 `tauri.conf.json` 的
`nsis.installerHooks` 接入。两个未决问题都不再需要在文档列出的选项之间取舍：

**问题 1 的解法不是"跳过整次清理"，而是"排除两个目录"。** 钩子用 `FindFirst` / `FindNext` 枚举
`_internal`，逐条删除，只跳过 `analysis-runs` 与 `analysis-assets`。因此遗留用户数据原地保留等应用
迁移，而其余残留照常清理——清理不会对任何用户永久失效，第四节里那两个选项（接受限制 / 另立退役
任务）都不必选。迁移仍是复制不删除，这批用户的这两个目录会一直被跳过，仅此而已。

**问题 2 的解法是把进程检查提前。** 钩子第一条语句就 `!insertmacro CheckIfAppIsRunning`。该宏由
`utils.nsh` 提供且在钩子之前引入，因此"应用正在运行"的提示与取消都发生在任何删除之前；模板自己在
其后的调用变成 no-op。钩子之后安装不再有任何提示，所以被部分清理的产物总会被紧接着的安装补齐。

实现中踩到的一个坑记录在此：`${__LINE__}` 在宏体内是**逐行求值**的，直接用它拼标签会让定义处与
`Goto` 处得到不同名字，makensis 报 `could not resolve label`。改为开头 `!define` 一次、结尾
`!undef`，与 Tauri 自己的 `CheckIfAppIsRunning` 写法一致。**这类错误只有真正构建才会暴露**，静态
检查和 CI 都看不到。

配套的检测手段也已实现：`scripts/check_installer_payload.py` 生成打包清单并与上一版比对，
`build_installer.ps1` 在产出安装包后一并生成 `installer-payload-manifest.json`，随 Release 发布供
下一版使用。v3.4.0 → v3.5.0 实测为 0 removed / 0 added / 3 changed，本次发布不遗留任何文件。

## 六、建议

1. **方向采纳 A′，但设计尚不完整**：落地 PR 必须同时给出问题 1 的取舍（接受限制或另立退役任务）
   与问题 2 的处理（进程退出、失败策略、取消回归）。
2. **不再是"等触发"，改为排期**。第三节证明触发条件已经满足过一次，而且根因是构建环境差异——它
   不体现在任何声明文件里，也就无法预判、无法靠"改动时顺带做"来覆盖。合理的排期是下一次动到安装器
   或发布流程时一并落地；在此之前用 C 的过渡说明。
3. **把产物清单留存为发布资产**。这是唯一可靠的检测手段：每次发布保存打包文件清单，下次构建后与
   上一版自动 diff，出现"只属于旧清单的路径"即提示。成本很小（一个文本文件加一次比对），且能把这类
   问题从"事后翻安装包才发现"变成发布门禁里的一条。
4. **已经落在用户机器上的那 3 个文件**：严重度低，暂不单独处理。A′ 落地后，这些用户的下一次升级会
   自然清掉；提前推送一次专门的清理不值得，因为删除安装目录下的文件同样要先解决问题 1 与问题 2。
5. **不采纳 B。** C 仅作为 A′ 落地前的一句发布说明，不单独立项。
