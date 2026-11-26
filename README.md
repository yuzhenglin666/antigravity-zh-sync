# Antigravity Zh Sync

适用于 Windows 的 Antigravity 桌面版简体中文同步工具。Antigravity 更新并覆盖汉化资源后，后台任务会检查新版本，在客户端彻底退出后补装汉化。

## 安装

从 [最新发布](https://github.com/yuzhenglin666/antigravity-zh-sync/releases/latest) 的 Assets 下载 Windows ZIP，解压后在该目录打开 PowerShell。

### 手动安装

- 已安装 Antigravity 桌面版和 Python 3.12 或更高版本。
- 已安装 Node.js 22 或更高版本，包含 npm。下载依赖和查询新版词库需要联网。

使用平时运行 Antigravity 的 Windows 账户执行安装脚本。执行策略参数仅对这次启动的 PowerShell 进程生效。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install.ps1
```

如果 Antigravity 安装在自定义位置，可追加 `-AntigravityPath 'D:\Apps\Antigravity\Antigravity.exe'`。也可以用 `-PythonPath` 和 `-NodePath` 指定解释器路径。

### 从 v0.1.0 升级

在新版目录按[卸载](#卸载)里的命令移除旧后台任务，再运行上面的安装命令。升级时省略 `-RestoreEnglish`，即可保留已装汉化和原版资源包备份。

### 让 Agent 安装

将以下提示词发给能在本机运行 PowerShell 的 Agent。

```text
请在当前 Windows 账户下帮我安装 Antigravity Zh Sync。项目地址为
https://github.com/yuzhenglin666/antigravity-zh-sync

使用本机已有的最新版，或从该仓库的最新发布页下载 Windows ZIP 并解压。
先阅读 README.md，检查 Antigravity 桌面版、Python 3.12+ 和 Node.js 22+（含 npm）
是否可用。若已有 AntigravityZhSync 后台任务，先核实状态，避免重复安装。
满足要求后，请在项目目录下实际运行 Install.ps1。Antigravity、Python 或 Node.js 装在自定义位置时，
用脚本提供的路径参数。只有缺少依赖、权限不足或需要我处理正在运行的会话时，
再指出具体问题。

安装后运行 Manage.ps1 -Action Status，分别报告后台任务状态和汉化状态。
需要排查时，查看 %LOCALAPPDATA%\AntigravityZhSync\watch.log。
如果日志显示补丁已经准备好、仍在等待客户端退出，请提醒我从系统托盘退出
Antigravity。等日志出现 installed 后再打开客户端。请保留正在运行的会话，
并使用项目自带的备份与还原流程。
```

### 检查安装状态

运行下面的命令可以查看客户端版本、后台任务状态和当前词库。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Manage.ps1 -Action Status
```

| 状态 | 含义 |
| --- | --- |
| `installed` | 当前版本的匹配词库已安装。 |
| `fallback_installed` | 临时词库已安装，后台会继续查找匹配词库。 |
| `waiting_for_exit` | 补丁已准备好。保存工作后，从系统托盘彻底退出 Antigravity。 |
| `ready_to_apply` | 客户端已退出，补丁等待后台任务安装。 |
| `staged_inactive` | 补丁已暂存，后台任务已禁用或未注册。 |
| `awaiting_check` | 当前资源还未确认已汉化。可查看最近一条日志。 |
| `client_files_missing` | 安装路径下找不到客户端程序或资源包。 |

需要立即检查时，运行以下命令。已有补丁在等待退出时，也可以用它重新查询词库。若暂时查不到匹配词库，已备好的匹配补丁会保留。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Manage.ps1 -Action CheckNow
```

后台任务叫 `AntigravityZhSync`，日志位于 `%LOCALAPPDATA%\AntigravityZhSync\watch.log`。

### 托盘通知

补丁准备好和安装完成时，Windows 会收到标题为「Antigravity 汉化同步」的通知。发送方可能显示为 Windows PowerShell 5.1。若看不到横幅，可在 Windows 的「系统 → 通知」中检查通知开关和「请勿打扰」。希望静默运行时，在安装命令中加 `-NoNotifications`。

## 更新与兼容性

已在 Windows 版 Antigravity **2.35.2** 上验证自动补装和还原，内置词库版本为 **v3.3.65**。后台任务随 Windows 登录启动，Antigravity 的官方更新照常进行。

检测到新版时，工具会查询上游明确标注适配的词库。专用词库尚未发布时，会先用内置词库在副本上生成补丁并检查资源包和 JavaScript 语法。检查通过后可先装临时补丁，后台会继续查询新词库。后台任务从上游获取词库，由本地补丁器生成补丁。界面翻译的覆盖范围取决于客户端和词库版本。

替换前会再次核对客户端版本和原文件，并将原资源包备份到 `%LOCALAPPDATA%\AntigravityZhSync\backups`。检查失败时，当前文件会保留，原因会写入日志。客户端大幅改版后，可能需要更新补丁器。

## 卸载

在本项目目录下运行以下命令。后台任务会被移除，已安装的汉化继续生效。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Uninstall.ps1
```

需要同时恢复英文界面时，先从系统托盘彻底退出 Antigravity，再给卸载命令追加 `-RestoreEnglish`。还原使用与当前客户端版本及已装补丁匹配的备份。日志和备份会保留。

## 来源与许可

本项目由社区维护，同步脚本采用 [MIT 许可](LICENSE)。

汉化词库与补丁器来自 [yiheng8023/antigravity-chinese v3.3.65](https://github.com/yiheng8023/antigravity-chinese/tree/v3.3.65)，固定提交为 `98301f853d3af3d49ae0da17fa8d89425473d037`。上游版权声明见 [patcher/LICENSE](patcher/LICENSE)。Antigravity 程序请从 Google 官方渠道获取。
