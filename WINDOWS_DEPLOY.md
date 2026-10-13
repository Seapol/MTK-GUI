# MTK GUI Windows 部署打包指南（exe 命名为 mtk.exe）

在 Windows 电脑上从零拉代码、打包出 `mtk.exe` 的完整步骤。
在 CMD 或 PowerShell 中执行。

---

## 0. 部署架构：三台机器分工

| 机器 | 角色 | 需要什么 |
|---|---|---|
| Mac | 开发机 | SSH key（已就绪），`git push` / `git pull` 代码 |
| Windows 机 | 打包机 | 本指南：HTTPS clone + venv + pyinstaller，产出 `dist\mtk\` |
| 工厂电脑 | 运行 | 什么都不用装（不用 git、不用 Python），只拷 `dist\mtk\` 文件夹 |

---

## 1. 安装前置软件（一次性）

| 软件 | 说明 |
|---|---|
| Git for Windows | https://git-scm.com/download/win ，一路默认安装 |
| Python 3.12 | https://www.python.org/downloads/ ，安装时**务必勾选 Add Python to PATH** |

安装完成后验证（新开一个终端）：

```bat
git --version
python --version
```

## 2. 拉取代码

```bat
:: 选一个存放代码的目录，例如 D:\work
D:
cd \work

:: 克隆仓库（HTTPS 方式，无需配 SSH key）
git clone https://github.com/Seapol/MTK-GUI.git
cd MTK-GUI

:: 切换到要部署的分支（部署分支：develop）
git checkout develop

:: 拉取最新代码
git pull origin develop
```

> 如已配置 SSH key，可改用：`git clone git@github.com:Seapol/MTK-GUI.git`

## 3. 创建虚拟环境并安装依赖

```bat
python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt
```

> 每次新开终端执行命令前，先执行 `.venv\Scripts\activate` 激活环境。

## 4. 修改 spec，把 exe 改名为 mtk.exe

exe 的名字由 spec 文件里的 `name=` 决定，需要改两处。

用记事本打开仓库根目录下的 `MTK_GUI_windows.spec`：

```bat
notepad MTK_GUI_windows.spec
```

找到 `EXE(...)` 里的：

```python
    name='MTK_GUI',
```

改成：

```python
    name='mtk',
```

再找到 `COLLECT(...)` 里的：

```python
    name='MTK_GUI',
```

也改成：

```python
    name='mtk',
```

改完保存关闭。

> 说明：
> - `EXE(name=...)` 决定最终 exe 文件名 → `mtk.exe`
> - `COLLECT(name=...)` 决定输出文件夹名 → `dist\mtk\`
> - 两处都改，最终产物为 `dist\mtk\mtk.exe`

## 5. PyInstaller 打包

在仓库根目录执行：

```bat
pyinstaller --noconfirm MTK_GUI_windows.spec
```

打包完成后产物位置：

```
dist\mtk\mtk.exe          <- 主程序
dist\mtk\_internal\       <- 依赖文件（必须和 mtk.exe 在一起）
```

## 6. 验证

双击运行 `dist\mtk\mtk.exe`（GUI 程序，无控制台窗口）。

如需拷贝到其他机器，**必须整个 `dist\mtk` 文件夹一起拷贝**，不能只拷 mtk.exe。

## 7. 拷贝到工厂电脑（运行部署）

工厂电脑**不需要 git、不需要 Python**，只把打包机上的整个 `dist\mtk\` 文件夹用 U 盘或网络共享拷过去：

```
mtk\            <- 整个文件夹一起拷，缺一不可
├── mtk.exe     <- 双击运行
└── _internal\  <- 依赖全在这，不能和 mtk.exe 分开
```

### 安装清单

**基础功能 —— 无需安装任何软件。** Python、PySide6、串口（pyserial）、SSH（paramiko）等依赖已全部打包在 `_internal\` 里；`ping`、`netsh`、`powershell` 为 Windows 自带。

**按需安装：**

| 组件 | 什么时候需要 | 怎么装 |
|---|---|---|
| [VC++ 运行库](https://aka.ms/vs/17/release/vc_redist.x64.exe) | 仅当双击 mtk.exe 报缺 DLL（少数精简系统） | 下载 x64 版安装一次 |
| iperf3 | 测试计划启用了 Wi-Fi 吞吐量步骤（host 侧 `iperf3 -c` 测速或 `iperf3 -s` 当 server） | 下载 Windows 版 iperf3.exe，放进 `mtk\` 文件夹（和 mtk.exe 同目录）或 `C:\Windows\`；计划未启用吞吐步骤则不用装 |
| USB 串口驱动 | 用 USB 转串口线连接 DUT | FTDI / CP210x 在 Win10/11 一般自动装；CH340 系列通常需手动装一次 |
| WLAN 网卡 | host 侧 Wi-Fi 扫描/连接/吞吐测试 | 电脑本身需有可用的 WLAN 网卡 |

**两个前提 + 一条说明：**

- 测试机建议装**英文版 Windows**：Wi-Fi/吞吐步骤按英文输出解析 `netsh`/`ping`，中文系统可能解析失败。
- 用户自建的 YAML 计划文件放 `mtk\yaml_plan\`（exe 旁边），随用随放，不用重新打包。
- 随包内置的 FRDM-IMX93 FCT demo 计划在 `mtk\_internal\yaml_plan\examples\imx93frdm\`，当前最新为 `FRDM-IMX93_FCT_Demo_v1.0.2.yaml`（v1.0.0 / v1.0.1 仍保留在包内）。

**版本号显示 v4.1.1.0000？**

exe 由源码直接打包时未带 CI 生成的 `resources\version.json`，状态栏回退显示静态版本 `v4.1.1.0000`，功能无影响；CI 打包管线构建时会写入真实版本号。

---

## 常见问题

**打包报错找不到 `config/permissions.json` 等文件**
spec 引用了以下文件，必须随代码一起拉下来（已在 git 仓库里）：
- `config/permissions.json`
- `config/FRDM-IMX93_Nets.xlsx`
- `config/12345_FRDM-IMX93_Nets_revA.xlsx`
- `yaml_plan/examples`
- `resources`

确认是在仓库根目录执行的打包命令（目录下能看到 `MTK_GUI_windows.spec`）。

**`pyinstaller` 不是内部或外部命令**
虚拟环境没激活，先执行 `.venv\Scripts\activate`。

**用户自己的 YAML 计划文件**
`yaml_plan/` 中用户自建的测试计划不在打包产物里，部署后需手动放到 exe 同级的 `yaml_plan/` 目录。内置 demo 计划（`yaml_plan/examples`）已随包打进 `_internal\yaml_plan\examples\`，无需手动放置。

---

## 附录：Mac 开发机 SSH key（已就绪，备用）

Mac 已配置好 SSH key（`~/.ssh/id_ed25519`，公钥已注册 GitHub），日常 `git push` / `git pull` 直接可用，无需任何操作。

换新 Mac 时的备用步骤：

```bash
ssh-keygen -t ed25519 -C "seapol@mac"        # 一路回车
pbcopy < ~/.ssh/id_ed25519.pub               # 公钥进剪贴板
# GitHub → Settings → SSH and GPG keys → New SSH key → 粘贴保存
ssh -T git@github.com                        # 测试，出现 Hi Seapol! 即成功
```

> Windows 打包机不需要 SSH key，用本指南第 2 步的 HTTPS 方式即可。
