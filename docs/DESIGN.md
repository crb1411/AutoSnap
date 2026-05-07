# AutoSnap 产品与技术设计文档 v0.1

> 跨平台截图自动归档应用 — 让你"忘掉截图，需要时找得回来"。
> 本文档由 4 个并行调研合并而成（平台机制 / 技术架构 / 存储与查询 / AI 集成），覆盖产品形态、技术栈、模块边界、实施路线。
> 本文档目标读者：你自己（决策）+ 第一位上手的开发者（执行）。

---

## 0A. 当前开源 v0 实现状态（2026-05-07）

本仓库已经落地一个**Windows-first、可直接运行的 v0 原型**。它优先证明核心闭环：用户照常截图，AutoSnap 后台捕获，复制到规范目录，写入 SQLite 索引，并提供本地 UI 查询。

### 0A.1 本次 v0 的实际技术栈

| 层 | v0 选择 | 原因 |
|---|---|---|
| 桌面 UI | Python Tkinter | Windows 自带 GUI 运行时，工程最小，便于今天交付可运行版本 |
| 捕获 | watchdog 文件监听 + Pillow `ImageGrab.grabclipboard()` 轮询剪贴板 | 不接管系统截图快捷键，覆盖 `Win+PrtScn` 和 `Win+Shift+S` |
| 归档 | Python 标准库 + Pillow | 复制原图、计算 SHA-256、生成缩略图和 sidecar JSON |
| 索引 | SQLite + 可用时启用 FTS5 | 单文件、零服务、断网可用 |
| AI | 可选 OpenAI Responses API（BYOK） | 无 API key 时完整降级为本地归档和搜索 |
| Windows 启动 | `scripts/windows_install.bat` + `scripts/windows_run.bat` | 对普通 Windows 用户比 Rust/Node/Tauri 工具链更容易安装 |

这不是最终桌面技术选型的否定。长期产品形态仍建议使用 Tauri + Rust + React + NSIS/签名安装包；当前 v0 先固定**存储格式、归档行为、查询体验、AI 可选契约**，后续替换底层 UI/监听实现时保持数据目录和 SQLite schema 兼容。

### 0A.2 当前 v0 已实现

- 默认归档到 `%USERPROFILE%\Documents\AutoSnap`
- 默认配置文件在 `%APPDATA%\AutoSnap\config.json`
- 监听截图目录，不改变用户原有截图方式
- 剪贴板图片轮询，覆盖 Windows 截图只进剪贴板的场景
- 复制归档，不移动/删除原文件
- 物理路径：`YYYY/MM/DD/YYYY-MM-DD_HH-mm-ss_unsorted_<hash8>.<ext>`
- SHA-256 去重
- SQLite 元数据表、annotations 表、FTS5 搜索表（环境支持时）
- `_cache/thumbs/` 缩略图缓存
- `.meta/*.json` sidecar 元数据
- Tkinter 时间线网格、关键词搜索、导入已有文件夹、打开归档目录
- 可选 AI 标注：设置 `OPENAI_API_KEY` + `AUTOSNAP_ENABLE_AI=1` 后处理未标注截图

### 0A.3 当前 v0 明确未实现

- 不提供系统托盘、自启动、全局热键
- 不提供真正的 Windows 原生剪贴板事件监听，只做低侵入轮询
- 不包含 Windows.Media.Ocr，本地 OCR 暂未接入
- 不提供 NSIS/EV 签名安装包，只提供 Python 运行脚本和 PyInstaller 构建脚本
- 不做 Mac/iOS/Android 原生端；手机截图可先通过 OneDrive/iCloud/Google Drive 同步目录导入
- 不自建云服务，不做账号、计费、同步合并

### 0A.4 Windows 运行方式

```bat
scripts\windows_install.bat
scripts\windows_run.bat
```

可选打包 exe：

```bat
scripts\windows_build_exe.bat
```

### 0A.5 v0 验收口径

1. 全新 Windows 用户安装 Python 3.11+ 后，双击 `windows_install.bat` 能完成依赖安装。
2. 双击 `windows_run.bat` 能打开 AutoSnap UI。
3. `Win+PrtScn` 落盘截图可被监听并复制到归档目录。
4. `Win+Shift+S` 剪贴板截图可通过轮询捕获并复制到归档目录。
5. 断网、无 API key 时，归档、去重、时间线和关键词搜索仍可用。
6. 设置 API key 后，AI 标注失败不得影响基础归档。

---

## 0. TL;DR — 一页纸总览

| 维度 | 决策 | 一句话理由 |
|---|---|---|
| 定位 | 后台运行的"截图归档器"，非截图工具 | 不与 Win+Shift+S / Cmd+Shift+4 / 系统截屏冲突 |
| 平台优先级 | **Windows v0** → Mac v1 → Android v2 → iOS（云盘代理 + Shortcuts，不做后台监听） | iOS 系统不允许后台常驻监听截图，硬限制 |
| 桌面技术栈 | **Tauri 2.0 + Rust 后端 + React 前端** | 安装包 5–10 MB，Windows "双击零配置" |
| 移动端 v0 策略 | 不做独立 App，让用户开手机系统的"截图自动同步到云盘"，桌面端把云盘目录纳入监听 | 0 行移动代码即拿到四端覆盖 |
| 监听方式 | 文件系统 watcher（截图目录）+ 剪贴板 listener 双保险 | 覆盖"按 PrtScn 只进剪贴板"等场景 |
| 安装分发 | NSIS .exe per-user 安装，不要 UAC，**EV 代码签名** | SmartScreen 是 v0 装机率头号杀手 |
| 索引 | SQLite + FTS5（v0）；本地 CLIP + sqlite-vec（v1） | 单文件、零运维、跨平台同源 |
| 归档物理结构 | `YYYY/MM/DD/` 时间分层，类别写进文件名 | 卸载 app 后用文件管理器照样找得到 |
| AI 默认模型 | **Claude Haiku 4.5**（BYOK），可切换 GPT-4o-mini / Gemini Flash / 本地 Qwen2.5-VL | 中文好、JSON 稳、prompt caching 省钱 |
| AI 是可选项 | 没 API Key 也能用：时间归档 + 本地 OCR + 文件名搜索 + 应用名分组 | "不掏钱也比系统截图文件夹好用 10 倍" |
| 隐私 | 默认本地优先；身份证/银行卡/密码框/敏感目录绝不出本机 | 用本地正则 + OCR 关键词 + 可选小 VLM 三层拦截 |
| 同步 | 复用用户已有云盘（OneDrive / iCloud / Google Drive） | 0 自建后端、用户数据用户掌控 |

**用户首次 Windows 安装路径**：下载 8 MB 安装包 → 双击（无 UAC）→ 选监听目录与归档目录 → 跳过 API key → 主界面打开 → 按 Win+Shift+S 截图 → **1 秒后归档完成、UI 出现该截图**。整个过程 ≤ 60 秒、≤ 5 次点击。

---

## 1. 产品定位

### 1.1 痛点
- 每天产生几十张截图，分散在桌面 / `Pictures/Screenshots/` / 剪贴板 / 相册
- 文件名无意义（`Screenshot (327).png`），找回靠肉眼翻
- 想批量归类没工具；用 ShareX / CleanShot 又要替换截屏快捷键
- 跨设备截图（Mac 截了 + 手机截了）从来不在一起

### 1.2 目标
做一个**后台运行**的归档器：
1. 用户照常用系统截屏快捷键，AutoSnap 在背后捕获
2. 自动按"时间 + AI 推断的内容类别"归档到规范目录
3. 提供时间轴 / 类别 / 关键词 / 快捷回溯四种查询入口
4. **AI 只是增强层**——没 API Key 时基础归档完全可用
5. 跨 Mac / Win / iOS / Android，但 Windows 安装体验是头等大事

### 1.3 非目标（v0–v1 不做）
- 不做截屏工具本身（不抢 Win+Shift+S / Cmd+Shift+4）
- 不做录屏 / 时间线回放（避免与 Rewind / Recall 正面对撞）
- 不做云端账号 / 服务器 / 计费（同步靠用户的云盘）
- 不做团队共享 / 协作（个人工具，不掺杂复杂权限）

### 1.4 差异化定位
> "Rewind 之轻量 / Eagle 之自动 / Apple 照片之跨平台"

竞品在"截图工具"和"图库管理"两端都有强者，**中间地带——零配置自动归档 + 跨设备时间/内容检索——几乎空白**。Eagle 最像但要用户主动拖入；ShareX/CleanShot 是截屏工具不是归档工具；Rewind 录屏太重隐私争议大。AutoSnap 只做"截图被产生之后的事"。

---

## 2. 各平台原生截图机制（决策依据）

| 平台 | 默认快捷键 | 默认保存路径 | 进剪贴板？ | AutoSnap 监听方式 |
|---|---|---|---|---|
| **macOS 12+** | `Cmd+Shift+3/4/5` | `~/Desktop/`（可改） | 默认否；按 Ctrl 则只进剪贴板 | FSEvents 监听 Desktop + `defaults read com.apple.screencapture` 自动同步用户改过的路径 |
| **Windows 10/11** | `Win+PrtScn` / `Win+Shift+S` / `PrtScn` | `%USERPROFILE%\Pictures\Screenshots\` | `Win+Shift+S` 默认进剪贴板，是否同时落盘看版本 | `ReadDirectoryChangesW` 监听 + `AddClipboardFormatListener` 监听 `WM_CLIPBOARDUPDATE`/`CF_DIB` |
| **iOS** | 侧边键 + 音量上 | 相册"截屏"相簿；不进剪贴板 | 否 | **不可后台监听**。走 iCloud 同步到桌面端 + iOS Shortcuts 主动触发 |
| **Android** | 电源 + 音量下（厂商各异） | `Pictures/Screenshots/` 或 `DCIM/Screenshots/` | 否 | `MediaStore` ContentObserver + ForegroundService（厂商保活白名单要专门引导） |

**关键洞察**：
- 桌面端都"先落盘到固定目录"，监听目录就够，零权限难题
- **Windows 必须做剪贴板兜底**：很多用户的 Snipping Tool 自动保存默认是关的，纯靠目录监听会漏掉
- **iOS 是真硬限制**，不要假装能后台监听，老老实实做云盘代理 + 用户主动分享

---

## 3. 技术架构

### 3.1 技术栈选型

#### 桌面端：Tauri 2.0（Rust + Web 前端）

| 候选 | 评价 | 决策 |
|---|---|---|
| **Tauri 2.0** | 安装包 5–10 MB；Rust 写监听/原生 API 性能强；前端复用 React | ✅ 选 |
| Electron | 安装包 80–150 MB；常驻 200 MB+ 内存；与"零配置"诉求冲突 | ❌ |
| Flutter Desktop | UI 漂亮但低层活（FS watcher / 系统托盘 / 剪贴板）插件成熟度低 | ❌ |
| .NET MAUI | Windows 表现好但 Mac 一塌糊涂 | ❌ |
| 原生 Swift + WPF | 体验最好但要写两套 UI + 两套业务逻辑 | ❌ |
| Python + Qt/Tk | PyInstaller 打包易被 Defender 误报、首启动 3–5 秒 | ❌ |

**关键论据**：唯一硬约束是"Windows 双击零配置"。Tauri 安装包小、性能强、跨平台一份代码（FS 用 `notify` crate，剪贴板用 `arboard`）。Electron 即使 asar 优化也压不到 50 MB 以下，且 SmartScreen 对大型未签名 exe 警告更激进。

#### 移动端 v0：不做独立 App，云盘代理

让用户在手机系统设置里打开"截图自动同步到云盘"（iOS 走 iCloud Drive / Google Photos，Android 走 OneDrive / Google Drive 上传）。桌面端 AutoSnap 把这些云盘目录加入监听，手机截图就被自动吃进归档管线。

**这一招直接绕开 iOS 后台限制**，0 行移动代码拿到四端覆盖。v2 再考虑做原生壳（Android 用 MediaStore Observer 真后台监听；iOS 用 Share Extension 让用户从系统截图浮窗"分享到 AutoSnap"）。

#### 同步层：复用用户云盘，不自建后端

归档目录就是云盘里某个 `AutoSnap/` 文件夹。SQLite 索引数据库放本机，跨设备通过云盘同步增量日志（CRDT-lite，v2 再做）。**0 运维成本、用户数据用户掌控、天然解决移动端**。

#### 本地存储：SQLite + FTS5

- **元数据**：SQLite + FTS5 全文索引（文件名、OCR 文本、AI 标签）
- **图像本身**：直接存原始 PNG/JPG 在 `AutoSnap/<year>/<month>/<day>/` 下，不入库
- **缩略图**：256 px WebP 存 `AutoSnap/.cache/thumbs/`，加 `.syncignore` 不进云盘
- **向量检索**：v0 不做，v1 引入本地 CLIP + `sqlite-vec`

#### AI 调用层：Provider 抽象 + BYOK

```rust
// src-tauri/src/ai/provider.rs
#[async_trait]
pub trait VisionProvider: Send + Sync {
    async fn annotate(&self, image: &[u8], ctx: &Context) -> Result<Annotation>;
    fn estimate_cost(&self, image: &[u8]) -> f64;
    fn name(&self) -> &str;
}
```

默认接 Claude Haiku 4.5；用户在设置页可切换 OpenAI / Gemini / Ollama 本地模型。

### 3.2 模块拆分

```
+----------------------------------------------------------+
|                       UI Layer (TS/React)                |   平台共享
|     时间轴 / 类别浏览 / 搜索 / 快捷回溯                  |
+----------------------------------------------------------+
            ^                           ^
            | Tauri IPC                 |
            v                           v
+----------------------+      +-------------------------+
|   Query Service      |      |   Settings Service      |   Rust, 共享
|  SQL + FTS5 + vec    |      |  API key, paths, rules  |
+----------------------+      +-------------------------+
            ^                           ^
            |                           |
+----------------------------------------------------------+
|                    Archiver (core)                       |   Rust, 共享
|   规范化文件名 → move/copy → 写索引 → 触发 AI 队列        |
+----------------------------------------------------------+
            ^                                  ^
            | new image event                  | annotation
            |                                  |
+----------------------+              +--------------------+
|  Capture Watcher     |              |  AI Annotator      |
|  - FS notify         |              |  - Provider trait  |
|  - Clipboard hook    |              |  - Queue + retry   |
|  - Cloud dir mirror  |              |  - 永不 panic       |
+----------------------+              +--------------------+
   平台特定 thin layer                   网络依赖（可关）
   (Win/Mac 各 ~100 行)
```

| 模块 | 输入 | 输出 | 跨平台？ | 网络？ |
|---|---|---|---|---|
| Capture Watcher | OS 事件 / 目录变化 / 剪贴板更新 | `CapturedImage{path, source, ts}` | thin platform layer | 否 |
| Archiver | `CapturedImage` | `ArchivedItem` + DB row | 全共享 | 否 |
| AI Annotator | `ArchivedItem` | `Annotation`（写回 DB） | 全共享 | **是**（可关） |
| Query Service | search query | `Vec<ArchivedItem>` | 全共享 | 否 |
| UI | 用户交互 | IPC 调用 | 全共享 | 否 |
| Sync (v2) | DB changelog | 合并后的 DB | 全共享 | 是 |

**核心解耦原则**：Annotator 通过队列消费 Archiver 的输出，**Annotator 失败时 Archiver 必须继续工作**。这是"不调 AI 也能用"硬约束的架构落点。

---

## 4. Windows-First 安装体验

**方案：Tauri 生成的 NSIS .exe 单文件安装包 + EV 代码签名**

用户路径（5 步内见结果）：

1. 官网点 "Download for Windows" → 下载 ~8 MB 的 `AutoSnap-Setup.exe`
2. 双击运行（**无需管理员**，per-user 安装到 `%LOCALAPPDATA%\AutoSnap\`，绕过 UAC）
3. 安装器自动启动 App，弹出 onboarding：
   - **Step 1**：选监听源（默认勾上 `%USERPROFILE%\Pictures\Screenshots\` + 剪贴板）
   - **Step 2**：选归档目录（默认 `%USERPROFILE%\Documents\AutoSnap\`，提示"放到 OneDrive 子目录可自动多端同步"）
   - **Step 3**：**跳过 API key**——直接进主界面。顶部黄条提示"加 API Key 解锁智能标签"，不强制
4. 用户按 `Win+Shift+S` 截图 → 1 秒后主界面出现该截图（基础归档完成，文件名规范化为 `2026-05-07_14-32-11_unsorted_a3f1.png`）
5. 任何时候可去设置粘贴 API key，历史截图一键回溯标注

**为什么 NSIS 而不是 MSI / MSIX / Winget**：
- MSI 默认要 UAC，与"零配置"冲突
- MSIX 需 Microsoft Store 或开发者证书，对"双击即装"反而是阻碍
- Winget 作为 v1+ 的补充分发渠道很好，但要求开 PowerShell，不能作为 v0 主入口

**关键投入：必须买 EV 代码签名证书 (~$300/年)**，否则 Windows SmartScreen 拦"未知发布者"是 Windows 装机率头号杀手。备选 Azure Trusted Signing。

---

## 5. 归档物理目录结构

### 5.1 设计原则
AutoSnap 是"后台归档器"，不是"私有黑盒"。三种场景都得能用：
1. **App 在线**：在 App 内按时间/类别/搜索找
2. **App 离线 / 卸载后**：直接用 Finder / Explorer 翻文件夹也能找到
3. **跨设备同步**（OneDrive / iCloud / 坚果云挂载该目录）：路径稳定、命名 OS 友好

所以目录结构必须**自解释**：光看路径就知道这是什么时候、大概什么内容的截图。

### 5.2 目录布局

```
AutoSnap/
├── 2026/
│   └── 05/
│       └── 07/
│           ├── 2026-05-07_14-30-12_chat_a3f1.png
│           ├── 2026-05-07_14-30-12_chat_a3f1.thumb.webp
│           ├── 2026-05-07_15-02-44_code_b7e2.png
│           ├── 2026-05-07_15-02-44_code_b7e2.thumb.webp
│           └── .meta/
│               ├── 2026-05-07_14-30-12_chat_a3f1.json
│               └── 2026-05-07_15-02-44_code_b7e2.json
├── _inbox/                    # 刚捕获、还没分类完的临时区
├── _trash/                    # 软删除（30 天后清理）
├── _index/
│   ├── autosnap.db            # SQLite 主索引
│   └── autosnap.db-wal
└── _config/
    └── rules.json             # 用户自定义归档/排除规则
```

### 5.3 文件命名规则

`YYYY-MM-DD_HH-mm-ss_<category>_<hash4>.png`

| 段 | 作用 | 示例 | 无 AI 时 |
|---|---|---|---|
| `YYYY-MM-DD_HH-mm-ss` | 主排序键，OS 自带按名排序即按时间排序 | `2026-05-07_14-30-12` | 必填 |
| `<category>` | AI 推断的主类，便于肉眼扫文件名 | `chat` / `code` / `web` | 降级为 `unsorted` 或 `<source-app>`（如 `wechat`、`vscode`） |
| `<hash4>` | SHA256 前 4 位，避免同秒内重名 + 辅助去重 | `a3f1` | 必填 |

**不在文件名里塞标题/摘要**：可读性差、Windows 路径长度限制 260 字符、含中文/emoji 会破坏跨平台同步。

### 5.4 为什么不按类别分一级目录

```
AutoSnap/chat/2026/05/07/...    ← 拒绝
AutoSnap/code/2026/05/07/...
```

致命缺点：
1. 类别由 AI 推断，**会变更和误判**。改类等于跨目录移动文件，破坏同步软件的去重和历史记录
2. 一张截图可能命中多个类别（聊天里的代码截图），物理目录天然单选
3. 离线模式下没有类别，全堆在 `unsorted/` 等于没分类

类别留给数据库 + 文件名片段，物理目录只用最稳定的维度——**时间**。

---

## 6. 数据模型（SQLite Schema）

```sql
-- 主表：一行一张截图
CREATE TABLE screenshots (
  id              TEXT PRIMARY KEY,           -- ULID，时间有序
  sha256          TEXT NOT NULL UNIQUE,       -- 内容哈希，去重主键
  archived_path   TEXT NOT NULL,              -- 相对 AutoSnap/ 根的路径
  original_path   TEXT,                       -- 捕获前的原路径（剪贴板直采时为 NULL）
  captured_at     INTEGER NOT NULL,           -- Unix ms
  archived_at     INTEGER NOT NULL,
  width           INTEGER NOT NULL,
  height          INTEGER NOT NULL,
  bytes           INTEGER NOT NULL,
  format          TEXT NOT NULL,              -- png/jpg/heic/webp
  source_app      TEXT,                       -- 推断的应用 bundle id 或进程名
  source_window   TEXT,                       -- 窗口标题
  device_id       TEXT NOT NULL,              -- 本机 UUID
  platform        TEXT NOT NULL,              -- macos/windows/ios/android
  is_favorite     INTEGER NOT NULL DEFAULT 0,
  ai_status       TEXT NOT NULL DEFAULT 'pending',  -- pending/done/failed/skipped
  deleted_at      INTEGER                     -- 软删除时间戳
);
CREATE INDEX idx_screenshots_captured_at ON screenshots(captured_at DESC);
CREATE INDEX idx_screenshots_source_app ON screenshots(source_app);

-- AI 标注：1:1，未标注的截图此表无记录
CREATE TABLE annotations (
  screenshot_id   TEXT PRIMARY KEY REFERENCES screenshots(id) ON DELETE CASCADE,
  category        TEXT NOT NULL,
  category_conf   REAL NOT NULL,              -- 0-1
  title           TEXT,
  summary         TEXT,
  has_sensitive   INTEGER NOT NULL DEFAULT 0,
  sensitive_types TEXT,                       -- JSON 数组
  model           TEXT NOT NULL,              -- "claude-haiku-4-5" 等
  cost_usd        REAL,
  annotated_at    INTEGER NOT NULL
);

-- 标签：多对多
CREATE TABLE tags (
  id    INTEGER PRIMARY KEY,
  name  TEXT NOT NULL UNIQUE
);
CREATE TABLE screenshot_tags (
  screenshot_id TEXT NOT NULL REFERENCES screenshots(id) ON DELETE CASCADE,
  tag_id        INTEGER NOT NULL REFERENCES tags(id),
  source        TEXT NOT NULL,                -- 'ai' | 'user' | 'rule'
  PRIMARY KEY (screenshot_id, tag_id)
);

-- OCR 文本（即使没 AI 也可由本地 OCR 写入）
CREATE TABLE ocr (
  screenshot_id TEXT PRIMARY KEY REFERENCES screenshots(id) ON DELETE CASCADE,
  text          TEXT NOT NULL,
  lang          TEXT,
  engine        TEXT NOT NULL,                -- 'tesseract' | 'apple-vision' | 'win-ocr'
  ocr_at        INTEGER NOT NULL
);

-- 全文检索：title + summary + ocr_text + tags + window_title 拼接
CREATE VIRTUAL TABLE search_fts USING fts5(
  screenshot_id UNINDEXED,
  content,
  tokenize = 'unicode61'   -- 中文分词待验证：可换 ICU / jieba 扩展
);

-- 嵌入向量预留（v1 启用）
CREATE TABLE embeddings (
  screenshot_id TEXT PRIMARY KEY REFERENCES screenshots(id) ON DELETE CASCADE,
  model         TEXT NOT NULL,
  dim           INTEGER NOT NULL,
  vector        BLOB NOT NULL                 -- float32 packed
);

-- AI 调用审计（用户可查可清）
CREATE TABLE ai_audit (
  id            INTEGER PRIMARY KEY,
  screenshot_id TEXT REFERENCES screenshots(id),
  provider      TEXT NOT NULL,
  model         TEXT NOT NULL,
  cost_usd      REAL,
  latency_ms    INTEGER,
  status        TEXT NOT NULL,                -- ok / blocked_sensitive / network_error / parse_error
  called_at     INTEGER NOT NULL
);
```

**关键设计点**：
- `sha256` 唯一约束 = 跨设备去重的天然基础
- AI 相关字段全部独立成表（`annotations` / `ocr` / `embeddings`）→ **主表能脱离 AI 独立工作**
- `category` 不做外键到独立 categories 表，用字符串 → 用户自定义不污染 schema
- `ai_status` 让 UI 能区分"AI 队列待处理 / 已完成 / 失败 / 用户主动跳过"

---

## 7. 类别体系（Taxonomy）

### 7.1 默认 16 类

| key | 名称 | 视觉特征 |
|---|---|---|
| `chat` | 聊天对话 | 气泡布局、头像列、时间戳 |
| `web` | 网页文章 | 浏览器 chrome、长文本、URL 栏 |
| `code` | 代码 | 等宽字体、语法高亮、行号 |
| `terminal` | 终端 | 黑/暗背景、命令提示符 |
| `error` | 错误报错 | 红色 toast / 堆栈 / 蓝屏 |
| `design` | 设计参考 | 色块密集、低文字密度 |
| `form` | 表单 | 输入框列、Label-Input 对 |
| `receipt` | 票据订单 | 金额、订单号、商品列表 |
| `map` | 地图 | 地图渲染、定位针 |
| `video` | 视频画面 | 黑边、播放控件、字幕 |
| `table` | 表格数据 | 网格线、表头 |
| `qr` | 二维码 | 方形矩阵 |
| `id_doc` | 证件类 | **本地处理，不传 AI** |
| `social` | 社媒动态 | 动态卡片、点赞/转发图标 |
| `email` | 邮件 | 邮件头、收发件人 |
| `slide` | 演示稿 | 16:9、大字标题 |
| `misc` | 其他 | 未匹配上的 |

### 7.2 类别 vs 标签 的分工

| 维度 | 类别 (category) | 标签 (tags) |
|---|---|---|
| 数量 | 单选，1 个 | 多选，0..N |
| 来源 | AI 主推断 | AI 抽取 + 用户加 + 规则生成 |
| 稳定性 | 一旦定下不轻易变 | 随时增删 |
| 用途 | 文件名片段 + 浏览树 | 搜索过滤、收藏标记 |
| 例 | `chat` | `#工作`、`#老板`、`#待办`、`#bug-1234` |

"既是聊天又是代码"：类别选 `chat`（外层容器），标签加 `code-snippet`。

### 7.3 用户自定义类别

```jsonc
// _config/rules.json
{
  "custom_categories": [
    {
      "key": "meeting_notes",          // [a-z0-9_]，会进文件名
      "label": "会议纪要",
      "ai_hint": "包含会议主题、发言要点、行动项的截图",
      "fallback_keywords": ["议题", "纪要", "Action Item"]
    }
  ]
}
```

- 自定义类别**只影响新归档**，旧文件不批量改名（避免破坏同步历史）
- 用户可对单张截图"重新分类"，触发改名 + meta 更新
- 删除自定义类别时已归档文件保留原文件名，DB 类别置为 `misc`

---

## 8. AI 集成

### 8.1 模型选型对比（单张 1280×800 截图基准）

| 模型 | 单张成本 (估算) | p50 延迟 | 中文 | 隐私 | 备注 |
|---|---|---|---|---|---|
| **Claude Haiku 4.5** | ~$0.0015 | 1.5–2.5s | 优秀 | API 默认不训练 | JSON / tool use 稳；prompt caching 90% off |
| Claude Sonnet 4.6 | ~$0.012 | 2–4s | 优秀 | 同上 | 精度上限高，旗舰但贵 8× |
| GPT-4o-mini | ~$0.0008–0.0015 | 0.8–1.5s | 良好 | 默认不训练 | 性价比对标 Haiku |
| Gemini 2.5 Flash | ~$0.0005–0.001 | 0.8–1.8s | 良好 | 付费层默认不训练 | **最便宜** |
| **Qwen2.5-VL 7B** (本地) | $0 | 3–8s (M1) | **优秀** (中文母语) | 100% 本地 | Ollama 一键，INT4 ~5GB |
| moondream2 (本地) | $0 | 0.5–2s | 一般 | 100% 本地 | <2GB，做粗筛分级 |

**默认推荐：Claude Haiku 4.5**
1. JSON / tool use 输出稳定（截图分类高度依赖结构化输出）
2. 中文理解优秀
3. prompt caching 对反复使用的 system prompt 极友好
4. 隐私默认不训练

用户可在设置面板下拉切换 provider；v2 提供 Ollama 本地模式。

### 8.2 单张截图处理 Pipeline

```
Watcher (FS/clipboard event)
        │
        ▼
1. Ingest (basic archive ALWAYS)
   - 时间归档目录 / 文件名规范化
   - 写 SQLite: ai_status=pending
        │
        ▼
2. Pre-filter
   - pHash 去重 (vs 最近 50 张)
   - 本地敏感检测 (regex + OCR keyword)
   - 用户配额 / 时段 / 应用 黑名单
        │
   skip ┴─── proceed
              │
              ▼
3. Preprocess
   - resize 长边 ≤ 1568 px
   - JPEG quality 75 (≤ 200KB 目标)
   - (可选) 敏感区域 mask
              │
              ▼
4. Prompt Build
   - system (cached, 见 §8.5)
   - user: image + categories[] + context
   - tool_choice: emit_annotation
              │
              ▼
5. Call LLM
   - timeout 20s, retry 2x (1s/4s backoff)
   - 429 → degrade to local model
   - 5xx → enqueue retry (max 24h)
              │
   fail ──┬───┴── ok
   ai_failed       │
   (后台重试)       ▼
              6. Postprocess
                 - 校验 JSON (jsonschema)
                 - 截断 title/summary
                 - 写 annotations + FTS5
                 - 生成缩略图
                 - ai_status=done, UI refresh
```

**关键说明**：
- 预处理后图片 token 数从 ~1500 降到 ~600（按 768 px tile 计费）
- JPEG q75 对截图（含文字）实测 OCR 准确率下降 <2%，体积压缩 5–10×
- **不要** resize 到 <1024，否则小字 OCR 显著退化

### 8.3 输出 JSON Schema

```json
{
  "type": "object",
  "required": ["category", "title", "summary", "tags", "ocr_text",
               "has_sensitive_info", "confidence"],
  "properties": {
    "category": { "type": "string", "enum": ["chat","web","code","terminal","error",
                  "design","form","receipt","map","video","table","qr","id_doc",
                  "social","email","slide","misc"] },
    "title": { "type": "string", "maxLength": 20 },
    "summary": { "type": "string", "maxLength": 80 },
    "tags": { "type": "array", "maxItems": 6, "items": { "type": "string", "maxLength": 12 } },
    "ocr_text": { "type": "string", "maxLength": 4000 },
    "has_sensitive_info": { "type": "boolean" },
    "sensitive_types": { "type": "array", "items": { "type": "string",
                         "enum": ["password","id_card","bank_card","phone",
                                  "private_chat","api_key","other"] } },
    "confidence": { "type": "number", "minimum": 0, "maximum": 1 }
  }
}
```

### 8.4 成本控制（Baseline 100 张/天）

| 手段 | 节省比例 | 实现要点 |
|---|---|---|
| 图片压缩 (1568 px + JPEG q75) | 40–60% | 见 §8.2 |
| pHash 去重 | 20–40% | 64-bit pHash，海明距离 ≤ 5 视为重复，复用最近一张标注 |
| Batch API | 50% | 累积 1–24h 一批；提供"立即处理"开关 |
| Prompt Caching | 30–50% | system + 类别列表稳定，TTL 5 min/1 h |
| 分级处理 | 60–80% | 本地 moondream 粗筛 → confidence<0.5 才送云端 |
| 用户配额 | 上限保护 | 每日/每月 USD 上限；触顶 fallback 到"仅时间归档" |

**叠加效果**：100 张/天 × Claude Haiku，名义 $4.5/月 → 实际 ~$1.2/月。Gemini Flash 可再压一半。

### 8.5 Prompt 模板（Production-Ready）

```text
========== SYSTEM (cached) ==========
You are AutoSnap's screenshot annotator. You receive a single screenshot
and must return ONE structured annotation by calling the `emit_annotation` tool.

Rules:
1. ALWAYS call the tool exactly once. Never reply in plain text.
2. `category` MUST be one of the values in <allowed_categories>.
   If genuinely uncertain, use "misc" and set confidence < 0.5.
3. `title` ≤ 20 characters, in the dominant language of the screenshot.
4. `summary` ≤ 80 characters, factual, no marketing tone.
5. `tags`: ≤ 6 short keywords, lowercase, no punctuation.
   Prefer concrete entities (app name, domain, language, framework).
6. `ocr_text`: extract all visible text verbatim, preserve line breaks,
   truncate at 4000 chars. If image is mostly graphical, return "".
7. `has_sensitive_info`: true if you see passwords, full credit-card numbers,
   ID numbers, private 1-on-1 chats, API keys, or medical records.
   Populate `sensitive_types` accordingly.
8. `confidence`: overall confidence in category + title (0–1).
9. Be concise. Do not hallucinate text not visible in the image.

========== USER ==========
<allowed_categories>
{{ CATEGORIES_JSON }}      // 运行时注入，含用户自定义类别
</allowed_categories>

<context>
captured_at: {{ ISO_TIMESTAMP }}
source_app: {{ APP_NAME or "unknown" }}
locale_hint: {{ "zh-CN" or "en-US" }}
</context>

[image: <attached>]
```

Tool 定义（Anthropic 风格，OpenAI/Gemini 同构）：
```json
{
  "name": "emit_annotation",
  "description": "Emit the structured annotation for the screenshot.",
  "input_schema": { /* §8.3 中的 schema */ }
}
```
设置 `tool_choice = {"type":"tool","name":"emit_annotation"}` 强制 tool use → 严格 JSON，无解析失败风险。

### 8.6 AI 模块对外契约

```rust
// AI 模块向 Archiver 暴露的唯一函数
pub async fn annotate(
    image_path: &Path,
    ctx: &Context,           // captured_at, source_app, locale_hint
) -> Option<Annotation>;     // 永远不 panic、永远不 throw
```

**契约 (核心 invariant)**：
1. `annotate()` **永远不 panic**；调用方收到 `None` 即视为 AI 不可用
2. `annotate()` **不修改文件系统**；写库由 archiver 完成
3. AI 模块**不依赖** archiver / DB 层；只依赖 image bytes 和配置
4. 所有 provider 实现同一个 `VisionProvider` trait（见 §3.1）

**故障演练 (CI 必跑)**：
- 拔网线 → 截图仍归档，AI 字段为空
- API key 故意填错 → 同上 + 设置页红点提醒
- Provider 返回非法 JSON → 重试 2 次 → 标 `ai_failed`，不污染 DB
- 杀掉 ollama 进程 → 自动 fallback 到云端（若已配置）或仅时间归档

---

## 9. 查询与回溯 UX

### 9.1 时间轴视图（默认入口）

```
┌─ AutoSnap ────────────────────────────────────────┐
│ [时间轴] [类别] [搜索] [收藏]              ⚙       │
├───────────────────────────────────────────────────┤
│  今天 · 5月7日 周四                  共 12 张     │
│  ┌────┐ ┌────┐ ┌────┐ ┌────┐                      │
│  │chat│ │code│ │web │ │... │                      │
│  └────┘ └────┘ └────┘ └────┘                      │
│  14:30  15:02  15:48  16:20                       │
│                                                    │
│  昨天 · 5月6日                       共 23 张     │
│  ...                                              │
│                                                    │
│  ── 5 月 1 日 ──                                  │
│  [折叠：5 月第 1 周 共 87 张 ▾]                   │
└───────────────────────────────────────────────────┘
```

- 默认按"日"分组，缩略图横向滚动；周/月切换在右上角
- 缩略图右下角小角标显示类别 icon
- 悬停（移动端长按）显示 AI 标题；没有就显示 `14:30:12 · WeChat`

### 9.2 类别浏览

```
┌─ 类别 ──────────────┬──────────────────────────────┐
│ 全部     (1,284)    │  ┌──────┐ ┌──────┐ ┌──────┐  │
│ ─────────────────── │  │ chat │ │ chat │ │ chat │  │
│ 聊天对话    (412)   │  └──────┘ └──────┘ └──────┘  │
│ 代码        (203)   │  老板 5/7  同事 5/6  群 5/6  │
│ 网页        (187)   │                              │
│ 错误报错    (56)    │  ...                         │
│ ─────────────────── │                              │
│ # 标签              │                              │
│   工作      (234)   │                              │
│   老板      (45)    │                              │
│ ─────────────────── │                              │
│ 未分类      (12) ⚠  │                              │
└─────────────────────┴──────────────────────────────┘
```

"未分类"永远显示在底部，作为"AI 队列待处理 + 无 AI 时全部进这"的兜底。

### 9.3 关键词 / 语义搜索

```
┌──────────────────────────────────────────────────────┐
│ 🔍 上周老板发的会议要点                  [×] [搜索]   │
├──────────────────────────────────────────────────────┤
│ 解析为：时间=4/28-5/4  类别=chat  关键词=会议+要点   │
│ ↓ 不对？[手动编辑过滤器]                              │
├──────────────────────────────────────────────────────┤
│ ▣ 5月3日 21:14  WeChat                               │
│   "下周一 10 点产品评审，准备这三件事..."             │
│   [chat] #工作 #老板                  匹配度 ★★★★    │
└──────────────────────────────────────────────────────┘
```

**搜索处理流程**：
```
用户输入
  ├─ 时间词抽取（"上周" / "昨天")  → captured_at 范围
  ├─ 类别词抽取（"聊天" / "代码")  → category 过滤
  ├─ 应用名抽取（"微信" / "VSCode") → source_app 过滤
  └─ 剩余 token                   → FTS5 全文 + (v1) 向量召回
排序：FTS BM25 × 0.6 + 向量相似 × 0.3 + 时间衰减 × 0.1
```

未标注的截图仍能被找到（用 ocr + 文件名 + source_app 匹配），列表里加灰色 `未标注` 角标。

### 9.4 快捷回溯（最常用、最被低估）

| 触发 | 行为 |
|---|---|
| `Cmd/Ctrl+Shift+A` | 唤起浮窗，默认显示"最近 1 小时" |
| 浮窗顶部 chips | `[最近 5 分钟] [1 小时] [今天] [此应用] [收藏]` |
| "此应用" | 自动用前台应用名做过滤 |
| 拖拽缩略图 | 直接拖进任何 app（IM、邮件、文档） |

```
┌─ AutoSnap 快捷回溯 ──────────────[置顶][⚙]─┐
│ [5min] [1h✓] [今天] [此 app] [收藏]         │
├─────────────────────────────────────────────┤
│ ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐               │
│ │  │ │  │ │  │ │  │ │  │ │  │               │
│ └──┘ └──┘ └──┘ └──┘ └──┘ └──┘               │
│ 16:20 16:05 15:48 15:32 15:18 15:02         │
└─────────────────────────────────────────────┘
```

这个入口**完全不依赖 AI**，是无 AI 模式下的主力工具。

---

## 10. "无 AI 模式"降级承诺

| 入口 | 有 AI | 无 AI（仅时间 + 文件名 + 本地 OCR） |
|---|---|---|
| 时间轴 | 缩略图 + 类别角标 + 标题 | 缩略图 + 时间 + `source_app`，**完整可用** |
| 类别浏览 | 16 类按内容分布 | 退化为按 `source_app` 分组（微信 / Chrome / VSCode），仍然有用 |
| 搜索 | 自然语言 + 语义 | 关键词在 OCR + 文件名 + 应用名 中检索；时间/应用过滤完整 |
| 快捷回溯 | 完全相同 | **完全相同**，核心场景 |
| 去重 | sha256 完整 | 完整 |
| 收藏/标签 | 完整 | 完整（手动加） |

**OCR 是中间档**：本地引擎（Apple Vision / Win.Media.Ocr / Tesseract）零成本零隐私，**默认开启**，不需要 API key 也跑。

**基线承诺一句话**：
> "不掏 API key，AutoSnap 也是一个比系统截图文件夹好用 10 倍的归档器。"

---

## 11. 隐私与控制

### 11.1 默认不送 AI 的内容（本地三层拦截）

按性能从轻到重：

1. **正则 + 关键词**（毫秒级）
   - 信用卡 Luhn 校验、身份证 18 位校验码
   - 邮箱、手机号正则
   - 关键词：`密码 / password / 验证码 / OTP / 私钥 / secret / api[_-]?key`
2. **本地 OCR + 关键词匹配**（100–500 ms）
3. **(可选) 本地小 VLM** — 用 moondream 二分类问答："Does this image contain login form / credit card / private chat?"（1–3 s）

命中后行为可配置：`block`（不发云端）/ `mask`（模糊敏感区再发）/ `ask`（弹窗询问）。

### 11.2 用户配置（`_config/rules.json`）

```jsonc
{
  "exclude": {
    "apps": ["1Password", "Bitwarden", "com.tencent.WeWork"],
    "paths": ["~/Pictures/Screenshots/private/"],
    "windows": ["*Incognito*", "*隐私模式*"],
    "time_ranges": [
      { "weekday": [1,2,3,4,5], "from": "09:30", "to": "10:30", "label": "晨会" }
    ]
  },
  "ai_optout": {
    "categories": ["id_doc", "receipt"],
    "apps": ["BankApp"]
  }
}
```

UI 入口：设置 → 隐私 → 三 Tab：「排除应用 / 排除目录 / 排除时段」。

### 11.3 数据流向声明（必须明示）

| 模式 | 图片去哪 | 保留多久 | 谁能看到 |
|---|---|---|---|
| Cloud (BYOK) | 用户自己的 Anthropic/OpenAI/Google 账号 | 取决于 provider；Anthropic 可申请 zero-retention | 仅你和 provider |
| Local Only | 不出本机 | 永久（本地） | 仅你 |
| Off | 不发送 | — | 仅你 |

### 11.4 数据导出 / 删除

- **导出**：生成 `.zip`，含 `images/ + meta.json + autosnap.db`
- **单张删除**：默认软删除（移到 `_trash/`，30 天后清），可一键彻底删除
- **类别批量删除**：例"删除所有 `id_doc` 类截图"，二次确认
- **撤回 AI 标注**："忘记 AI 对此图的所有判断" → 删 `annotations`/`ocr`/`embeddings` 行，保留原图
- **完全清空**：清 `_index/` + `_trash/`，**不动用户原图原路径**

---

## 12. 实施路线

### v0 — Windows-only MVP（4 周 / 20 人天）

**范围**：仅 Windows。
- Capture Watcher（监听 `Pictures/Screenshots/` + 剪贴板）
- Archiver（按日期归档 + 文件名规范化 + sha256 去重）
- SQLite 索引 + 本地 OCR（Windows.Media.Ocr）
- 基础 UI：时间轴 + 关键词搜索 + 快捷回溯（`Ctrl+Shift+A`）
- NSIS 安装包 + EV 签名

**不含**：AI 标注、Mac/Mobile、同步。

**验收**：
- 全新 Windows 11 机器从下载到归档第一张截图 ≤ 60 秒、≤ 5 次点击
- 安装包 ≤ 15 MB
- 1000 张截图下时间线滚动 60fps、搜索 < 200ms
- 关掉网络全功能可用

### v1 — AI 标注 + Mac 端（3 周 / 15 人天）

**范围**：
- Claude Haiku 4.5 Provider + BYOK 设置页
- AI 标注 → annotations 表 + FTS5 写入
- 三层敏感拦截
- pHash 去重 + 配额控制
- Mac 版（同一份 Tauri 代码 + Apple notarization）
- 云盘目录监听（让用户自配 OneDrive/iCloud 路径，把手机截图自动吃进来）

**验收**：
- 一张新截图从落盘到出现 AI 标签 ≤ 10 秒
- 标注失败时归档不受影响（断网测试）
- Mac 安装包通过 notarization
- 单张截图标注成本 < $0.002

### v2 — 语义搜索 + 真同步 + 移动壳（6 周 / 30 人天）

**范围**：
- 本地 CLIP embedding + sqlite-vec 语义搜索
- 多 Provider 切换（OpenAI / Gemini / Ollama 本地模式）
- CRDT-based DB 同步（基于云盘 changelog）
- Android 原生轻 App（FileObserver + ForegroundService）
- iOS Shortcuts 集成（"截图后自动上传到云盘"引导）

**验收**：
- "找上周关于地图的截图"这类语义查询命中率 ≥ 80%
- 双设备 1 小时内数据一致
- iOS 通过 Shortcuts 完成截图归档闭环

---

## 13. 关键技术风险

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| 1 | Windows SmartScreen 拦未签名 exe | v0 装机率腰斩 | EV 代码签名（$300/年）；备选 Azure Trusted Signing |
| 2 | iOS 无法后台监听截图 | iPhone 端体验残缺 | v0 走云盘代理；v2 用 Shortcuts/Share Extension 让用户主动触发；不假装能后台监听 |
| 3 | 多模态 API 成本失控 | BYOK 用户单月数十美元 | 默认 Haiku/Flash + pHash 去重 + 本地 OCR 预过滤 + 用户配额 |
| 4 | OneDrive 文件锁导致 move 失败 | 归档丢截图 | "copy + verify + delete" 而非 rename；锁定时重试 3 次后降级为只索引不移动 |
| 5 | 用户对"上传截图"恐慌 | 核心用户拒绝开 AI | 默认关闭 AI；本地敏感拦截；Local Only 模式（Ollama）；开源 Annotator 模块建立信任 |
| 6 | SQLite FTS5 中文分词差 | 中文搜索召回低 | v0 用 `unicode61` 字切；v1 评估 ICU / jieba 扩展 |
| 7 | Android 厂商 ROM 杀后台 | Android 端漏截图 | 写专门的"小米/华为/三星保活引导页" |

---

## 14. 开放问题（待验证 / 决策）

1. **Anthropic Batch API 对图像输入的具体限制**（待官方文档复核）
2. **Gemini 付费层是否对 BYOK 完全 zero-retention**（待验证）
3. **Qwen2.5-VL 在 Ollama 官方仓库的 vision 支持稳定性**（2026-05 仍在迭代）
4. **是否完全开源** vs 只开源 Annotator 模块（影响信任 vs 商业化空间）
5. **托管方案**：v2 是否提供 "AutoSnap Cloud"（按量计费给非技术用户），还是坚持纯 BYOK
6. **本地敏感分类器**：v1 用规则版还是直接上小模型版？规则版可先上线
7. **同步冲突合并策略**：同一张图被两台设备同时归档（sha256 重复但路径不同）的合并细节
8. **EV 证书替代**：Azure Trusted Signing 当前定价与 EV 证书的 TCO 对比

---

## 15. 设计原则速查表

每次做技术决策时回头看这 6 条：

1. **不与系统截图工具冲突** — 用户照常按 Win+Shift+S
2. **基础归档不依赖 AI** — 无 API key 也是好用工具
3. **物理目录自解释** — 卸载 app 后用文件管理器照样找得到
4. **隐私本地优先** — 敏感内容默认不出本机
5. **Windows 装机零阻力** — 双击安装、无 UAC、无配置弹窗
6. **AI 模块永不 panic** — 它挂掉时主流程必须继续运行
