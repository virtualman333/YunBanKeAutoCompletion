# 云班课辅助工具（YunBanKe Auto Completion）

一键把云班课（Mosoteach）课程下的资源标记为**已读 / 已学完**，支持图形界面和命令行两种用法。

> 本仓库最初是易语言版本的半成品（`云班课辅助工具V1.1.exe`），现已用 **Python 完整重写**：
> 补齐了空白的 `api.py` / `main.py`，新增图形界面、配置持久化、单元测试和本文档。
> 易语言版本的接口协议被完整保留并做了向后兼容。

---

## 目录

- [功能特性](#功能特性)
- [环境要求](#环境要求)
- [安装](#安装)
- [快速开始](#快速开始)
- [图形界面使用教程](#图形界面使用教程)
- [命令行使用教程](#命令行使用教程)
- [配置文件说明](#配置文件说明)
- [工作原理](#工作原理)
- [项目结构](#项目结构)
- [常见问题](#常见问题)
- [开发与测试](#开发与测试)
- [免责声明](#免责声明)

---

## 功能特性

| 功能 | 说明 |
| --- | --- |
| 账密登录 | 调用云班课官方登录接口，令牌以 `login_token` Cookie 维持会话 |
| 课程列表 | 自动拉取「我加入的课程」，支持按**序号 / 课程 ID / 名称关键字**定位 |
| 一键已读 | 遍历课程下全部资源，逐条上报观看进度，标记为已读 |
| 图形界面 | tkinter 界面，等价于原易语言窗口，操作全程可视化 |
| 命令行 | 5 个子命令，方便写进脚本或定时任务 |
| 断点容错 | 单条失败不影响整批；会话失效时给出明确提示 |
| 频率控制 | 请求间隔可调，默认 0.3s，避免高频请求 |
| 自动重试 | 网络抖动 / 5xx 自动重试 3 次 |
| 凭证持久化 | 账号密码存本地 `username.ini`（兼容老版本的裸 `key=value` 格式） |
| 零额外依赖 | 除 `requests` 外全部使用标准库 |

---

## 环境要求

- **Python 3.9 或更高版本**
- 能正常访问 `www.mosoteach.cn` 与 `coreapi-proxy.mosoteach.cn`
- `tkinter`（仅图形界面需要，Windows / macOS 官方 Python 自带）

---

## 安装

```bash
# 1. 获取代码
git clone https://github.com/virtualman333/YunBanKeAutoCompletion.git
cd YunBanKeAutoCompletion

# 2. （推荐）创建虚拟环境
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt
```

验证安装：

```bash
python main.py --version
```

---

## 快速开始

三步跑通：

```bash
# 第 1 步：登录并保存账号
python main.py login

# 第 2 步：看看有哪些课程，记住序号
python main.py courses

# 第 3 步：对某门课程一键已读
python main.py read --course 1
```

想要图形界面的话：

```bash
python main.py gui
```

---

## 图形界面使用教程

启动：

```bash
python main.py gui
```

界面从上到下依次是：

```
┌─ 登录区 ─────────────────────────────────────────────┐
│  账号 [__________]   密码 [__________]      [ 登录 ]  │
│  ☑ 记住密码                                          │
│  未登录                                              │
├─ 课程区 ─────────────────────────────────────────────┤
│  课程 [ 计算机网络（36b5d14a-…）▾ ] [刷新课程][获取资源]│
├─ 操作区 ─────────────────────────────────────────────┤
│  [一键已读] [停止]  ▓▓▓▓▓▓░░░░░░░  12 / 30           │
├─ 资源列表 ───────────────────────────────────────────┤
│  #   资源 ID                        状态              │
│  1   aaaa1111-…0001                ✓ 已标记为已读     │
│  2   aaaa1111-…0002                待处理             │
├─ 运行日志 ───────────────────────────────────────────┤
└──────────────────────────────────────────────────────┘
```

操作步骤：

1. **登录** —— 填账号（手机号/学号）和密码，勾选「记住密码」后点击 `登录`。
   登录成功会显示姓名和学号，并自动把课程列表填进下拉框。
2. **选课程** —— 在「课程」下拉框里选择目标课程。
3. **获取资源**（可选）—— 点 `获取资源` 会先把资源 ID 拉下来显示在列表里，
   方便你确认将要操作哪些内容。直接点「一键已读」也会自动拉取。
4. **一键已读** —— 点 `一键已读`，确认弹窗后开始执行。
   列表中每条资源的状态会实时从「待处理」变为 `✓ 已标记为已读`（绿色）或
   `✗ 失败原因`（红色），底部进度条与日志同步刷新。
5. **停止** —— 中途想停就点 `停止`，当前请求结束后退出循环。

> 所有网络请求都在后台线程执行，界面不会卡死，窗口可以随时最小化。

---

## 命令行使用教程

查看总帮助：

```bash
python main.py --help
```

参数既可以写在子命令**前面**，也可以写在**后面**，两种写法等价：

```bash
python main.py --account 13800000000 read --course 1
python main.py read --course 1 --account 13800000000
```

### 子命令一览

| 子命令 | 作用 |
| --- | --- |
| `login` | 登录，验证账号并保存凭证 |
| `courses` | 列出我加入的课程 |
| `read` | 对课程执行一键已读 |
| `gui` | 启动图形界面 |
| `logout` | 删除本地保存的凭证 |

### 公共参数

| 参数 | 说明 |
| --- | --- |
| `--account` | 账号；不传则读 `username.ini` |
| `--password` | 密码；不传则读 `username.ini` |
| `--token` | 直接使用抓到的 `login_token`，跳过登录 |
| `--config PATH` | 指定凭证文件路径 |
| `--timeout N` | 单次请求超时秒数，默认 `15` |
| `--delay N` | 相邻请求间隔秒数，默认 `0.3` |
| `--no-retry` | 关闭传输层自动重试 |
| `--no-save` | 登录成功后不写入 `username.ini` |
| `-v, --verbose` | 输出调试日志（含请求 URL 与参数） |

### 1. 登录

```bash
python main.py login
```

交互式输入账号密码（密码不回显），成功后打印姓名/学号/课程并保存凭证。

也可以一次性传参，或用 `--no-save` 避免落盘：

```bash
python main.py login --account 13800000000 --password your-password
python main.py login --account 13800000000 --password your-password --no-save
```

### 2. 查看课程

```bash
python main.py courses
```

输出：

```
── 我加入的课程（3 门） ──────────────────────────────
   1. 计算机网络            36b5d14a-956f-11ec-80ab-b8599fe847b4
   2. 操作系统              aaaa1111-2222-3333-4444-555566667777
   3. 数据结构              99ffbb00-1234-5678-90ab-cdef12345678
──────────────────────────────────────────────────────
提示：python main.py read --course <序号|ID>  可对单门课程执行一键已读
```

### 3. 一键已读

```bash
# 只处理一门课（三种定位方式都支持）
python main.py read --course 1
python main.py read --course 36b5d14a-956f-11ec-80ab-b8599fe847b4
python main.py read --course 计算机网络

# 处理全部课程
python main.py read --all

# 先小范围试跑，只处理前 5 条
python main.py read --course 1 --limit 5

# 放慢节奏，每次请求间隔 1.5 秒
python main.py read --all --delay 1.5
```

运行输出：

```
── 开始一键已读：计算机网络 ──────────────────────────
  观看进度上报值 12222 秒   请求间隔 0.3s
──────────────────────────────────────────────────────
  [  1/30] ✓ 36B5D14A-956F-11EC-80AB-B8599FE847B4
  [  2/30] ✓ AAAA1111-2222-3333-4444-555566667777
  ...
  [ 30/30] ✓ 99FFBB00-1234-5678-90AB-CDEF12345678

「计算机网络」共 30 条资源，成功 30 条，失败 0 条
──────────────────────────────────────────────────────
任务结束：全部成功 ✓
```

**退出码**：`0` 全部成功；`1` 存在失败项；`2` 会话失效需重新登录；`130` 用户中断。
方便写进脚本判断：

```bash
python main.py read --all || echo "有资源没处理成功，请查看日志"
```

### 4. 排障：导出原始页面

如果提示「没有解析到任何资源 ID」，用这个命令把服务端原始返回存下来：

```bash
python main.py read --course 1 --dump-html dump.html
```

命令会打印解析结果，同时把 HTML 写到 `dump.html`。
打开它搜索 `data-value` 就能看出页面结构是否变化。

### 5. 退出登录

```bash
python main.py logout
```

删除本地的 `username.ini`。

---

## 配置文件说明

凭证保存在**项目根目录**的 `username.ini`：

```ini
# 云班课辅助工具凭证文件
# 明文保存，请勿提交到版本库或分享给他人
[yunbanke]
account=13800000000
password=your-password
```

- 文件读取对格式做容错：标准 ini 的 `[节]` 写法、以及老版本易语言写出的
  无节名 `key=value` 写法都能识别（连原程序里 `usernane` 这个拼写错误也兼容）。
- 也识别 `username` / `user` / `账号` / `密码` 等别名。
- **该文件是明文**，`.gitignore` 已把它排除，请不要提交或分享。

指定其它路径：

```bash
python main.py --config D:\secrets\ybk.ini read --course 1
```

---

## 工作原理

工具做的事很简单：**模拟云班课移动网页版**，用你的账号完成「打开资源 → 上报观看进度」这套动作。

```
        ┌──────────────┐
        │  你的账号密码 │
        └───────┬──────┘
                │ ① POST account-login
                ▼
     ┌───────────────────────┐
     │ 得到 login_token 令牌  │
     └───────────┬───────────┘
                 │ 令牌写入 Cookie，后续请求自动携带
                 ▼
     ┌───────────────────────┐
     │ ② GET  my_joined      │ → 课程列表
     └───────────┬───────────┘
                 ▼
     ┌───────────────────────┐
     │ ③ GET  res&m=index    │ → HTML，正则抽出资源 ID
     └───────────┬───────────┘
                 ▼
        ┌────────┴────────┐   对每条资源循环
        │                 │
        ▼                 ▼
 ④ request_url_for_json  ⑤ save_watch_to
   （打开资源预览）        （上报已读）
```

### 接口明细

| 步骤 | 方法 | 地址 | 关键参数 |
| --- | --- | --- | --- |
| ① 登录 | POST | `coreapi-proxy.mosoteach.cn/index.php/passports/account-login` | JSON Body：`{"account","password"}` |
| ② 课程 | GET | `www.mosoteach.cn/web/index.php?c=clazzcourse&m=my_joined` | 无 |
| ③ 资源列表 | GET | `www.mosoteach.cn/web/index.php?c=res&m=index&clazz_course_id=<课程ID>` | 正则 `data-value="(.*?)"` 抽取资源 ID |
| ④ 资源预览 | POST | `www.mosoteach.cn/web/index.php?c=res&m=request_url_for_json` | `file_id`、`type=VIEW`、`clazz_course_id`，请求头带 `mime: video` |
| ⑤ 标记已读 | POST | `www.mosoteach.cn/web/index.php?c=res&m=save_watch_to` | `clazz_course_id`、`res_id`、`watch_to=12222`、`duration=12222`、`current_watch_to=12222` |

### 关于 `12222`

原版硬编码了 `12222`。这个值同时作为 `watch_to`（已观看秒数）、`duration`（总时长）
和 `current_watch_to`（当前进度）上报，三者相等即表示 **进度 100%**。
想让某条资源显示成别的进度，用 `--watch-to` 调整即可：

```bash
# 只报告 100 秒进度
python main.py read --course 1 --watch-to 100
```

### 请求特征

- **User-Agent**：移动端 Safari（`iPhone OS 11_0`），与原版一致。
- **会话**：所有请求共用一个 `requests.Session`，`login_token` 自动携带。
- **重试**：连接失败或 429/5xx 自动重试 3 次，指数退避。
- **限速**：请求之间默认间隔 0.3 秒。

---

## 项目结构

```
YunBanKeAutoCompletion/
├── api.py                  # ★ 云班课接口客户端（登录/课程/资源/已读）
├── main.py                 # ★ 命令行入口（argparse 子命令）
├── gui.py                  # ★ tkinter 图形界面
├── config.py               # ★ 凭证读写（username.ini）
├── requirements.txt
├── .gitignore
├── tests/
│   └── test_api.py         # 离线单元测试（不联网、不用真实账号）
├── README.md
├── 云班课辅助工具V1.1.exe   # 原易语言版本（历史归档）
└── 云班课资源一键已读.e     # 原易语言源码（历史归档）
```

★ 为本次 Python 重写新增/填充的文件。

### 各模块职责

| 模块 | 主要内容 |
| --- | --- |
| `api.py` | `YunBanKeClient` 客户端；`User`/`Course`/`ResourceResult`/`MarkReport` 数据类；`LoginError`/`SessionExpiredError`/`ApiError` 异常 |
| `main.py` | 5 个子命令、课程定位（序号/ID/名称）、控制台输出格式化 |
| `gui.py` | `YunBanKeApp` 窗口；后台线程 + 消息队列刷新界面 |
| `config.py` | `load_credentials` / `save_credentials` / `clear_credentials` |

### 二次开发

```python
import api

client = api.YunBanKeClient()
user = client.login("13800000000", "password")
print(user.display_name)

for course in client.get_my_courses():
    print(course.name, course.id)

# 只处理某一门课
report = client.mark_course_read(
    course,
    progress=lambda done, total, result: print(done, "/", total, result.ok),
)
print(report.summary())
```

只想用已有令牌（比如从浏览器抓的 `login_token`）：

```python
client = api.YunBanKeClient()
client.set_token("粘贴你的 login_token")
client.check_session()
```

---

## 常见问题

**Q：提示「会话失效，请重新登录」？**
令牌过期了。重新执行 `python main.py login` 即可。若刚登录就出现，用
`--dump-html` 导出页面确认服务端返回内容，可能接口有变动。

**Q：提示「没有解析到任何资源 ID」？**
三种可能：① 该课程确实没有资源；② 页面结构变了；③ 会话无效。
先用 `--dump-html dump.html` 导出页面，搜索 `data-value` 确认。

**Q：`ModuleNotFoundError: No module named 'tkinter'`？**
只有图形界面需要 tkinter，命令行功能不受影响。

- Windows / macOS：重新安装 python.org 官方版，勾选 tcl/tk。
- Ubuntu/Debian：`sudo apt install python3-tk`
- Fedora：`sudo dnf install python3-tkinter`

**Q：显示「接口未确认：{...}」是什么意思？**
`save_watch_to` 没有返回 `success` 字段。该条资源可能不支持这种进度上报
（例如纯文档类资源），也可能需要先满足其它前置条件。用 `-v` 看详细响应体。

**Q：会被封号吗？**
本工具请求频率很低、流量特征与正常网页版一致，但**仍属于自动化操作，
存在被平台风控识别并限制的风险**。建议把 `--delay` 保持在 0.3 秒以上，
不要高频重复执行。

**Q：密码保存在哪？安全吗？**
明文存在项目根目录 `username.ini`，只有登录时用到。介意的话用
`--no-save` 或 `logout` 清掉，每个会话手动输密码。

---

## 开发与测试

```bash
# 运行单元测试（离线，不联网、不需要真实账号）
python -m unittest discover -s tests -v

# 语法检查
python -m py_compile api.py main.py gui.py config.py
```

测试覆盖：课程列表解析（含多种字段变体）、资源 ID 抽取（含兜底规则与去重）、
登录成功/失败/缺 token、响应成功判定、请求参数拼装、进度回调、
凭证文件的读写与老格式兼容。

调试单个请求：

```bash
python main.py -v read --course 1 --limit 1
```

---

## 免责声明

- 本项目仅供**学习 Python 网络编程与 GUI 开发**使用。
- 使用者需自行承担因使用本工具产生的一切后果，包括但不限于账号被平台限制。
- 请勿将本工具用于任何商业用途或违反云班课用户协议的场景。
- 请遵守所在学校/机构的学术诚信规定，学习过程本身无法被自动化替代。

---

## 更新日志

### v2.0.0 —— Python 重写版

- 用 Python 完整重实现原易语言版本的全部功能
- 新增 `gui.py` 图形界面（tkinter），替代原易语言窗口
- 新增 `config.py`，凭证文件兼容老版本的裸 `key=value` 格式
- 新增命令行 5 个子命令，支持 `--course` 按序号/ID/名称定位
- 新增传输层自动重试、请求限速、`--dump-html` 排障
- 新增 23 项离线单元测试
- 资源 ID 解析加入多级兜底规则，提高页面结构变化时的容错性

### v1.1 —— 易语言版本（历史）

- `云班课辅助工具V1.1.exe`：选择课程后一键标记资源已读
