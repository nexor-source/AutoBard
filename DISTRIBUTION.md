# AutoBard GUI、打包和自动更新

## 本地启动 GUI

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m autobard --config config\settings.json gui
```

点击“启动服务”后，程序才会开始监听热键。双击右键开始一次检测，F9 中止当前检测，F10 停止服务。

“重新校准画面”会先说明两次框选的范围和确认/取消按键。用户确认后 GUI 自动最小化，并按照“校准准备时间”倒计时再截图，方便切换回游戏；倒计时支持 0–60 秒，默认 5 秒。校准结束或取消后 GUI 会自动恢复。

GUI 启动后会自动检测 usbip-win2 的 `usbip2_ude` 和 `usbip2_filter` 驱动状态。“基本设置”页可以手动重新检测或打开安装说明。选择 `system_input` + `viiper` 时，如果缺少主驱动，GUI 会阻止服务启动并给出明确提示；检测功能本身不会安装或修改驱动。

## 生成 Windows 分发包

首次构建或依赖有变化时执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

如果依赖已经安装并且只想快速重建：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1 -SkipInstall
```

构建脚本会先运行测试，然后生成：

- `dist\AutoBard\AutoBard.exe`：本机测试入口。
- `dist\AutoBard-win64.zip`：需要分发给用户的完整程序包。
- `dist\AutoBard-win64.zip.sha256`：自动更新使用的 SHA-256 校验文件。

程序采用 PyInstaller onedir 模式。请分发整个 ZIP，不要只发送 `AutoBard.exe`。用户解压后直接运行 `AutoBard.exe`；`runtime\viiper.exe`、Python 运行库和配置文件必须与它保持原有相对目录。

## 发布自动更新

更新源默认为 GitHub 仓库 `nexor-source/AutoBard`。发布新版本时：

1. 同时修改 `src\autobard\__init__.py` 和 `pyproject.toml` 中的版本号。
2. 提交并推送代码。
3. 创建与版本一致的标签，例如 `v2.1.0`，再推送该标签。
4. `.github\workflows\release.yml` 会在 Windows 上运行测试、打包，并创建 GitHub Release。

每个 Release 必须同时包含名字完全一致的两个文件：

- `AutoBard-win64.zip`
- `AutoBard-win64.zip.sha256`

GUI 启动时会查询最新的非草稿 Release。发现更高版本后，只有在用户确认时才下载；下载包通过 SHA-256 校验后才会安装。安装过程会保留用户已有的 `config` 和 `debug_output`，随后重新启动程序。源码方式运行 GUI 时只会打开 Release 页面，不执行覆盖安装。

## 分发前注意事项

- 目标电脑仍需正确安装和配置 USB/IP 驱动环境；GUI 已内置 VIIPER 可执行文件并会自动检测驱动，但不会替用户安装驱动。
- 未签名的 EXE 可能触发 Windows SmartScreen。正式公开分发时建议为 `AutoBard.exe` 和更新包签名。
- 请确认 `viiper.exe` 及其依赖允许随本项目再分发。
- 游戏自动化可能违反游戏规则；GUI 在启用 `system_input` 前要求用户确认风险。
