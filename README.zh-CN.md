# AutoSnap

> English: [README.md](README.md) ｜ 详细安装步骤：[docs/INSTALL.zh-CN.md](docs/INSTALL.zh-CN.md)

AutoSnap 是一个开源的**截图自动归档器**。它**不替换**你现有的截图快捷键，而是在背后监听截图保存目录和剪贴板，自动把新截图按"时间 + 内容"复制到一个规范的归档目录，写入 SQLite 索引，方便后续按时间或关键词回溯。

本仓库目前是 Windows-first 的 v0 实现，用 Python + Tkinter 写成，依赖少、能立刻跑起来；长期会迁移到 Tauri + Rust 桌面应用（参见 [docs/DESIGN.md](docs/DESIGN.md)）。

## v0 已经能做什么

- **不打扰原有截图习惯**：照常按 `Win+PrtScn` / `Win+Shift+S`，AutoSnap 在背后归档。
- **覆盖剪贴板截图**：`Win+Shift+S` 默认只进剪贴板不落盘，AutoSnap 通过轮询剪贴板把它捕获下来。
- **规范命名归档**：`YYYY/MM/DD/YYYY-MM-DD_HH-mm-ss_<category>_<hash>.png`，卸载 App 后用文件管理器照样找得到。
- **不动原文件**：AutoSnap 只复制 + 索引，不会移动或删除你原本的截图。
- **SHA-256 自动去重**：同一张图不会被归档两次。
- **SQLite 索引 + sidecar JSON 元数据**：单机零运维，断网完全可用。
- **本地 Tkinter UI**：时间轴浏览、关键词搜索、导入已有文件夹、一键打开归档目录。
- **AI 标注是可选项**：配 OpenAI API Key 后自动给截图打标签 / 写标题；不配也能用，基础归档完整可用。

## 一句话安装（Windows 普通用户）

1. 打开 <https://github.com/crb1411/AutoSnap/releases>
2. 下载最新的 `AutoSnap-Setup.exe`
3. 双击运行（无需管理员权限）
4. 安装完成后启动 AutoSnap，点 **Start watching**，然后照常截图

详细步骤、常见问题、卸载方式见 [docs/INSTALL.zh-CN.md](docs/INSTALL.zh-CN.md)。

## 默认路径

| 用途 | 默认位置 |
|---|---|
| 归档目录 | `%USERPROFILE%\Documents\AutoSnap` |
| 配置文件 | `%APPDATA%\AutoSnap\config.json` |
| 安装目录 | `%LOCALAPPDATA%\Programs\AutoSnap` |

想多端同步？把"归档目录"指到你的 OneDrive / iCloud / 坚果云子目录即可——AutoSnap 不需要自建后端。

## 启用 AI 标注（可选，BYOK）

AutoSnap 默认完全不联网。如果想让它自动给截图打标签 / 写标题：

1. 打开 AutoSnap，点顶栏 **设置** → **AI 标注** Tab
2. 勾选 **启用 AI 标注**
3. 在 **OpenAI API Key** 里粘贴你的密钥（`sk-...`）
4. 模型名按需修改（默认 `gpt-4.1-mini`，因为可用模型会随时间变化）
5. 点 **保存**——立即生效，新截图开始走 AI；想给历史截图补标注，点顶栏的 **AI 补标注**

> 想关闭：回设置取消勾选 **启用 AI 标注**，保存即可。基础归档和搜索完全不受影响。
>
> Key 存在本地 `%APPDATA%\AutoSnap\config.json`，不会上传任何外部服务。也支持 `OPENAI_API_KEY` 环境变量作为兜底（设置面板里没填时使用）。

## 开发者快速上手

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m autosnap
```

跑测试：

```bash
python -m unittest discover -s tests
```

本地构建 Windows 安装包：

```bat
scripts\windows_build_installer.bat
```

会产出 `installer-dist\AutoSnap-Setup.exe`。这是一个 PyInstaller bootstrap 安装器，运行后把 AutoSnap 部署到 `%LOCALAPPDATA%\Programs\AutoSnap`。

## 设计文档

完整的产品定位、跨平台路线、技术架构、AI 集成、查询 UX、隐私设计：[docs/DESIGN.md](docs/DESIGN.md)。

## 路线图（摘要）

- **v0**（当前）：Windows + Python/Tkinter，覆盖归档与本地搜索
- **v1**：接入 Claude Haiku 4.5 等多模态 API、Mac 版、本地 OCR
- **v2**：Tauri + Rust 重构桌面端、本地 CLIP 语义检索、Android 原生 App、iOS Shortcuts 集成、跨设备同步（基于用户云盘）

## License

[MIT](LICENSE)
