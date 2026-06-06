# BilibiliCrawler

BilibiliCrawler 是一个 B 站评论 / 动态爬取与舆论分析桌面工具。v2.00 起项目迁移为 **Tauri 2 + React + TypeScript** 桌面应用，Python 爬虫和分析逻辑作为本地 sidecar 后端运行，通过本地进程通信完成爬取、扫码登录、LLM 分析和导出。

> 旧版 Python GUI / 单 exe 代码保留在 `legacy-python-gui` 分支。主分支以后以 Windows 安装包桌面应用为主。

本项目先后使用Cursor,Trae,Warp,antigravity,Claude Code,Codex完成。

如果有帮助的话，麻烦点个star⭐️谢谢喵！

如果使用过程中遇到Bug或有新增功能需求请提Issue谢谢喵！

## 功能

- 评论爬取：支持视频 BV/AV、动态、专栏链接。
- 动态爬取：支持用户空间动态和关注页动态流。
- 扫码登录：关注页动态流可通过 B 站 App 扫码登录。
- 筛选与导出：支持关键词、时间范围、最大页数，导出 CSV。
- 舆论分析：调用 LLM API 分析评论 / 动态主题、风险点、洞察和代表性内容。
- 可视化图表：支持主题排行、时间趋势、等级分布、地域地图、词云图和深度分析模块。
- 词云图：由 Python `wordcloud` 生成 PNG。
- 自定义界面：支持浅色 / 暗色主题、本地背景图、背景透明度和模糊效果。

## 下载使用

前往 [Releases](https://github.com/Yi-luo-hua/BilibiliCrawler/releases) 下载最新安装包：

安装后从开始菜单或桌面快捷方式启动即可。安装包面向 Windows x64，默认当前用户安装，不需要额外安装 Python 环境。

## 使用方式

### 评论爬取

1. 进入“评论爬取”页面。
2. 输入视频 BV/AV、动态链接、专栏 CV 号或完整链接。
3. 设置最大页数、排序方式和是否包含子评论。
4. 点击“开始任务”，等待日志和进度完成。
5. 如需更稳定地获取评论 IP 归属地，建议先扫码登录。
6. 点击“导出 CSV”保存结果。

### 动态爬取

1. 进入“动态爬取”页面。
2. 输入用户 UID 或 `space.bilibili.com/xxx` 链接。
3. 留空目标时会尝试爬取关注页动态流，此时需要扫码登录。
4. 可选设置关键词、时间范围和最大页数。
5. 点击“开始任务”，完成后可以导出 CSV。

### 舆论分析

1. 先完成评论或动态爬取，让数据保存在当前 sidecar 会话中。
2. 进入“舆论分析”页面。
3. 填写 请求地址、模型名和 API Key。
4. 数据源会自动匹配当前会话里已经爬取的数据。
5. 选择抽样聚合或全量分批策略，并勾选需要生成的分析模块。
6. 点击“开始分析”，完成后页面会展示所选图表和分析文本。
7. 点击“导出报告”可保存 Markdown 或 JSON 分析结果。

当前分析模块：

- 主题排行
- 时间趋势
- 等级分布
- 地域地图
- 词云图
- 舆论深度分析

说明：
- 词云图 PNG 会写入固定资源目录，每次分析创建独立子目录：

```text
%LOCALAPPDATA%\BilibiliCrawler\analysis-assets\
```

子目录命名格式：

```text
YYYYMMDD-HHMMSS-来源标签[-BV号]
```

示例：

```text
20260606-134500-动态
20260606-134500-视频评论-BV1abcdefghij
20260606-134500-动态评论
```

### 界面设置

1. 进入“界面设置”页面。
2. 选择浅色 / 暗色主题。
3. 选择本地背景图。
4. 调整背景透明度和模糊效果；恢复默认会清空自定义背景。

## 导出字段

评论 CSV 默认字段：

- 评论 ID
- 根评论 ID
- 用户名
- 用户等级
- 评论内容
- 点赞数
- 回复数
- 发布时间
- IP 归属地

动态 CSV 默认字段：

- 动态 ID
- 用户名
- 类型
- 内容
- 发布时间
- 点赞数
- 评论数
- 转发数

分析报告：

- Markdown：总结、所选分析模块、图表资源、洞察、风险点和代表性内容。
- JSON：完整分析结构，包含可视化图表数据层和元信息。
- Markdown 图表资源会写入报告同级的 assets 目录；词云图直接复用 sidecar 生成的 PNG 文件。

## 源码开发

### 环境要求

- Windows 10/11 x64
- Python 3.10+
- Node.js 20+
- pnpm 10.28.0+
- Rust stable MSVC toolchain

### 安装依赖

```powershell
pip install -r requirements.txt
corepack prepare pnpm@10.28.0 --activate
corepack pnpm --dir desktop install
```

### 开发运行

```powershell
corepack pnpm --dir desktop tauri dev
```

### 构建安装包

```powershell
scripts\build_installer.ps1
```

产物位于：

```text
desktop\src-tauri\target\release\bundle\nsis\
```

### 回归测试

```powershell
python -m unittest discover -s tests -v
python -m py_compile backend\sidecar.py src\processor\analysis_processor.py
corepack pnpm --dir desktop typecheck
```

## 项目结构

```text
BilibiliCrawler/
├─ assets/                         应用 logo 与图标资源
├─ backend/
│  └─ sidecar.py                   Python sidecar 入口，与 Tauri 进程通信
├─ config/
│  └─ config.py                    全局配置
├─ desktop/                        Tauri + React 桌面前端
│  ├─ public/
│  │  └─ favicon.png
│  ├─ src/
│  │  ├─ assets/
│  │  │  └─ app_logo.png
│  │  ├─ components/
│  │  │  ├─ AnalysisWorkspace.tsx  舆论分析配置与可视化仪表盘
│  │  │  ├─ BackgroundLayer.tsx    自定义背景图层
│  │  │  ├─ BottomActionBar.tsx    底部任务控制与导出
│  │  │  ├─ RightPanel.tsx         右侧日志和进度面板
│  │  │  ├─ SideNav.tsx            侧边导航
│  │  │  ├─ TaskWorkspace.tsx      评论 / 动态任务表单
│  │  │  └─ TitleBar.tsx           自定义标题栏
│  │  ├─ lib/
│  │  │  ├─ analysisCharts.ts      分析图表、地图和导出资产工具
│  │  │  └─ tauri.ts               Tauri invoke 封装
│  │  ├─ App.tsx
│  │  ├─ main.tsx
│  │  ├─ styles.css
│  │  └─ types.ts
│  ├─ src-tauri/
│  │  ├─ src/
│  │  │  └─ main.rs                Tauri Rust 入口和 sidecar 管道
│  │  ├─ capabilities/
│  │  ├─ icons/
│  │  ├─ Cargo.toml
│  │  └─ tauri.conf.json
│  ├─ package.json
│  └─ vite.config.ts
├─ scripts/
│  ├─ build_backend.ps1            安装 Python 依赖并用 PyInstaller 构建 sidecar
│  └─ build_installer.ps1          NSIS 安装包构建
├─ src/
│  ├─ api/bilibili_api.py          B 站 API 封装
│  ├─ crawler/comment_crawler.py   评论爬虫
│  ├─ crawler/dynamic_crawler.py   动态爬虫
│  ├─ exporter/csv_exporter.py     CSV 导出
│  └─ processor/
│     ├─ analysis_processor.py     LLM 舆论分析和词云图生成
│     └─ data_processor.py         数据清洗与统计
├─ tests/
│  ├─ fixtures/
│  └─ test_sidecar_analysis.py     sidecar 与分析回归测试
├─ utils/
│  └─ helpers.py                   链接解析等工具函数
└─ requirements.txt
```

## 更新日志

### v3.0.1 (2026.06.06)
- 修复 LLM 返回非标准 JSON（尾随逗号、嵌套对象截断）导致分析失败的问题，改用括号计数解析 + 尾逗号修复回退。
- 修复词云图在前端不显示的问题：sidecar 改以 base64 编码传输 PNG，不再依赖 asset 协议文件路径。

### v3.00 (2026.06.06)
- 新增舆论分析工作区，支持评论 / 动态数据源、LLM 请求配置、抽样聚合和全量分批分析。
- 新增主题排行、时间趋势、等级分布、地域地图、词云图和舆论深度分析可视化模块。
- 新增 Markdown / JSON 分析报告导出，Markdown 可携带图表资源和词云 PNG。
- 新增 `wordcloud` / `jieba` / `matplotlib` 依赖打包校验，安装包内置 Python sidecar 依赖，用户无需额外安装 Python 包。
- 改进桌面交互与任务状态展示，补充 sidecar 分析回归测试。

### v2.00 (2026.05.27)
- 主架构迁移到 Tauri 2 + React 19 + TypeScript + Vite + Tailwind。
- Python 爬虫逻辑改为 sidecar 后台进程，前端通过 JSON 请求 / 事件通信。
- 发布形式从单 exe 改为 NSIS 安装包。
- 新增风格化桌面 UI、玻璃面板、自定义背景、运行日志和进度条。
- 动态图文内容支持多图链接导出。
- 修复扫码登录 cookie 提取、限流重试、CSV 空数据导出等问题。

### v1.30 (2026.05.25)
- 新增动态爬取模式（用户空间 + 关注页动态流）
- 新增扫码登录功能
- 评论/动态双模式 GUI，关键词筛选 + 时间范围过滤

### v1.20 (2026.04.01)
- 支持动态评论和专栏文章评论爬取
- 自动识别输入类型，新增统一解析器

### v1.10 (2026.02.15)
- 子评论并发爬取（4线程），自适应请求延迟
- Light / Dark 双主题切换

### v1.0.0 (2025.12.9)
- 初始版本，支持视频评论爬取 + GUI + CSV导出

## 许可证

[MIT License](LICENSE)

## 免责声明

本项目仅供学习和研究使用，请遵守 B 站相关协议和法律法规。
