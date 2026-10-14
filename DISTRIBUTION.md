# AutoBard GUI、打包和自动更新

## 本地启动 GUI

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m autobard --config config\settings.json gui
```

点击“启动服务”后，程序才会开始监听热键。双击右键开始一次检测，F9 中止当前检测，F10 停止服务。

“重新校准画面”会先说明两次框选的范围和确认/取消按键。用户确认后 GUI 自动最小化，并按照“校准准备时间”倒计时再截图，方便切换回游戏；倒计时支持 0–60 秒，默认 5 秒。校准结束或取消后 GUI 会自动恢复。

程序会自动在第一、第二颗音符附近寻找指针，并在确认候选连续向右移动后才开始跟踪；搜索范围会自动扩展，通常不再需要猜测固定延迟。“额外启动延迟”支持 0–2000ms，默认 0ms，仅用于规避少数设备上的特殊界面动画。

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

发布包的初始配置由代码中的统一默认值生成，不使用开发者本机的校准坐标、输入确认状态或调试开关。首次安装默认使用 `dry_run`，用户需重新校准并在 GUI 中选择输出模式。目标 FPS 为 120，速度窗口为 90 点，会话上限为 12 秒，点击补偿为 45/50 ms。已有用户更新时仍保留各自的配置，再按下述规则迁移旧默认值。

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

从 2.1.1 开始，新程序会在首次加载旧配置时执行版本迁移，因此已经发布的旧更新器也能完成升级，无需先替换旧更新器。未标记迁移版本的配置中，`tracking.history_size` 为 18 时改为 90，`session.max_duration_s` 为 8 时改为 12；其他数值以及校准坐标、输入模式、点击延迟和其他设置保留。历史配置无法区分“保留旧默认值”和“手动设回同一个旧默认值”，上述两个相同数值均按旧默认值处理。

写入前会保存原文件为 `config/settings.json.pre-migration-v1.bak`，并在新配置中记录 `config_revision: 1`。已有备份不会覆盖；迁移后用户再次调整参数不会被反复迁移。若配置目录不能写入，迁移只对当前运行生效，并记录提示，原文件保持不变。

## 分发前注意事项

- 目标电脑仍需正确安装和配置 USB/IP 驱动环境；GUI 已内置 VIIPER 可执行文件并会自动检测驱动，但不会替用户安装驱动。
- 未签名的 EXE 可能触发 Windows SmartScreen。正式公开分发时建议为 `AutoBard.exe` 和更新包签名。
- 请确认 `viiper.exe` 及其依赖允许随本项目再分发。
- 游戏自动化可能违反游戏规则；GUI 在启用 `system_input` 前要求用户确认风险。
