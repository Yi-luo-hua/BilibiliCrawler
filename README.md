# Bilibili Comments Crawler

Bilibili Comments Crawler 是一个 B 站评论 / 动态爬取工具。v2.00 起项目迁移为 **Tauri + React + TypeScript** 桌面壳，Python 爬虫逻辑作为本地 sidecar 后端运行，通过本地进程通信完成爬取、扫码登录和 CSV 导出。

> 旧版 Python GUI / 单 exe 代码已保留在 `legacy-python-gui` 分支，主分支后续以安装包桌面应用为主。

本项目先后使用Cursor,Trae,Warp,antigravity,Claude Code,Codex完成。

如果有帮助的话，麻烦点个star⭐️谢谢喵！

如果使用过程中遇到Bug或有新增功能需要请提Issue谢谢喵！

## 功能

- 评论爬取：支持视频 BV/AV、动态、专栏链接。
- 动态爬取：支持用户空间动态和关注页动态流。
- 扫码登录：关注页动态流可通过 B 站 App 扫码登录。
- 筛选与导出：支持关键词、时间范围、最大页数，导出 CSV。
- 自定义背景：支持选择本地背景图、透明度、模糊和恢复默认。
- 本地运行：前端不直接请求网络，爬虫任务由 Python sidecar 后台线程执行。

## 下载使用

前往 [Releases](https://github.com/Yi-luo-hua/BCC/releases) 下载最新安装包：

- `BilibiliCrawler-Setup-2.0.0-x64.exe`

安装后从开始菜单或桌面快捷方式启动即可。首版安装包面向 Windows x64，默认当前用户安装，不需要额外安装 Python 环境。

如果想使用更加轻量化、无需安装的旧版，请下载v1.30。

## 使用方式

### 评论爬取

1. 进入“评论爬取”页面。
2. 输入视频 BV/AV、专栏 CV 号或直接复制完整链接即可。
3. 设置最大页数、排序方式和是否包含子评论。
4. 点击“开始任务”，等待日志和进度完成。
5. 点击“导出 CSV”保存结果。

### 动态爬取

1. 进入“动态爬取”页面。
2. 输入用户 UID 或 `space.bilibili.com/xxx` 链接。
3. 留空目标时会尝试爬取关注页动态流，需要扫码登录。
4. 可选设置关键词、时间范围和最大页数。
5. 点击“开始任务”，完成后导出 CSV。

### 界面设置

1. 进入“界面设置”页面。
2. 选择浅色 / 暗色主题。
3. 选择背景图后，应用会复制到安装目录下的 `user-data/backgrounds/`。
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

## 项目结构

```text
BilibiliCommentsCrawler/
├── assets/                         应用 logo 与图标资源
│   ├── app_logo.ico
│   └── app_logo.png
├── backend/
│   └── sidecar.py                  Python sidecar 入口，与 Tauri 进程通信
├── config/
│   └── config.py                   全局配置（请求头、API 地址、默认参数等）
├── desktop/                        Tauri + React 桌面前端
│   ├── src/
│   │   ├── components/
│   │   │   ├── BackgroundLayer.tsx  自定义背景图层
│   │   │   ├── BottomActionBar.tsx  底部操作栏（任务控制、导出）
│   │   │   ├── RightPanel.tsx       右侧面板（日志、进度）
│   │   │   ├── SideNav.tsx          侧边导航栏
│   │   │   ├── TaskWorkspace.tsx    任务工作区（输入表单）
│   │   │   └── TitleBar.tsx         自定义标题栏
│   │   ├── lib/
│   │   │   └── tauri.ts             前端与 Rust 后端的 Tauri invoke 封装
│   │   ├── App.tsx                  根组件
│   │   ├── main.tsx                 入口
│   │   ├── styles.css               全局样式（玻璃面板、主题变量）
│   │   └── types.ts                 公共 TypeScript 类型定义
│   ├── src-tauri/
│   │   ├── src/
│   │   │   └── main.rs              Tauri Rust 壳入口，注册 sidecar 命令
│   │   ├── capabilities/            安全能力配置
│   │   ├── icons/                   应用图标
│   │   ├── resources/               打包附加资源
│   │   └── tauri.conf.json          Tauri 配置（窗口、权限、sidecar 声明）
│   ├── package.json
│   └── vite.config.ts
├── scripts/
│   ├── build_backend.ps1            PyInstaller 构建 Python sidecar 单文件
│   └── build_installer.ps1          NSIS 安装包构建
├── src/
│   ├── api/
│   │   └── bilibili_api.py          B 站 API 封装（评论、动态、扫码登录）
│   ├── crawler/
│   │   ├── comment_crawler.py       评论爬虫（视频 / 专栏 / 动态）
│   │   └── dynamic_crawler.py       动态爬虫（用户空间 / 关注流）
│   ├── exporter/
│   │   └── csv_exporter.py          CSV 导出
│   └── processor/
│       └── data_processor.py        数据清洗与格式化
├── utils/
│   └── helpers.py                   工具函数（文件名清洗、链接解析等）
└── requirements.txt                 Python 依赖
```

## 更新日志

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
