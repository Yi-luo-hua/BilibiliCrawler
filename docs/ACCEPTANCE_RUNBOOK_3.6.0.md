# v3.6.0 真机验收操作手册（三条阻断项）

配套 [v3.6.0 发布准备与验收清单](RELEASE_3.6.0.md) 第 5 节。清单说**验收什么**，本文说**怎么做**，
只覆盖三条不可跳过的：从 v3.5.0 覆盖升级、安装器清理的遗留数据保留、真实风控下爬取仍判成功。
其余验收项可按 v3.5.0 的先例记为「维护者决定跳过」，但必须写明是跳过而不是通过。

---

## 0. 先决条件：本机注册表已被隔离测试污染，不修则三条全部无效

2026-09-10 在开发机上核查发现两处，**必须在装任何包之前处理**。

### 0.1 安装目录会指向一个不存在的隔离测试路径

```
HKCU\Software\local\BilibiliCrawler  (默认值) = E:\Cache\11-temp\bcc-isolated-test\install1
```

生成的 `installer.nsi` 里：

```nsis
Function RestorePreviousInstallLocation
  ReadRegStr $4 SHCTX "${MANUPRODUCTKEY}" ""     ; = HKCU\Software\local\BilibiliCrawler
  StrCmp $4 "" +2 0
    StrCpy $INSTDIR $4
FunctionEnd
```

`$INSTDIR` 会被设成那个路径，而**该目录已经不存在**。直接运行 3.6.0 安装包，默认安装位置就是
`E:\Cache\11-temp\bcc-isolated-test\install1`，不是真实安装所在的
`%LOCALAPPDATA%\BilibiliCrawler`。安装程序只在页面上显示这个路径，一路下一步不会有任何警告，
**升级验收会在一个空目录里做全新安装，结论完全无效**。

### 0.2 卸载项残留在 3.1.1，且指向不存在的 uninstall.exe

```
HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\BilibiliCrawler
  DisplayName     = BilibiliCrawler
  DisplayVersion  = 3.1.1
  InstallLocation = ...\.install-test\BilibiliCrawler-smoke-20260727-183100
  UninstallString = ...\.install-test\BilibiliCrawler-smoke-20260727-183100\uninstall.exe
```

该目录下只剩 `user-data\`，`uninstall.exe` 不存在。安装器用这个键判断"已装版本"并调用旧卸载程序
（`installer.nsi` 第 211、348 行），因此升级提示会显示从 **3.1.1** 升级，旧卸载程序调用也会落空。

### 0.3 真实安装是 3.4.0，不是清单要求的 3.5.0

`%LOCALAPPDATA%\BilibiliCrawler\bilibilicrawler_desktop.exe` 的 ProductVersion 是 **3.4.0**，
目录下有 **10 个真实 run**、`analysis-assets`、`user-data`。桌面与开始菜单**没有**快捷方式，
所以「必须从快捷方式启动验收」那条现在也做不了。

### 0.4 处理顺序

```powershell
# 1) 备份用户数据 —— 后面的清理验收会真的删安装目录里的文件
$Stamp  = Get-Date -Format yyyyMMdd-HHmmss
$Backup = "E:\Cache\11-temp\bcc-backup-$Stamp"
New-Item -ItemType Directory -Force $Backup | Out-Null
foreach ($d in 'analysis-runs','analysis-assets','user-data') {
    Copy-Item "$env:LOCALAPPDATA\BilibiliCrawler\$d" $Backup -Recurse -Force -ErrorAction SilentlyContinue
}
Get-ChildItem "$Backup\analysis-runs" | Measure-Object   # 应为 10

# 2) 导出两个注册表键留底，再删除
reg export "HKCU\Software\local\BilibiliCrawler" "$Backup\manuproductkey.reg" /y
reg export "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\BilibiliCrawler" "$Backup\uninstkey.reg" /y
reg delete "HKCU\Software\local\BilibiliCrawler" /f
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\BilibiliCrawler" /f

# 3) 卸载现有 3.4.0（顺带完成清单里「卸载后用户数据保留」一条）
& "$env:LOCALAPPDATA\BilibiliCrawler\uninstall.exe"
# 卸载完成后确认三个数据目录仍在：
Get-ChildItem "$env:LOCALAPPDATA\BilibiliCrawler" | Select-Object Name
```

删掉这两个键之后，`$INSTDIR` 会回落到模板默认的 `$LOCALAPPDATA\${PRODUCTNAME}`
（`installer.nsi` 第 502 行），也就是正确的目标。

---

## 1. 从 v3.5.0 覆盖升级

清单条目：「全新安装与从 v3.5.0 覆盖升级均正常，currentUser 安装位置正确」。

### 1.1 先装 v3.5.0 作为基线

```powershell
gh release download v3.5.0 -p 'BilibiliCrawler-Setup-3.5.0-x64.exe' -D "$env:TEMP\bcc-v350"
# 核对官方 SHA-256 后再运行
gh release download v3.5.0 -p 'BilibiliCrawler-Setup-3.5.0-x64.exe.sha256' -D "$env:TEMP\bcc-v350"
Get-FileHash "$env:TEMP\bcc-v350\BilibiliCrawler-Setup-3.5.0-x64.exe" -Algorithm SHA256
Get-Content "$env:TEMP\bcc-v350\BilibiliCrawler-Setup-3.5.0-x64.exe.sha256"
& "$env:TEMP\bcc-v350\BilibiliCrawler-Setup-3.5.0-x64.exe"
```

安装完成后确认：安装位置是 `%LOCALAPPDATA%\BilibiliCrawler`；从**开始菜单快捷方式**启动能起来；
标题栏显示 `评论 / 动态`（3.5.0 还没有版本显示，这正是升级后要看到变化的地方）。

### 1.2 覆盖安装 3.6.0

用候选包 `desktop\src-tauri\target\release\bundle\nsis\BilibiliCrawler-Setup-3.6.0-x64.exe`。

逐条确认：

- 安装页面显示的目标目录是 `%LOCALAPPDATA%\BilibiliCrawler`，**不是** `E:\Cache\...`
- 升级提示显示的旧版本是 **3.5.0**（若显示 3.1.1，说明 0.2 那个键没删干净）
- 安装后从快捷方式启动，标题栏应用名下显示 **`v3.6.0`**，不是「正在读取版本…」或「版本读取失败」
- `analysis-runs` 里升级前的 run 数量不变，随便打开一个 run 目录内容完好
- 快捷方式的 `TargetPath` 与 `WorkingDirectory` 指向新安装位置：

```powershell
$s = (New-Object -ComObject WScript.Shell).CreateShortcut(
     "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\BilibiliCrawler.lnk")
$s.TargetPath; $s.WorkingDirectory
(Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\BilibiliCrawler').InstallLocation
```

---

## 2. 安装器清理的遗留数据保留

清单条目：**任一数据目录丢失即为发布阻断**。这条验的是 `installer-hooks.nsh` 的守卫——
`_internal` 下只要存在 `analysis-runs` 或 `analysis-assets`，整次清理必须一步都不做。

### 2.1 造现场

在**已装好 3.5.0**（第 1.1 步之后、1.2 步之前）的安装目录里：

```powershell
$I = "$env:LOCALAPPDATA\BilibiliCrawler\resources\backend\sidecar\_internal"
New-Item -ItemType Directory -Force "$I\analysis-runs"   | Out-Null
New-Item -ItemType Directory -Force "$I\analysis-assets" | Out-Null
Set-Content "$I\analysis-runs\marker.txt"   'legacy run data must survive'
Set-Content "$I\analysis-assets\marker.txt" 'legacy asset data must survive'
Set-Content "$I\stale-payload-marker.txt"   'program payload, deleted only when the guard passes'
```

第三个文件是关键：它是**程序 payload 位置**上的普通文件。守卫生效时它也必须留下——
判据是「有没有遗留数据目录」，不是「排除那两个目录后再删」。

### 2.2 覆盖安装 3.6.0，然后确认三者都在

```powershell
Test-Path "$I\analysis-runs\marker.txt"        # 必须 True
Test-Path "$I\analysis-assets\marker.txt"      # 必须 True
Test-Path "$I\stale-payload-marker.txt"        # 必须 True —— 整次跳过清理
Test-Path "$I\..\_internal.old-payload"        # 必须 False —— 不留临时目录
```

**任何一个 True/False 不符即停止发布。** 前两个是用户数据，第三个证明守卫是「整次跳过」而不是
「排除两个目录后照删」——后者意味着重命名窗口回来了，那正是 v3.5.0 刻意消除的数据丢失路径。

### 2.3 反向验证：守卫不成立时清理必须真的执行

清掉遗留目录后再覆盖安装一次，确认标记文件这次**被删掉**：

```powershell
Remove-Item "$I\analysis-runs","$I\analysis-assets" -Recurse -Force
Set-Content "$I\stale-payload-marker.txt" 'should be removed this time'
# 再次运行 3.6.0 安装包（修复安装 / 覆盖安装）
Test-Path "$I\stale-payload-marker.txt"        # 必须 False
```

只做 2.2 不做 2.3，无法区分「守卫生效」和「清理功能整个没跑」。

---

## 3. 真实风控下爬取仍判成功

清单条目：本版最大的行为改动，夹具替代不了。验的是子评论失败降级为警告、任务**不得**判为失败。

### 3.1 制造条件

在装好的 3.6.0 里，评论爬取，**勾选「包含子评论」**，选一个评论多、且楼中楼回复多的视频，
最大页数拉到 20 以上。`MAX_REPLY_WORKERS` 的并发扇出在这种目标上很容易吃到 412。

不建议为了触发风控去登录——未登录时更容易限速，正好是要的条件。

### 3.2 判据

任务结束后：

- 界面终态是**完成**，不是失败
- 日志出现 `N 条评论的回复未能获取，其余结果继续保留`
- 日志另有一条终态警告 `N 条评论的回复未能获取，主评论与其余回复完整；首个原因：…`
  （两条措辞不同：前者来自爬虫进度，后者来自任务终态，会写进 manifest）
- 导出的 CSV 里主评论完整

```powershell
$Run = Get-ChildItem "$env:LOCALAPPDATA\BilibiliCrawler\analysis-runs" |
       Sort-Object LastWriteTime | Select-Object -Last 1
$M = Get-Content "$Run\manifest.json" -Raw | ConvertFrom-Json
$M.status                      # completed
$M.counts.reply_failures       # 与日志里的 N 相同
$M.warnings                    # 含那条终态警告
```

`counts.reply_failures` 与日志的 N **必须是同一个数字**。对不上说明汇总路径有问题。

### 3.3 若一直触发不了风控

不要为了凑数把它标成通过。记为跳过，并写明该路径由 `tests/test_crawl_integrity.py` 的
`test_reply_failure_completes_the_crawl_and_is_reported_as_a_warning` 覆盖——夹具能证明逻辑，
不能证明真实 412 会走进那条逻辑。

### 3.4 顺带确认顺利路径没被改坏

同一台机器上换一个评论量小的视频再爬一次：任务完成，日志**不出现**任何不完整提示，
`manifest.json` 里**没有** `counts.reply_failures` 字段。本版的改动不应在顺利路径上产生新提示。

---

## 4. 收尾

三条做完后，把结果（含失败与跳过）追加到 [RELEASE_3.6.0.md](RELEASE_3.6.0.md) 的验收记录，
并按 0.4 的备份还原被测试改动过的注册表与数据。**候选包不用于发布**：Release 资产要按清单
第 6 节在干净 worktree 里用全新构建环境重建。
