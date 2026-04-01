# B站评论爬虫工具

一个基于Python的Bilibili评论爬取工具，支持爬取**视频、动态、专栏文章**的所有评论（包括子评论/回复），提供图形界面操作，并将数据导出为CSV格式。

使用Cursor,Trae,Warp,antigravity完成。

如果有帮助的话，麻烦点个star⭐️谢谢喵！

## 功能特点

- ✅ 支持通过视频链接、BV号或AV号爬取评论
- ✅ **支持爬取B站动态评论**（纯文字动态、图文动态、转发动态）
- ✅ **支持爬取B站专栏文章评论**（cv号或文章链接）
- ✅ 支持爬取主评论和子评论（回复）
- ✅ 支持按时间或热度排序
- ✅ 提供图形界面（GUI），操作简单
- ✅ 实时显示爬取进度和日志
- ✅ 导出为CSV格式，支持Excel打开
- ✅ 包含完整的评论信息（用户信息、点赞数、时间等）
- ✅ **多线程并发爬取子评论**，大幅提升爬取速度
- ✅ **自适应请求频率**，智能应对B站风控
- ✅ **Light / Dark 双主题**切换

## 环境要求

- Python 3.8 或更高版本
- Windows / Linux / macOS

## 安装步骤

### 第一步：克隆或下载本项目

下载并解压项目文件到任意目录，或使用Git克隆。

### 第二步：安装依赖包（重要！）

#### 方法1：使用一键安装脚本（推荐）

**Windows 用户**：双击运行 `install_dependencies.bat`

**Linux/macOS 用户**：在终端运行
```bash
chmod +x install_dependencies.sh
./install_dependencies.sh
```

#### 方法2：手动安装

**在项目根目录下**（包含 requirements.txt 的目录）打开命令行终端，运行：

```bash
pip install -r requirements.txt
```

**注意**：
- 如果使用 Python 3.x，可能需要使用 `pip3` 而不是 `pip`
- 如果使用虚拟环境（venv），请在激活虚拟环境后再安装
- 如果遇到权限问题，可以尝试添加 `--user` 参数：`pip install --user -r requirements.txt`

### 验证安装

可以运行以下命令验证依赖是否正确安装：

```bash
python -c "import requests, pandas, customtkinter; print('依赖安装成功！')"
```

如果没有报错，说明依赖已正确安装。

## 使用方法

### 方法1: 使用GUI界面（推荐）

#### 快速启动：

**Windows 用户**：双击 `启动程序.bat`

**Linux/macOS/或命令行用户**：
```bash
python main.py
```

然后在图形界面中：
1. 输入内容链接或ID，支持以下格式：
   - **视频**: `https://www.bilibili.com/video/BV1xx411c7mu` 或 `BV1xx411c7mu`
   - **动态**: `https://t.bilibili.com/123456789` 或 `https://www.bilibili.com/opus/123456789`
   - **专栏文章**: `https://www.bilibili.com/read/cv12345` 或 `cv12345`
2. 设置爬取参数（是否包含子评论、最大页数、排序模式等）
3. 选择导出文件路径
4. 点击"开始爬取"按钮
5. 等待爬取完成
6. 点击"导出CSV"按钮保存数据

### 方法2: 使用命令行（代码示例）

```python
from src.crawler.comment_crawler import CommentCrawler
from src.processor.data_processor import DataProcessor
from src.exporter.csv_exporter import CSVExporter

# 创建爬虫
crawler = CommentCrawler()

# 爬取评论（子评论自动并发爬取）
comments = crawler.crawl_comments(
    "BV1xx411c7mu",  # 视频BV号或链接
    include_replies=True,  # 包含子评论
    max_pages=100,  # 最大页数
    mode=3  # 排序模式：3=按时间，2=按热度
)

# 处理数据
processor = DataProcessor()
cleaned_comments = processor.clean_comments(comments)

# 导出CSV
CSVExporter.export(cleaned_comments, "comments.csv")
```

## 项目结构

```
bilibili-comment-crawler/
├── main.py                      # 主程序入口
├── 启动程序.bat                 # Windows 快捷启动脚本
├── install_dependencies.bat     # Windows 依赖安装脚本
├── install_dependencies.sh      # Linux/macOS 依赖安装脚本
├── src/
│   ├── api/
│   │   └── bilibili_api.py         # B站API调用封装（自适应延迟 + 重试）
│   ├── crawler/
│   │   └── comment_crawler.py      # 评论爬取核心（并发子评论爬取）
│   ├── processor/
│   │   └── data_processor.py       # 数据处理和清洗
│   ├── exporter/
│   │   └── csv_exporter.py         # CSV导出功能
│   └── gui/
│       ├── main_window.py          # GUI主窗口
│       ├── theme.py                # 主题系统（Light/Dark）
│       └── widgets/                # 自定义控件
│           ├── card_frame.py
│           ├── header_bar.py
│           ├── log_console.py
│           └── stat_card.py
├── config/
│   └── config.py                   # 配置文件（请求、并发、分页参数）
├── utils/
│   └── helpers.py                  # 工具函数
├── requirements.txt                # 依赖列表
└── README.md                       # 项目说明
```

## CSV导出字段说明

导出的CSV文件包含以下字段：

- **评论ID**: 评论的唯一标识
- **根评论ID**: 如果是回复，这是原始评论的ID
- **是否为回复**: 标识该评论是否为回复
- **用户名**: 评论者的用户名
- **用户等级**: 评论者的B站等级
- **评论内容**: 评论的文本内容
- **点赞数**: 评论获得的点赞数
- **回复数**: 评论收到的回复数
- **时间**: 评论发布时间（格式化）
- **IP归属地**: 评论者的IP归属地（如果可用）

## 注意事项

1. **遵守法律法规**: 请确保您的使用符合相关法律法规和B站服务条款
2. **合理使用**: 请控制爬取频率，避免对B站服务器造成过大压力
3. **数据隐私**: 请妥善保管爬取的数据，尊重用户隐私
4. **网络环境**: 确保网络连接稳定，某些情况下可能需要科学上网
5. **反爬虫机制**: B站可能会更新反爬虫机制，如遇到问题请及时更新代码

## 常见问题

### Q: 运行时提示 "No module named 'xxx'" 错误？
A: 这表示缺少必要的依赖包，请按照以下步骤操作：
1. 打开命令行终端，切换到项目根目录（包含 requirements.txt 的目录）
2. 运行：`pip install -r requirements.txt`
3. 等待所有依赖安装完成
4. 验证安装：`python -c "import requests, pandas, customtkinter; print('依赖安装成功！')"`
5. 重新运行程序：`python main.py`

如果仍然遇到问题，请检查：
- 是否使用了正确的 Python 版本（Python 3.8+）
- 是否在正确的目录下运行命令
- 尝试使用 `pip3` 而不是 `pip`
- 尝试添加 `--user` 参数：`pip install --user -r requirements.txt`

### Q: 启动GUI时提示 "Can't find a usable init.tcl" 错误？
A: 这是tkinter的Tcl/Tk库路径问题，已自动修复。如果仍有问题：
1. 确保Python安装完整（包含tkinter组件）
2. 如果使用虚拟环境，尝试退出虚拟环境使用系统Python
3. 或运行 `python fix_tkinter.py` 进行诊断
4. 手动设置环境变量：
   ```bash
   set TCL_LIBRARY=<Python安装路径>\tcl\tcl8.6
   set TK_LIBRARY=<Python安装路径>\tcl\tk8.6
   ```

### Q: 爬取失败怎么办？
A: 请检查：
- 网络连接是否正常
- 视频ID或链接是否正确
- 是否触发了B站的反爬虫机制（可以尝试降低爬取频率）

### Q: CSV文件在Excel中打开乱码？
A: 程序已使用UTF-8 with BOM编码，如果仍有问题，可以尝试用记事本打开后另存为其他编码。

### Q: 如何提高爬取速度？
A: v1.10 已内置自适应延迟和并发子评论爬取。如需进一步调整，可修改 `config/config.py` 中的 `REQUEST_DELAY_MIN`（默认0.1s）和 `MAX_REPLY_WORKERS`（默认4线程）。请勿设置过于激进，以免触发B站风控。

### Q: 支持批量爬取多个视频吗？
A: 当前版本不支持，但可以通过修改代码实现批量爬取功能。

### Q: 如何切换主题？
A: 点击GUI窗口右上角的主题切换按钮（☀️/🌙）即可在亮色和深色主题之间切换。

## 更新日志

### v1.20 (2026.04.01)

**✨ 新功能**
- **支持B站动态评论爬取**（纯文字动态、图文动态、转发动态）
- **支持B站专栏文章评论爬取**（通过cv号或文章链接）
- 自动识别输入类型（视频/动态/文章），无需手动选择
- 通过动态详情API自动获取评论区的真实 oid 和 type 参数

**🏗️ 架构优化**
- 新增 `ContentType` 枚举和 `ParsedInput` 统一解析器
- 新增 `resolve_target()` 方法，统一处理多种内容类型的OID获取
- API模块新增动态详情接口和专栏文章信息接口
- 评论和子评论爬取传递正确的 `type_id` 参数

**🎨 GUI 优化**
- 更新窗口标题和输入框提示，明确支持视频/动态/文章
- 输入框 placeholder 显示所有支持的格式示例

### v1.10 (2026.02.15)

**🚀 性能优化**
- 子评论并发爬取（ThreadPoolExecutor，默认4线程），速度提升 3-5x
- 自适应请求延迟：正常时 0.1s，被限速时自动退避到 2s 并逐步恢复
- 每页数据量从 20 提升到 30（B站API最大值），减少 33% 请求次数
- B站风控（code=-412）自动检测与重试

**🏗️ 架构优化**
- 全模块统一 `logging` 日志系统，替代散落的 `print()`
- 线程安全的 GUI 回调（通过 `root.after()` 投递到主线程）
- 迭代式重试机制替代递归调用
- 移除冗余依赖（beautifulsoup4、lxml）和空函数
- 清理未使用的 `animation_manager.py`

**🎨 GUI 优化**
- Light / Dark 双主题完整切换
- 统计卡片增加彩色背景底色与淡色边框
- 按钮状态视觉优化（开始/停止/导出的 disabled/enabled 明确区分）
- 排序分段按钮加宽、字体加大
- 进度条空闲时静止，爬取中动画，完成后满格
- 主题切换按钮增大

### v1.0.1 (2025.12.15)
- 增加了按钮高亮
- 调整UI

### v1.0.0 (2025.12.9)
- 初始版本发布
- 支持爬取B站视频评论
- 提供GUI界面
- 支持CSV导出

## 许可证

本项目仅供学习和研究使用，请勿用于商业用途。

## 贡献

欢迎提交Issue和Pull Request！

## 联系方式

如有问题或建议，请通过Issue反馈。

