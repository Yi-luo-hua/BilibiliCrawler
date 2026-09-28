<div align="center">

<img src="./assets/app_logo.png" alt="BilibiliCrawler Logo" width="250" />

# BilibiliCrawler

**A Bilibili comment & dynamic post crawler with LLM sentiment & public opinion analysis for both end users and AI Agents.**

[![GitHub Downloads](https://img.shields.io/github/downloads/Yi-luo-hua/BilibiliCrawler/total)](https://github.com/Yi-luo-hua/BilibiliCrawler/releases)
[![GitHub Repo stars](https://img.shields.io/github/stars/Yi-luo-hua/BilibiliCrawler?style=social)](https://github.com/Yi-luo-hua/BilibiliCrawler/stargazers)
[![GitHub Code License](https://img.shields.io/github/license/Yi-luo-hua/BilibiliCrawler)](LICENSE)
[![GitHub last commit](https://img.shields.io/github/last-commit/Yi-luo-hua/BilibiliCrawler)](https://github.com/Yi-luo-hua/BilibiliCrawler/commits/main)
[![GitHub pull request](https://img.shields.io/badge/PRs-welcome-blue)](https://github.com/Yi-luo-hua/BilibiliCrawler/pulls)
[![Release](https://img.shields.io/github/v/release/Yi-luo-hua/BilibiliCrawler)](https://github.com/Yi-luo-hua/BilibiliCrawler/releases)

<p align="center">
  <b>English</b> | <a href="README.md">简体中文</a>
</p>

[Download Desktop App (Windows)](https://github.com/Yi-luo-hua/BilibiliCrawler/releases) • [MCP Guide](docs/MCP.md) • [Roadmap & Architecture](docs/FORWARD_PLAN.md) • [Changelog](CHANGELOG.md)

</div>

This project was built successively using Cursor, Trae, Warp, antigravity, Claude Code, and Codex.  
If this project helps you, please consider giving it a star ⭐️!  
If you encounter any bugs or have feature requests, feel free to open an Issue!

---

## 📖 Table of Contents

- [✨ Key Features](#-key-features)
- [⚖️ Usage Modes & Feature Matrix](#️-usage-modes--feature-matrix)
- [🚀 Quick Start](#-quick-start)
  - [Option 1: Desktop Application (Recommended for general users, No Python needed)](#option-1-desktop-application-recommended-for-general-users-no-python-needed)
  - [Option 2: MCP Protocol Integration (Recommended for AI Agents)](#option-2-mcp-protocol-integration-recommended-for-ai-agents)
  - [Option 3: Command-Line CLI](#option-3-command-line-cli)
- [🖥️ Desktop Guide](#️-desktop-guide)
- [📊 Data Export & Run Storage](#-data-export--run-storage)
- [🛠️ Development & Building](#️-development--building)
- [📁 Project Structure](#-project-structure)
- [📝 Release Highlights](#-release-highlights)
- [📄 License & Disclaimer](#-license--disclaimer)

---

## ✨ Key Features

- **Deep & Complete Comment Crawling**: Full support for Bilibili videos (BV/AV), dynamic posts, and column articles. Supports recursive pagination for sub-comments (replies), with `max_pages=0` to crawl the entire comment section without limits.
- **Dynamic Posts & Following Feed**: Crawl dynamic posts from any user space via UID, or log in via Bilibili App QR code to fetch your personal following feed.
- **LLM Sentiment & Deep Public Opinion Analysis**: Integrates with OpenAI-compatible LLMs (custom Base URL, Model name, and API Key). Supports sample aggregation and full-batch analysis, generating sentiment breakdown, topic rankings, sociological/psychological perspectives, and user-defined custom analysis angles.
- **Interactive Visualizations**: Donut charts for sentiment, bar charts for topic rankings, heatmaps for geographic distribution (China and overseas), timeline activity trends, user level distribution, and Python word clouds.
- **Modern Desktop Experience**: Crafted with **Tauri 2 + React 19 + TypeScript + TailwindCSS**, offering native performance, light/dark themes, frosted-glass acrylic styling, and custom local wallpapers with blur/opacity tuning.
- **Native MCP (Model Context Protocol) Support**: Available on PyPI (`bilibili-crawler[mcp]`). AI Agents (Claude Desktop, Cursor, Antigravity, Cline, etc.) can directly invoke tools via stdio without launching the desktop UI.
- **Security-First Architecture**: LLM keys are held in memory only—never written to disk or logs. Crawled comments are wrapped in `<untrusted-data>` tags to prevent prompt injection. CSV exports include Excel formula injection protection.

---

## ⚖️ Usage Modes & Feature Matrix

BilibiliCrawler provides two usage options: a desktop GUI and a headless CLI / MCP server:

| Feature / Capability | Desktop GUI | CLI | MCP Server (AI Agent) |
| :--- | :---: | :---: | :---: |
| **Video / Dynamic / Article Comment Crawling** | ✅ (Full + Nested Replies) | ✅ | ✅ |
| **User Space & Following Feed Dynamics** | ✅ (Includes QR Code Login) | ❌ | ❌ |
| **IP Location Parsing** | ✅ (Requires QR Login) | ✅ (Configure `BILIBILI_COOKIE`) | ✅ (Configure `BILIBILI_COOKIE`) |
| **LLM Sentiment Analysis** | ✅ (Sample / Full batch) | ✅ | ✅ |
| **Custom Analysis Angles (Prompt)** | ✅ | ✅ | ✅ |
| **Interactive Visual Charts** | ✅ (Recharts + Maps) | ❌ | ❌ |
| **Word Cloud Generation (PNG)** | ✅ (Built-in) | ✅ (Requires `[analysis]` extra) | ✅ (Requires `[analysis]` extra) |
| **Report Export Formats** | CSV / Markdown / JSON | CSV / Markdown / JSON | Structured ToolResult / Relative file paths |
| **Runtime Environment** | Windows 10/11 x64<br>(**No Python required**) | Python 3.10+ | Python 3.10+ |

---

## 🚀 Quick Start

### Option 1: Desktop Application (Recommended for general users, No Python needed)

1. Go to [GitHub Releases](https://github.com/Yi-luo-hua/BilibiliCrawler/releases) and download the latest Windows installer (e.g. `BilibiliCrawler-Setup-3.7.0-x64.exe`).
2. Double-click to install and launch from the Start menu or desktop shortcut. **No Python, Node.js, or runtime libraries required**.
3. Interface Preview:

<div align="center">
  <img src="docs/image/ScreenShot_2026-07-20_145934_010.png" alt="Default UI" width="48%" />
  <img src="docs/image/ScreenShot_2026-07-20_150142_079.png" alt="Custom Wallpaper UI" width="48%" />
</div>

---

### Option 2: MCP Protocol Integration (Recommended for AI Agents)

Published on PyPI, BilibiliCrawler can be integrated into any MCP-compatible agent in seconds:

#### 1. Installation & Environment
```powershell
# Create a dedicated virtual environment
python -m venv .venv-agent
.venv-agent\Scripts\pip install "bilibili-crawler[mcp]"

# Verify installation
.venv-agent\Scripts\bilibili-crawler doctor
```

#### 2. Configure MCP Host
Add the following to your MCP client configuration (e.g., Claude Desktop's `claude_desktop_config.json`, Cursor, or Antigravity):

```json
{
  "mcpServers": {
    "bilibili-crawler": {
      "command": "C:\\path\\to\\.venv-agent\\Scripts\\bilibili-crawler-mcp.exe",
      "args": [],
      "env": {
        "BILIBILI_LLM_BASE_URL": "https://api.openai.com/v1",
        "BILIBILI_LLM_MODEL": "gpt-4o-mini",
        "BILIBILI_LLM_API_KEY": "sk-...",
        "BILIBILI_COOKIE": "SESSDATA=your_sessdata; bili_jct=your_jct",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

> **Notes**:
> - **LLM Credentials**: Only required for analysis tools. If you have already configured LLM credentials in the desktop app, the MCP server will automatically discover and reuse them—no need to enter plaintext keys in the JSON config.
> - **BILIBILI_COOKIE**: Optional. Enables Bilibili to return comment IP locations. If omitted, comments are crawled anonymously (IP locations remain empty).
> - For tool specifications (`crawl_and_analyze`, `get_task_status`, `stop_task`, etc.), see [docs/MCP.md](docs/MCP.md).

---

### Option 3: Command-Line CLI

Run crawling and analysis directly from your terminal:

```powershell
# 1. Basic Crawling: Crawl first 5 pages of video comments (Saved as JSON / CSV, no LLM cost)
bilibili-crawler crawl-comments "BV1GJ411x7h7" --max-pages 5

# 2. Deep Crawling with LLM Analysis (Crawl entire comment section with custom prompts)
# Note: LLM credentials are automatically loaded from desktop config or environment variables:
bilibili-crawler crawl-and-analyze "BV1GJ411x7h7" `
  --max-pages 0 `
  --strategy sample `
  --sample-size 500 `
  --custom-module "Controversies=Analyze the core points of disagreement in the comments"

# 3. Re-analyze an existing run directory (run_id) with specific modules
bilibili-crawler analyze-run "20260928-120000-video-BV1GJ411x7h7" `
  --charts "sentiment_distribution,deep_analysis"
```

---

## 🖥️ Desktop Guide

### 1. Comment Crawling
- **Supported Targets**: Paste video URLs, BV/AV IDs, dynamic post URLs (`t.bilibili.com/...`), or article links (`cv...`).
- **Controls**: Set max pages (`0` for unlimited complete crawl), sort order (Newest / Hottest), and toggle sub-comment (replies) extraction.
- **IP Locations**: Click "QR Login" in the top-right corner to authenticate the session and fetch IP locations.

### 2. Dynamic Posts Crawling
- **User Space**: Enter target UP's UID or space URL.
- **Following Feed**: Leave the target field empty, scan QR code to log in, and crawl your personal following stream.
- **Filters**: Filter by keywords, publish timeframe (e.g. past 24 hours, past 7 days), and maximum page count.

### 3. Public Opinion Analysis
- **Model Settings**: OpenAI-compatible format. Enter Provider Base URL, Model name, and API Key.
- **Strategy**: Choose between "Sample Aggregation" (fast summary) and "Full Batch" (comprehensive statistics).
- **Modules**: Freely toggle Sentiment, Topics, Timeline, User Levels, Geographic Map, Deep Sociology/Psychology Analysis, Word Cloud, and Custom Prompt modules.
- **Export Reports**: One-click export to Markdown (with origin metadata and embedded word clouds) or JSON.

### 4. UI Customization
- Supports Light and Dark modes.
- Choose any local image as your window wallpaper with customizable opacity and acrylic blur strength.

---

## 📊 Data Export & Run Storage

### Run Directory Storage (`run_id`)
Each crawl or analysis generates an isolated run directory containing `manifest.json`, `comments.json`, `comments.csv`, `analysis.json`, etc.:
- Primary directory: `<repo-root>\analysis-runs\<run_id>\`
- Production fallback: `%LOCALAPPDATA%\BilibiliCrawler\analysis-runs\<run_id>\`

### Exported Fields
- **Comment CSV**: `Comment ID`, `Root ID`, `Is Reply`, `Username`, `User Level`, `Content`, `Like Count`, `Reply Count`, `Time`, `IP Location`, `Parent ID`, `User ID`.  
  *(Cells beginning with `=`, `+`, `-`, or `@` are automatically prefixed with a single quote to prevent Excel formula injection).*
- **Dynamics CSV**: `Dynamic ID`, `Username`, `Type`, `Content`, `Publish Time`, `Like Count`, `Comment Count`, `Forward Count`.

---

## 🛠️ Development & Building

### Requirements
- **OS**: Windows 10/11 x64
- **Node.js**: 20+ (`pnpm 10.28.0+` recommended)
- **Python**: 3.10+ (Official release installer built with CPython 3.13.15 x64)
- **Rust**: Stable MSVC toolchain

### 1. Install & Run Locally
```powershell
# 1. Install Python core dependencies
pip install -r requirements.txt

# 2. Install desktop frontend dependencies
corepack prepare pnpm@10.28.0 --activate
corepack pnpm --dir desktop install

# 3. Start development server (Tauri with Hot Reloading)
corepack pnpm --dir desktop tauri dev
```

### 2. Automated Regression Tests
```powershell
# Python regression suite (27 modules, 430+ tests)
python -m unittest discover -s tests -v

# Frontend typecheck & unit tests
corepack pnpm --dir desktop typecheck
node --experimental-strip-types --test desktop\tests\*.test.ts

# Rust host compilation check
cargo check --manifest-path desktop\src-tauri\Cargo.toml --locked
```

### 3. Build Windows Installer
```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_installer.ps1 -Python "path\to\python.exe"
```
The output will be placed in: `desktop\src-tauri\target\release\bundle\nsis\`.

---

## 📁 Project Structure

```text
BilibiliCrawler/
├─ bilibili_crawler/       # Python core implementation & distributable package
│  ├─ api/                 # Bilibili API endpoints & session handling
│  ├─ crawler/             # Comment & dynamic post crawler engines
│  ├─ processor/           # LLM analysis, text processing & word clouds
│  ├─ service/             # Headless business layer (AgentService, run storage, credentials)
│  ├─ sidecar.py           # Desktop Tauri IPC adapter
│  ├─ mcp_server.py        # MCP stdio server implementation
│  └─ agent.py             # CLI command entry point
├─ desktop/                # Tauri 2 + React 19 desktop application
│  ├─ src/                 # React UI, components, charts & state machines
│  └─ src-tauri/           # Rust host application & sidecar process manager
├─ docs/                   # Technical specs, MCP documentation & release notes
├─ scripts/                # Packaging, verification & build automation scripts
├─ tests/                  # Automated test suite
├─ pyproject.toml          # Python package metadata
└─ CHANGELOG.md            # Comprehensive release changelog
```

---

## 📝 Release Highlights

### 🌟 v3.7.0 (Latest Release)
- **Uncapped Crawling Limits**: `max_pages=0` crawls the entire comment section; nested sub-comments (replies) now page automatically until completely retrieved.
- **Cookie Session & IP Locations**: CLI & MCP support `BILIBILI_COOKIE` to parse verified IP locations.
- **Desktop Full Analysis Fix**: Fixed an issue where full analysis occasionally fell back to 300 samples; now analyzes the entire dataset.
- **Security & Stability Hardening**: Improved word cloud handling and custom module parsing; strictly isolated untrusted data and credential scrubbing.

👉 **[View Full Historical Changelog (v1.0.0 ~ v3.7.0) »](CHANGELOG.md)**

---

## 📄 License & Disclaimer

### License
This project is open-sourced under the [MIT License](LICENSE).

### Disclaimer
This project is for educational and research purposes only. Users must strictly comply with Bilibili's developer agreements, terms of service, and applicable laws and regulations.
