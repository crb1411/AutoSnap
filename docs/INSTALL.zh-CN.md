# AutoSnap 安装指南（中文）

> English / 开发者请看 [README.md](../README.md) 中的 *Windows Developer Quick Start* 章节。

本文档面向**普通 Windows 用户**，从下载到第一张截图被归档，全程不需要命令行、不需要 Python 环境。

---

## 第 1 步 · 下载安装包

打开 GitHub Releases 页面：

> <https://github.com/crb1411/AutoSnap/releases>

在最新版本下找 **Assets** 折叠区，点击 `AutoSnap-Setup.exe` 下载（约 30–80 MB，PyInstaller bootstrap 单文件）。

如果你看到的是 **Source code (zip / tar.gz)** 而没有 `AutoSnap-Setup.exe`，说明这个 release 还在打包中或上一次构建失败了，请：

- 切换到稍早的 release 版本
- 或者去 [Actions → Build Windows Installer](https://github.com/crb1411/AutoSnap/actions/workflows/windows-installer.yml) 找最近一次绿色的 run，下载它的 `AutoSnap-Setup-*` artifact

---

## 第 2 步 · 双击安装

1. 双击下载到的 `AutoSnap-Setup.exe`
2. 如果 Windows SmartScreen 弹出**"Windows 已保护你的电脑"**：
   - 点击灰色的 **更多信息**
   - 出现 **仍要运行** 按钮，点它
   - 这是因为安装器目前没有 EV 代码签名（v1 计划购买，参见 DESIGN 文档 §13）
3. 安装器会弹一个对话框告诉你：

   ```
   Install AutoSnap to:
   C:\Users\<你>\AppData\Local\Programs\AutoSnap

   This does not require administrator permission.
   ```

   点 **是 (Yes)** 确认。整个安装大约 5–15 秒。
4. 完成后会问 **Launch it now?**，点 **是** 直接启动。

> 安装器**不需要管理员权限**，不会修改系统目录、不会改注册表全局键，所有内容只写到当前用户的 `AppData` 下。

---

## 第 3 步 · 第一次启动

主界面打开后：

1. 检查"归档目录"是否合你心意（默认 `C:\Users\<你>\Documents\AutoSnap`）
   - 想多端同步可改成 OneDrive / iCloud / 坚果云的子目录
2. 检查"监听目录"——默认会包含：
   - `C:\Users\<你>\Pictures\Screenshots`（`Win+PrtScn` 默认目录）
   - 剪贴板（捕获 `Win+Shift+S` 那种只进剪贴板的截图）
3. 点 **Start watching** 开始后台监听

---

## 第 4 步 · 验证一切正常

1. 按 `Win+PrtScn` 截一张全屏图
2. 等 1–2 秒，AutoSnap 主界面应该多出一个缩略图
3. 打开归档目录，应该能看到类似：
   ```
   Documents\AutoSnap\2026\05\07\2026-05-07_15-32-11_unsorted_a3f1b2.png
   ```
4. 再按 `Win+Shift+S` 框选截一张（这种是只进剪贴板的）
5. 等 2–3 秒（剪贴板轮询周期），AutoSnap 也应该捕获到

如果某一步没反应，看下面的「常见问题」。

---

## 第 5 步（可选）· 启用 AI 标注

默认 AutoSnap 完全离线，不会把你的截图发到任何外部服务。如果你想让它自动给截图打标签 / 写标题：

1. 准备一个 OpenAI API Key（[平台地址](https://platform.openai.com/api-keys)）
2. 打开 PowerShell（开始菜单搜 "PowerShell"），运行：
   ```powershell
   setx OPENAI_API_KEY "sk-你的密钥"
   setx AUTOSNAP_ENABLE_AI "1"
   setx AUTOSNAP_OPENAI_MODEL "gpt-4.1-mini"
   ```
3. **完全退出 AutoSnap 再重启**（`setx` 设置的环境变量只对新进程生效）
4. 之后新截图会被异步送去 AI 标注；标注失败不影响基础归档

> 想关闭：把 `AUTOSNAP_ENABLE_AI` 设为 `0`，或者删除该环境变量。
> 隐私顾虑：v0 是个最小实现，**不会**做敏感信息本地拦截，**也不会**给你截图打码。涉及密码、身份证、银行卡的截图请暂时不要开启 AI（v1 会加敏感拦截，参见 DESIGN §11）。

---

## 卸载

两种方式：

**方式 A · Windows 设置**

1. 打开 **设置 → 应用 → 已安装的应用**
2. 搜索 "AutoSnap"，点 **卸载**

**方式 B · 直接运行卸载脚本**

打开 `C:\Users\<你>\AppData\Local\Programs\AutoSnap\Uninstall AutoSnap.bat`，双击。

> 卸载**不会删除**你的归档目录（`Documents\AutoSnap`）和配置文件（`AppData\Roaming\AutoSnap\config.json`）。如果想完全清理，手动删这两个目录即可。

---

## 常见问题

### Q1：双击 `AutoSnap-Setup.exe` 后 Windows Defender 拦截 / 删除文件
v0 安装器没有 EV 代码签名，部分 Defender 策略会激进拦截。两种处置：

- 在 Defender 隔离区把它"还原"（恢复），加入排除项后再运行
- 或者从源码本地构建（见 README 开发者章节），完全跳过下载步骤

### Q2：装完了，按截图键 AutoSnap 没反应
按这个顺序排查：

1. AutoSnap 主界面是否点过 **Start watching**？没点的话不会监听
2. 你的截图实际保存在哪里？打开 `Pictures\Screenshots` 看有没有新文件
   - 如果在别的目录（比如 ShareX 改过路径），去 AutoSnap 设置里把那个目录加入"监听目录"
3. 如果你用的是 `Win+Shift+S`，截完别忘了把截图**贴出来或保留在剪贴板**——AutoSnap 是从剪贴板读的，如果你立刻又复制了别的内容会被覆盖
4. 看 `%APPDATA%\AutoSnap\` 下有没有日志文件，里面会记录监听状态

### Q3：归档目录想换到 OneDrive 实现多端同步
- 在 AutoSnap 设置里把"归档目录"改到 `C:\Users\<你>\OneDrive\AutoSnap`（或 iCloud / 坚果云对应路径）
- 之后所有新归档会自动同步到云
- **注意**：SQLite 索引数据库默认也在归档目录里（`_index/autosnap.db`），多设备并发写有可能损坏。建议**只在一台设备上开启监听**，其他设备只用来浏览（v2 会做基于 changelog 的安全多端同步）

### Q4：手机截图也想归档
v0 不做手机端 App，但可以这样：

- **iPhone**：把 iCloud 照片同步打开 → Mac 上 iCloud Drive 会同步 → AutoSnap 监听 iCloud Drive 的截图目录（v0 的 Mac 版还在路上，目前临时方案是 iPhone → iCloud → Windows OneDrive 中转）
- **Android**：用 OneDrive / Google Drive 客户端开启相册自动上传，AutoSnap 监听桌面端这些云盘对应的本地目录即可

### Q5：能不替代我现在用的 ShareX / Snipaste 吗？
完全可以共存。AutoSnap 不抢任何快捷键，只在背后监听文件和剪贴板。ShareX / Snipaste 截完图后保存到磁盘 → AutoSnap 立刻归档。

### Q6：releases 页只有源码，没有 `AutoSnap-Setup.exe`
说明该 tag 的构建还没跑完或者失败了。打开 [Actions](https://github.com/crb1411/AutoSnap/actions/workflows/windows-installer.yml)：

- 如果 workflow 还在跑（黄色圆圈），等它结束
- 如果是绿色✅，刷新 release 页应该出现 asset
- 如果是红色❌，从 Actions run 里下 `pyinstaller-build-log-*` artifact 反馈给开发者

---

## 一句话总结

> **下载 → 双击 → 选目录 → Start watching → 照常截图。AutoSnap 在背后帮你按时间归档好。**

需要更深入了解架构和长期路线，参见 [docs/DESIGN.md](DESIGN.md)。
