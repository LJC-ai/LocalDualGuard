# DualGuard-Sec 打包部署教程

> 小白友好。本教程覆盖两条封装链路：**Windows 源码 → exe 安装包**、**Linux → deb 包 + systemd 服务**。全部命令可复制即用。
>
> 适用版本：DualGuard-Sec（安全版，edition = `sec`）。学生版请参考 `DualGuard-Student/docs/packaging.md`。

---

## 目录

- [一、环境准备（通用）](#一环境准备通用)
- [二、Windows：源码打包 exe 安装包](#二windows源码打包-exe-安装包)
- [三、Windows：安装与卸载](#三windows安装与卸载)
- [四、Windows：机构平板批量预装方案](#四windows机构平板批量预装方案)
- [五、Linux：deb 包编译制作](#五linuxdeb-包编译制作)
- [六、Linux：服务器安装与卸载](#六linux服务器安装与卸载)
- [七、Linux：后台服务启停与开机自启](#七linux后台服务启停与开机自启)
- [八、部署后自检清单](#八部署后自检清单)

---

## 一、环境准备（通用）

DualGuard-Sec 基于 Python 3.10+，公共库位于仓库根目录 `common/`。

```bash
# 1. 克隆 / 进入仓库
cd e:\LocalDualGuard

# 2. 建议使用虚拟环境
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux
source .venv/bin/activate

# 3. 安装依赖
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
# 打包工具
python -m pip install pyinstaller
```

确认源码可跑通后再打包：

```bash
python -m DualGuard_Sec.main --check
```

---

## 二、Windows：源码打包 exe 安装包

打包分两步：① PyInstaller 把 Python 源码打成单文件 `DualGuard-Sec.exe`；② Inno Setup 把 exe + 配置 + 资源封装成带安装向导的 `Setup.exe`。

### 2.1 安装 Inno Setup

下载并安装 [Inno Setup 6](https://jrsoftware.org/isdl.php)（免费）。安装时勾选中文语言包。

### 2.2 用 PyInstaller 打包主程序

在仓库根目录执行：

```powershell
pyinstaller ^
  --noconfirm ^
  --onefile ^
  --windowed ^
  --name "DualGuard-Sec" ^
  --icon "DualGuard-Sec\assets\icon.ico" ^
  --add-data "DualGuard-Sec\config.yaml;DualGuard-Sec" ^
  --add-data "common;common" ^
  --hidden-import "DualGuard_Sec.rules" ^
  "DualGuard-Sec\dualguard_sec\main.py"
```

- `--onefile`：单文件 exe，便于分发。
- `--windowed`：无控制台黑窗（托盘程序）。
- `--add-data`：把 config.yaml 与公共库 common 一并打入。Windows 用 `;` 分隔，Linux 用 `:`。

打包产物：`dist\DualGuard-Sec.exe`。

> 验证：双击 `dist\DualGuard-Sec.exe`，托盘应出现图标，`%PROGRAMDATA%\DualGuard\sec\` 目录会被自动创建。

### 2.3 准备打包目录

为 Inno Setup 整理一个干净的 staging 目录：

```
staging\
├── DualGuard-Sec.exe          # 上一步产物
├── config.yaml                # 复制自 DualGuard-Sec\config.yaml
├── audit_policy.json          # 赛事方下发的审核策略（含预期哈希）
└── audit_policy.sha256        # 对应的 SHA256 清单
```

生成审核策略哈希（Python）：

```powershell
python -c "import hashlib,sys; print(hashlib.sha256(open('audit_policy.json','rb').read()).hexdigest())" > audit_policy.sha256
```

### 2.4 编写 Inno Setup 脚本

在 `DualGuard-Sec\installer\dualguard-sec.iss` 创建脚本：

```ini
; DualGuard-Sec Inno Setup 脚本
#define MyAppName "DualGuard-Sec"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "DualGuard Contributors"
#define MyAppExeName "DualGuard-Sec.exe"

[Setup]
AppId={{8F3C2A1B-SEC1-4D2A-9C00-DUALGUARDSEC}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\output
OutputBaseFilename=DualGuard-Sec-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startup"; Description: "开机自启"; GroupDescription: "附加任务:"

[Files]
Source: "..\staging\DualGuard-Sec.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\staging\config.yaml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\staging\audit_policy.json"; DestDir: "{commonappdata}\DualGuard\sec"; Flags: onlyifdoesntexist
Source: "..\staging\audit_policy.sha256"; DestDir: "{commonappdata}\DualGuard\sec"; Flags: onlyifdoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{commonstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{commonappdata}\DualGuard\sec"
```

要点：
- `PrivilegesRequired=admin`：写入 `%PROGRAMDATA%` 需管理员权限。
- `audit_policy.*` 安装到 `{commonappdata}\DualGuard\sec`（即 `C:\ProgramData\DualGuard\sec`，与 `paths.py` 默认一致），`onlyifdoesntexist` 避免覆盖已有策略。
- 卸载时 `[UninstallDelete]` 清理数据目录（机构可选择保留以留存违规记录）。

### 2.5 编译生成安装包

用 Inno Setup Compiler（ISCC）命令行编译：

```powershell
cd DualGuard-Sec\installer
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" dualguard-sec.iss
```

产物：`DualGuard-Sec\installer\output\DualGuard-Sec-Setup-1.0.0.exe`。这就是分发给选手终端的安装包。

---

## 三、Windows：安装与卸载

### 3.1 安装

1. 右键 `DualGuard-Sec-Setup-1.0.0.exe` → **以管理员身份运行**。
2. 选择语言（简体中文 / English）→ 下一步。
3. 接受许可（含合规免责声明）→ 选择安装目录（默认 `C:\Program Files\DualGuard-Sec`）。
4. 勾选"开机自启"（推荐赛事终端勾选）→ 安装 → 完成。
5. 安装后程序自动启动，托盘出现 DualGuard-Sec 图标。

### 3.2 静默安装（脚本/批量场景）

```powershell
DualGuard-Sec-Setup-1.0.0.exe /SP- /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER=0
```

- `/VERYSILENT`：完全静默；`/SILENT` 仅隐藏向导但显示进度。
- `/CURRENTUSER=0`：以管理员安装到全部用户。

### 3.3 卸载

- **图形化**：控制面板 → 应用 → DualGuard-Sec → 卸载。
- **静默卸载**：

```powershell
"C:\Program Files\DualGuard-Sec\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
```

卸载默认会删除 `%PROGRAMDATA%\DualGuard\sec`（含违规记录）。如需保留记录以备复盘，编辑 `.iss` 中 `[UninstallDelete]` 行为或卸载前手动备份该目录。

---

## 四、Windows：机构平板批量预装方案

赛事主办方对一批选手平板 / 笔记本预装，推荐以下方案之一。

### 方案 A：U 盘 + 批处理（最小依赖，适合离线机房）

1. 准备 U 盘，根目录放入：

```
U盘\
├── DualGuard-Sec-Setup-1.0.0.exe
├── audit_policy.json          # 本场赛事统一策略
├── audit_policy.sha256
└── install.bat
```

2. `install.bat` 内容：

```bat
@echo off
chcp 65001 >nul
echo === DualGuard-Sec 批量预装 ===
%~dp0DualGuard-Sec-Setup-1.0.0.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER=0
if errorlevel 1 ( echo 安装失败 & pause & exit /b 1 )
:: 下发本场策略（覆盖默认空策略）
copy /Y "%~dp0audit_policy.json" "%PROGRAMDATA%\DualGuard\sec\audit_policy.json"
copy /Y "%~dp0audit_policy.sha256" "%PROGRAMDATA%\DualGuard\sec\audit_policy.sha256"
echo === 预装完成，请拔出 U 盘并重启 ===
pause
```

3. 每台平板插入 U 盘 → 右键 `install.bat` → **以管理员身份运行** → 完成。

> 注意：下发策略后必须同步 `audit_policy.sha256`，否则启动时 `audit_hash` 会判为篡改并触发恢复。

### 方案 B：MDM / Intune 集中分发（适合已纳管设备）

1. 在 Intune 控制台添加"Windows 应用 (Win32)"，上传 `.intunewin` 包（由安装包经 Microsoft Win32 Content Prep Tool 打包）。
2. 安装命令：`DualGuard-Sec-Setup-1.0.0.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART`
3. 卸载命令：`"%ProgramFiles%\DualGuard-Sec\unins000.exe" /VERYSILENT`
4. 安装行为：系统上下文（需管理员）。
5. 策略下发：用 Intune PowerShell 脚本统一推送 `audit_policy.json` + `.sha256` 到 `%PROGRAMDATA%\DualGuard\sec\`。

### 方案 C：微软部署工具 MDT / WDS（适合裸机批量装机）

将安装包加入 MDT 任务序列的"安装应用程序"步骤，配合镜像一起下发；策略文件作为任务序列末尾的"复制文件"步骤写入。

---

## 五、Linux：deb 包编译制作

目标：产出 `dualguard-sec_1.0.0_amd64.deb`，安装后注册为 systemd 服务 `dualguard-sec.service`。

### 5.1 构建 deb 目录结构

在仓库根目录创建打包工作区：

```
build-deb/
└── dualguard-sec/
    ├── DEBIAN/
    │   ├── control
    │   ├── postinst
    │   ├── prerm
    │   └── postrm
    ├── usr/bin/dualguard-sec              # 启动脚本
    ├── usr/lib/dualguard-sec/
    │   ├── DualGuard-Sec                  # PyInstaller 产物
    │   ├── config.yaml
    │   └── common/                        # 若非 onefile 则需打入
    ├── etc/dualguard-sec/
    │   ├── audit_policy.json
    │   └── audit_policy.sha256
    └── etc/systemd/system/
        └── dualguard-sec.service
```

> 数据目录 `/var/lib/dualguard/sec/` 不要打进包里，由程序启动时 `ensure_dirs()` 自动创建（见 `common/paths.py`）。

### 5.2 用 PyInstaller 产出 Linux 可执行文件

在 Linux 构建机（与目标机同架构、同 glibc 版本，推荐 Ubuntu 20.04+）执行：

```bash
pyinstaller \
  --onefile \
  --name "DualGuard-Sec" \
  --add-data "DualGuard-Sec/config.yaml:DualGuard-Sec" \
  --add-data "common:common" \
  --hidden-import "DualGuard_Sec.rules" \
  "DualGuard-Sec/dualguard_sec/main.py"
```

> Linux 下 `--add-data` 分隔符是 `:`，与 Windows 的 `;` 不同。

把 `dist/DualGuard-Sec` 放入 `build-deb/dualguard-sec/usr/lib/dualguard-sec/`。

### 5.3 编写 control 文件

`build-deb/dualguard-sec/DEBIAN/control`：

```
Package: dualguard-sec
Version: 1.0.0
Section: utils
Priority: optional
Architecture: amd64
Depends: libc6 (>= 2.31)
Maintainer: DualGuard Contributors <noreply@dualguard.local>
Description: DualGuard-Sec (security edition) local compliance guard.
 DualGuard-Sec is a local-side compliance guard for authorized
 cybersecurity training / CTF / pentest drill scenarios. It counts
 violations, warns, freezes for 72h, and verifies audit policy hash.
 .
 ⚠ Authorized closed-range use only. No unauthorized pentesting in
 public networks; no malicious attack code generation.
```

### 5.4 编写 systemd 服务文件

`build-deb/dualguard-sec/etc/systemd/system/dualguard-sec.service`：

```ini
[Unit]
Description=DualGuard-Sec local compliance guard (security edition)
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/dualguard-sec
WorkingDirectory=/usr/lib/dualguard-sec
Restart=on-failure
RestartSec=5
# 以专用用户运行，降低权限
User=_dualguard
Group=_dualguard
# 数据目录
Environment=DUALGUARD_DATA_ROOT=/var/lib/dualguard
# 防止绕过：禁止修改自身
ProtectSystem=strict
ReadWritePaths=/var/lib/dualguard /var/log/dualguard-sec
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

### 5.5 编写维护脚本

`postinst`（安装后注册服务）：

```bash
#!/bin/bash
set -e
# 创建专用用户
if ! id _dualguard >/dev/null 2>&1; then
    useradd --system --no-create-home --shell /usr/sbin/nologin _dualguard
fi
# 数据目录
install -d -o _dualguard -g _dualguard /var/lib/dualguard/sec
install -d -o _dualguard -g _dualguard /var/log/dualguard-sec
# 注册并启动
systemctl daemon-reload
systemctl enable dualguard-sec.service
systemctl start dualguard-sec.service
echo "DualGuard-Sec 已安装并启动。策略文件位于 /etc/dualguard-sec/"
exit 0
```

`prerm`（卸载前停服务）：

```bash
#!/bin/bash
set -e
if [ "$1" = "remove" ] || [ "$1" = "deconfigure" ]; then
    systemctl stop dualguard-sec.service || true
    systemctl disable dualguard-sec.service || true
fi
exit 0
```

`postrm`（卸载后清理）：

```bash
#!/bin/bash
set -e
if [ "$1" = "purge" ]; then
    systemctl daemon-reload || true
    rm -rf /var/lib/dualguard/sec /var/log/dualguard-sec
    echo "已清除 DualGuard-Sec 数据目录（purge）。"
fi
exit 0
```

### 5.6 启动脚本 wrapper

`build-deb/dualguard-sec/usr/bin/dualguard-sec`：

```bash
#!/bin/bash
exec /usr/lib/dualguard-sec/DualGuard-Sec "$@"
```

### 5.7 赋权并打包

```bash
cd build-deb
# 维护脚本必须有执行权限
chmod 0755 dualguard-sec/DEBIAN/postinst \
          dualguard-sec/DEBIAN/prerm \
          dualguard-sec/DEBIAN/postrm \
          dualguard-sec/usr/bin/dualguard-sec
chmod 0644 dualguard-sec/etc/systemd/system/dualguard-sec.service

# 修正属主（deb 内文件必须 root:root）
sudo chown -R root:root dualguard-sec

# 生成 deb（注意目录名与包名）
dpkg-deb --build --root-owner-group dualguard-sec dualguard-sec_1.0.0_amd64.deb
```

产物：`build-deb/dualguard-sec_1.0.0_amd64.deb`。

校验：

```bash
dpkg-deb --info dualguard-sec_1.0.0_amd64.deb
dpkg-deb --contents dualguard-sec_1.0.0_amd64.deb
```

---

## 六、Linux：服务器安装与卸载

### 6.1 安装

```bash
sudo dpkg -i dualguard-sec_1.0.0_amd64.deb
```

若缺依赖：

```bash
sudo apt-get install -f -y
```

`postinst` 会自动：创建 `_dualguard` 用户 → 建数据目录 → `systemctl enable` + `start`。

### 6.2 验证

```bash
systemctl status dualguard-sec.service
# 查看违规记录目录
ls -la /var/lib/dualguard/sec/
# 查看日志
journalctl -u dualguard-sec.service -f
```

### 6.3 卸载

```bash
# 保留违规记录（推荐，便于复盘）
sudo dpkg -r dualguard-sec

# 彻底清除（含数据目录）
sudo dpkg --purge dualguard-sec
```

`--purge` 会触发 `postrm` 删除 `/var/lib/dualguard/sec` 与日志目录。

---

## 七、Linux：后台服务启停与开机自启

DualGuard-Sec 注册为 systemd 服务 `dualguard-sec.service`，常用命令：

```bash
sudo systemctl start   dualguard-sec.service   # 启动
sudo systemctl stop    dualguard-sec.service   # 停止
sudo systemctl restart dualguard-sec.service   # 重启
sudo systemctl status  dualguard-sec.service   # 查看状态
```

### 开机自启

安装时 `postinst` 已执行 `systemctl enable`。手动管理：

```bash
sudo systemctl enable  dualguard-sec.service   # 开启开机自启
sudo systemctl disable dualguard-sec.service   # 关闭开机自启
# 查看是否已设为自启
systemctl is-enabled dualguard-sec.service
```

### 日志查看

- systemd journal（推荐）：`journalctl -u dualguard-sec -e --since "1 hour ago"`
- 应用日志文件：`/var/log/dualguard-sec/`（由 `paths.py` 的 `log_dir` 输出）。

### 更新审核策略（不重装）

```bash
sudo cp audit_policy.json   /etc/dualguard-sec/audit_policy.json
sudo cp audit_policy.sha256 /etc/dualguard-sec/audit_policy.sha256
sudo chown _dualguard:_dualguard /etc/dualguard-sec/audit_policy.*
sudo systemctl restart dualguard-sec.service
```

> 策略与哈希必须成对更新，否则 `audit_hash` 启动校验失败会触发"篡改程序警告"并从备份恢复。

---

## 八、部署后自检清单

| 检查项 | Windows | Linux |
|--------|---------|-------|
| 进程在运行 | 任务管理器可见 `DualGuard-Sec.exe` | `systemctl status dualguard-sec` 为 active |
| 数据目录已建 | `%PROGRAMDATA%\DualGuard\sec\` 存在 | `/var/lib/dualguard/sec/` 存在 |
| 策略哈希一致 | 启动无篡改弹窗 | 启动无篡改弹窗 |
| 冻结生效 | 达阈值后操作被拦截 | 达阈值后操作被拦截 |
| 开机自启 | 注册表/启动项存在 | `systemctl is-enabled` 返回 enabled |
| 卸载干净 | 控制面板无残留 | `dpkg -l \| grep dualguard-sec` 无 |

---

> 如遇问题，先看日志再提 Issue。Windows 看 `%PROGRAMDATA%\DualGuard\sec\logs\`，Linux 看 `journalctl -u dualguard-sec` 与 `/var/log/dualguard-sec/`。
