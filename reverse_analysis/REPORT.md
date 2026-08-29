# `7.0_64_create_thread_safe.exe` 静态逆向报告

结论：该文件不是 AutoBard、VIIPER、Python 或 PyInstaller 产物，也不是一个单纯的“创建线程测试程序”。它是一个带 18 层自修改解码、加密配置、网络下载、加密缓存、解压和反射式 PE 内存加载能力的分阶段加载器。随后在本机找到了它的缓存，并成功静态解出第二阶段。第二阶段在功能上是一套完整的远程设备监视/控制代理，包含键盘记录、剪贴板与截图采集、系统侦察、远程命令、下载执行、内存载荷执行和提权辅助等能力。无论其作者如何命名，它都应按高风险 RAT/后门处理。

本次只进行了静态分析：没有启动目标 EXE，没有连接其中的服务器，也没有从网络下载任何内容。第二阶段来自本机已经存在的缓存文件，整个解密、解压和反汇编过程均未执行其中代码。

## 样本识别

| 项目 | 值 |
| --- | --- |
| 原始文件 | `D:\7.0_64_create_thread_safe.exe` |
| 文件大小 | 123,307 bytes |
| SHA-256 | `8FDF00F61A4953846BEDC651F05BBD09B0247D9781C89DCE98FDDE72F18D9656` |
| 架构 | PE32+ / AMD64 (`0x8664`) |
| 数字签名 | 无 |
| 链接时间戳 | 2026-07-01 19:35:46 +08:00 |
| 内嵌 PDB 路径 | `H:\window\tools\BinLoadTester\TestExeTemplates\out\x64\create_thread_safe_64.pdb` |
| 外层载荷标记 | `BLT_PAYLOAD_001\0` |
| 内嵌载荷大小 | 18,307 bytes (`0x4783`) |
| 内嵌载荷 SHA-256 | `C024DF023E491B4037E308878EC9F12062AE13A0E148F09EBC8066B1533D0507` |
| 18 层解码后 SHA-256 | `2065E6DEB694BC2D0D6D8F45650BF2D2BDF395DF0CAB28A9B94E26BCD7C04DF8` |

PDB 路径说明了外层来自 `BinLoadTester/TestExeTemplates` 一类模板；它只能说明构建模板来源，不能证明内部载荷安全，也不能据此确定作者身份。

## 实际执行链

1. 外层程序取得自己的文件路径并重新打开自身。
2. 从文件末尾读取 40-byte trailer，验证 `BLT_PAYLOAD_001\0`、版本 `1`、架构 `0x40`、载荷偏移和长度。
3. 从文件偏移 104,960 读出 18,307-byte 内嵌载荷。
4. 使用 `VirtualAlloc` 分配内存，复制载荷，将内存改为 `PAGE_EXECUTE_READWRITE`，刷新指令缓存。
5. 通过 `CreateThread` 将控制权交给载荷并等待线程结束。
6. 内嵌载荷先执行 18 层交替的尾部代码变异和倒序滚动 XOR 解码，真正入口最终位于载荷偏移 `0x1D3`。
7. 真正入口扫描 `%@)!#!$` 标记，以 `0xC0DEFACE` 为种子解密其后的 `0x1D0` bytes，并验证 `DMV2`、长度 `0x1D0`、版本 `2`。
8. 代码直接遍历 PEB，使用自定义大小写不敏感哈希解析 DLL 和 API 名称，避免把关键网络 API 以明文写入导入表。

## 解出的 DMV2 配置

| 偏移 | 内容 | 解释 |
| --- | --- | --- |
| `0x00` | `DMV2` | 配置魔数 |
| `0x04` | `0x1D0` | 配置总长度 464 bytes |
| `0x08` | `2` | 版本 |
| `0x0C` | `154.82.93.152` | 服务器地址 |
| `0x10B` | `853EAFC200002A0D` | 缓存目录名，同时用作重复 XOR key |
| `0x147` | `%@)!#!$` | 内部标记 |
| `0x154` | `443` | TCP 端口 |
| `0x15C` | `17E936CD21C167C3712E430C1308E267` | 16-byte 握手字段；准确语义尚未确定 |
| `0x16C` | `D57A419AE153533CB8567F3DA79F7F33DC0E9F555EA771BCE949F9EF938CCA99` | 32-byte 固定身份/公钥类字段；代码要求它非全零 |

解密配置 SHA-256：`15C2DA7AAA20A0D53AAF22AFF3F3AC7F77F16777FCD1EE5376B1AB8D1B5CC39F`。

代码通过 `SHGetFolderPathA(CSIDL_COMMON_APPDATA)` 构造缓存位置，因此正常 Windows 安装上的目标路径为：

```text
C:\ProgramData\853EAFC200002A0D\1
```

## 本地缓存和第二阶段加载

程序会优先尝试上述缓存文件：

- 文件必须大于 `0x2800` bytes，且不超过 `0x400000` bytes（4 MiB）。
- 使用字符串 `853EAFC200002A0D` 做循环重复 XOR 解密。
- 将结果用一个与 aPLib depacker 高度吻合的位流/LZ 解码器解压到 1 MiB 内存区。
- 验证解压结果为 `MZ`、`PE32+`、AMD64 文件。
- 自行复制 PE headers/sections、处理 x86/x64 relocation、解析 imports、运行 TLS callbacks 和入口点。
- 再按哈希 `0x2EC07661` 查找该内存 PE 的导出函数，并把解密后的 DMV2 配置传给它。现已确认这个哈希精确对应 `DM_Start`。

这不是普通的 `LoadLibrary`：它具备完整的 64-bit PE 手工映射器，第二阶段可以不以正常模块形式出现在磁盘或标准加载链中。

## 已找到并解开的第二阶段

只读检查确认下列缓存真实存在：

| 项目 | 值 |
| --- | --- |
| 路径 | `C:\ProgramData\853EAFC200002A0D\1` |
| 大小 | 261,503 bytes |
| 创建/修改时间 | 2026-08-21 09:00:03 +08:00 |
| SHA-256 | `CD91509529CC740A2FD98C9BB034067E99248BD148945DFF91A63628ACF7AE65` |
| MD5 | `0669F121EBC3A904861A1E1B5BEB11C5` |
| 文件所有者 | `BUILTIN\Administrators` |

该缓存的创建时间只比外层 EXE 的时间 2026-08-21 08:59:57 晚约 6 秒，与该 EXE 曾在本机实际启动并写出/下载缓存高度一致；时间戳相关性本身不是绝对证明，但结合路径、key 和格式完全匹配，证据很强。

用配置中的 ASCII key 做循环 XOR，再用代码中的有界 aPLib-style depacker 解压，得到：

| 项目 | 值 |
| --- | --- |
| 类型 | 无签名 PE32+ / AMD64 DLL |
| 解压大小 | 518,656 bytes |
| SHA-256 | `C2D36D068753504AF6DF0C218F54AF2E6CFF95F935DB69A5D55AFB636B0060F3` |
| ImageBase | `0x180000000` |
| Entry RVA | `0x56074` |
| SizeOfImage | 712,704 bytes |
| 链接时间戳 | 2026-07-17 20:54:33 +08:00 |
| 导出 | `DM_Start`（RVA `0x48780`）、`DM_Stop`（RVA `0x48788`） |
| PDB / 版本资源 | 无 |

`DM_Start` 的哈希正是外层手工映射器查找的 `0x2EC07661`，所以调用关系已经闭环：外层下载/读取缓存 → XOR → 解压 → 手工映射 DLL → 调用 `DM_Start(DMV2_config)`。

### 第二阶段能力

以下能力由导入表、命令分发函数、字符串交叉引用和对应调用路径共同确认：

- 设备与环境侦察：Windows 版本、MachineGuid、用户名/计算机名、内存、磁盘、GPU、显示器、安装软件、进程、会话、网络适配器、TCP 表、杀毒软件状态和 RDP/UAC 配置；
- 监视采集：`KEYLOG.LOCAL` 键盘记录、活动窗口标题、剪贴板文本/位图、定时截图；
- 远程命令：定位并启动 `cmd.exe`，用临时批处理脚本执行命令，回传 stdout 和 exit code，并支持取消当前命令；
- 进程与会话操作：创建进程、跨用户会话启动、挂起/恢复线程、终止进程、作业对象限制；
- 权限相关操作：请求 `SeDebugPrivilege`，访问 `winlogon.exe`/`lsass.exe`/`TrustedInstaller` 相关 token 和服务，用 `CreateProcessAsUserW` 启动进程；
- 下载与执行：使用 WinINet 伪装 Chrome 120 User-Agent 下载最多 64 MiB 的文件，支持落地执行；
- 内存执行：存在对任意 payload 做 `VirtualAlloc`、复制并 `CreateThread` 执行的命令处理路径；
- 网络控制：查看连接、用 `SetTcpEntry` 等 API 关闭 TCP 连接，维护 `BACKUP_ADDR.LIST`；
- 系统修改：创建目录/替换文件、增加防火墙规则、重启、卸载、更新基础配置和特性配置；
- 功能模块名包括 `Screenshot`、`Clipboard`、`KeyInput`、`Filter`、`TcpPolicy`，内部产品/互斥体字符串包括 `MagnetBasic`、`Global\Magnet_`，版本字符串包括 `1.3.1` 和 `1.3.3`。

这些能力远超普通“设备信息查看器”。如果没有用户明确、知情的远程管理授权，它在功能上就是 RAT/监控后门。

## 网络行为

如果本地缓存缺失或加载失败，程序会：

- 初始化 Winsock 2.2；
- 直接建立到 `154.82.93.152:443` 的 TCP 连接；
- 设置约 5 秒的 socket 超时；
- 使用代码中自称 `Magnet Wire v2` 的自定义握手/加密协议，而不是调用系统 TLS/HTTP API；
- 代码里动态构造了 `Magnet Wire v2 transcript`、`c2s/s2c key`、`c2s/s2c nonce`、`server proof`、`client proof` 等域分离标签；
- 接收 `0x1F` 元数据帧、多个 `0x20` 数据帧和 `0x21` 结束/校验帧；
- 限制总载荷不超过 4 MiB，并用标准多项式 `0xEDB88320` 的 CRC-32 验证数据；
- 下载成功后，将载荷用前述 ASCII key 做 XOR 后写入缓存文件，再在内存中恢复明文、解压并手工映射；
- 失败后等待约 5 秒重试；成功启动第二阶段后进入每 60 秒一次的无限休眠。

公开搜索没有找到 `Magnet Wire v2`、`KEYLOG.LOCAL`/`MagnetBasic` 组合或该精确样本哈希的可靠公开归属，因此报告不把它强行归为某个公开命名的恶意软件家族；这里的 RAT 判断来自实际代码能力，而不是家族标签。

## 反查出的关键 API

载荷的哈希算法以 `0xB1F48651` 起始，将 ASCII 小写转大写，然后逐字符执行：

```text
hash = ((hash XOR character) * 0x010001AB) mod 2^32
```

本机 DLL export 反查确认它使用：

- `kernel32.dll`：`VirtualAlloc`、`VirtualFree`、`CreateFileA`、`ReadFile`、`WriteFile`、`DeleteFileA`、`CreateDirectoryA`、`LoadLibraryA`、`GetProcAddress`、目录枚举和休眠等；
- `ntdll.dll`：`RtlZeroMemory`、`RtlMoveMemory`；
- `user32.dll`：窗口枚举、进程 ID 查询和 `ShowWindow`；
- `ws2_32.dll`：`WSAStartup`、`socket`、`getaddrinfo`、`connect`、`send/recv`、`sendto/recvfrom`、`setsockopt`、`ioctlsocket`、`shutdown` 等；
- `shell32.dll`：`SHGetFolderPathA`。

全部 5 个 DLL 哈希和 43 个 API 哈希都已在本机 Windows DLL 中成功反查，没有未解析项。

## 风险判断

高风险判断来自这些可直接验证的代码行为，而不是文件名或单一杀软标签：

- 多层自修改/混淆，意在隐藏真正代码和配置；
- 明文解密得到固定公网服务器和端口；
- 自定义认证加密网络协议和固定 32-byte 身份/公钥类字段；
- 下载并缓存第二阶段；现已确认第二阶段包含完整的远程监视/控制能力；
- 缓存文件使用弱 XOR 隐藏内容；
- 在 RWX 内存中解压和手工映射 PE；
- 运行第二阶段的 TLS callbacks、入口点和特定导出函数。

因此不要直接运行。由于本机缓存已经存在，应按“可能已经执行过第二阶段”处理：先断开该机器网络，保留样本和日志，在另一台可信设备上修改此后在该机输入或复制过的重要密码/token，并进行离线查杀或终端取证。只删除启动器和缓存不能证明已经运行的第二阶段没有留下其他影响；对高价值账户或敏感机器，重装系统是更稳妥的恢复基线。

## 产物与复现

- `reconstructed_loader.c`：安全、不可编译的 C-like 主流程反编译稿；刻意省略可直接复用的网络协议和反射加载实现。
- `reconstructed_stage2.c`：第二阶段的安全、不可编译 C-like 行为反编译稿。
- `output/stage2/stage2_summary.json`：缓存解密、解压哈希和第二阶段 PE 元数据。
- `output/stage2/capstone/interesting_disassembly.txt`：第二阶段关键函数的 Capstone 反汇编。
- `output/auto/payload_final_disassembly.txt`：18 层解码后的 Capstone 反汇编。
- `output/auto/config_dmv2.bin` 与 `config_dmv2.json`：静态解密后的配置及字段报告。
- `output/auto/recovered_hashes.json`：DLL/API 哈希反查结果。
- `output/auto/peel_report.json`：18 层解码过程、每层入口和 SHA-256。
- `recover_config.py`、`recover_hashes.py`、`peel_layers.py`、`extract_cached_stage.py`：复现脚本；它们只解析字节，不运行目标代码。

局限：已经恢复第二阶段主体、导出和主要能力，但原始符号、注释和工程源码并不存在，因此只能重建等价主流程，不能一比一还原作者的 C++ 文件。分析没有主动连接服务器，也没有执行载荷；服务器当前状态、运行时下发配置及这台机器是否存在额外落地物仍未验证。
