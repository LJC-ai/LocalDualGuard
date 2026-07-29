# DualGuard-Student 打包部署教程

> 小白友好。本教程覆盖两条封装链路：**Windows 源码 → exe 安装包**、**Linux → deb 包 + systemd 服务**。全部命令可复制即用。
>
> 适用版本：DualGuard-Student（学生版，edition = `student`）。安全版请参考 `DualGuard-Sec/docs/packaging.md`。
>
> ⚠ 学生版可能部署于未满 18 周岁学生设备，部署前务必完成监护人知情同意，文案保持温和引导向。

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

DualGuard-Student 基于 Python 3.10+，公共库位于仓库根目录 `common/`。

```bash
# 1. 进入仓库
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
python -m pip install pyinstaller
```

确认源码可跑通：

```bash
python -m dualguard_student.main --check
```

---

## 二、Windows：源码打包 exe 安装包

两步：① PyInstaller 打 `DualGuard-Student.exe`；② Inno Setup 封装成带向导的 `Setup.exe`。

### 2.1 安装 Inno Setup

下载安装 [Inno Setup 6](https://jrsoftware.org/isdl.php)，安装时勾选中文语言包。

### 2.2 用 PyInstaller 打包主程序

在仓库根目录执行：

```powershell
pyinstaller ^
  --noconfirm ^
  --onefile ^
  --windowed ^
  --name "DualGuard-Student" ^
  --icon "DualGuard-Student\assets\icon.ico" ^
  --add-data "DualGuard-Student\config.yaml;DualGuard-Student" ^
  --add-data "common;common" ^
  --hidden-import "dualguard_student.rules" ^
  "DualGuard-Student\dualguard_student\main.py"
```

- Windows 下 `--add-data` 分隔符是 `;`。
- 产物：`dist\DualGuard-Student.exe`。

> 验证：双击运行，托盘出现图标，`%PROGRAMDATA%\DualGuard\student\` 目录被自动创建。

### 2.3 准备 staging 目录

```
staging\
├── DualGuard-Student.exe
├── config.yaml                # 复制自 DualGuard-Student\config.yaml
├── audit_policy.json          # 教师/教研下发的学习诚信策略
└── audit_policy.sha256
```

生成策略哈希：

```powershell
python -c "import hashlib; print(hashlib.sha256(open('audit_policy.json','rb').read()).hexdigest())" > audit_policy.sha256
```

### 2.4 编写 Inno Setup 脚本

在 `DualGuard-Student\installer\dualguard-student.iss` 创建：

```ini
; DualGuard-Student Inno Setup 脚本
#define MyAppName "DualGuard-Student"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "DualGuard Contributors"
#define MyAppExeName "DualGuard-Student.exe"

[Setup]
AppId={{8F3C2A1B-STU1-4D2A-9C00-DUALGUARDSTU}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\output
OutputBaseFilename=DualGuard-Student-Setup-{#MyAppVersion}
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
Source: "..\staging\DualGuard-Student.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\staging\config.yaml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\staging\audit_policy.json"; DestDir: "{commonappdata}\DualGuard\student"; Flags: onlyifdoesntexist
Source: "..\staging\audit_policy.sha256"; DestDir: "{commonappdata}\DualGuard\student"; Flags: onlyifdoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{commonstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{commonappdata}\DualGuard\student"
```

> 学生版默认卸载也清理数据目录。如校方需保留学习记录复盘，可将 `[UninstallDelete]` 行改为 `Type: files; Name: "{commonappdata}\DualGuard\student\lock.state"` 仅清冻结态。

### 2.5 编译生成安装包

```powershell
cd DualGuard-Student\installer
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" dualguard-student.iss
```

产物：`DualGuard-Student\installer\output\DualGuard-Student-Setup-1.0.0.exe`。

---

## 三、Windows：安装与卸载

### 3.1 安装

1. 右键 `DualGuard-Student-Setup-1.0.0.exe` → **以管理员身份运行**。
2. 选择语言 → 接受许可（含未成年人保护与学习诚信声明）→ 选择目录 → 勾选"开机自启" → 安装 → 完成。
3. 安装后自动启动，托盘出现 DualGuard-Student 图标。

### 3.2 静默安装

```powershell
DualGuard-Student-Setup-1.0.0.exe /SP- /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER=0
```

### 3.3 卸载

- 图形化：控制面板 → 应用 → DualGuard-Student → 卸载。
- 静默卸载：

```powershell
"C:\Program Files\DualGuard-Student\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
```

---

## 四、Windows：机构平板批量预装方案

校方对一批学生平板 / 机房笔记本预装，推荐以下方案。

### 方案 A：U 盘 + 批处理（离线机房最简单）

U 盘根目录：

```
U盘\
├── DualGuard-Student-Setup-1.0.0.exe
├── audit_policy.json          # 本班/本校统一学习诚信策略
├── audit_policy.sha256
└── install.bat
```

`install.bat`：

```bat
@echo off
chcp 65001 >nul
echo === DualGuard-Student 批量预装 ===
%~dp0DualGuard-Student-Setup-1.0.0.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER=0
if errorlevel 1 ( echo 安装失败 & pause & exit /b 1 )
copy /Y "%~dp0audit_policy.json" "%PROGRAMDATA%\DualGuard\student\audit_policy.json"
copy /Y "%~dp0audit_policy.sha256" "%PROGRAMDATA%\DualGuard\student\audit_policy.sha256"
echo === 预装完成，请拔出 U 盘并重启 ===
pause
```

每台平板插入 U 盘 → 右键 `install.bat` → **以管理员身份运行**。

> ⚠ 部署前请确认已完成监护人知情同意流程，策略文案保持温和引导向（见 config.yaml 中 popups）。

### 方案 B：MDM / Intune 集中分发

1. Intune 添加 Win32 应用，上传 `.intunewin` 包。
2. 安装命令：`DualGuard-Student-Setup-1.0.0.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART`
3. 卸载命令：`"%ProgramFiles%\DualGuard-Student\unins000.exe" /VERYSILENT`
4. 安装行为：系统上下文。
5. 策略下发：Intune PowerShell 脚本推送 `audit_policy.json` + `.sha256` 到 `%PROGRAMDATA%\DualGuard\student\`。

### 方案 C：MDT / WDS 装机镜像集成

将安装包加入 MDT 任务序列"安装应用程序"步骤，策略文件作为任务序列末尾"复制文件"步骤写入。

---

## 五、Linux：deb 包编译制作

目标：产出 `dualguard-student_1.0.0_amd64.deb`，注册为 systemd 服务 `dualguard-student.service`。

### 5.1 构建 deb 目录结构

```
build-deb/
└── dualguard-student/
    ├── DEBIAN/
    │   ├── control
    │   ├── postinst
    │   ├── prerm
    │   └── postrm
    ├── usr/bin/dualguard-student
    ├── usr/lib/dualguard-student/
    │   ├── DualGuard-Student
    │   ├── config.yaml
    │   └── common/
    ├── etc/dualguard-student/
    │   ├── audit_policy.json
    │   └── audit_policy.sha256
    └── etc/systemd/system/
        └── dualguard-student.service
```

> `/var/lib/dualguard/student/` 不要打进包里，由程序 `ensure_dirs()` 启动时创建。

### 5.2 用 PyInstaller 产出 Linux 可执行文件

在 Linux 构建机（推荐 Ubuntu 20.04+，与目标机同架构）执行：

```bash
pyinstaller \
  --onefile \
  --name "DualGuard-Student" \
  --add-data "DualGuard-Student/config.yaml:DualGuard-Student" \
  --add-data "common:common" \
  --hidden-import "dualguard_student.rules" \
  "DualGuard-Student/dualguard_student/main.py"
```

> Linux 下 `--add-data` 分隔符是 `:`。

把 `dist/DualGuard-Student` 放入 `build-deb/dualguard-student/usr/lib/dualguard-student/`。

### 5.3 编写 control 文件

`build-deb/dualguard-student/DEBIAN/control`：

```
Package: dualguard-student
Version: 1.0.0
Section: education
Priority: optional
Architecture: amd64
Depends: libc6 (>= 2.31)
Maintainer: DualGuard Contributors <noreply@dualguard.local>
Description: DualGuard-Student (student edition) learning-integrity guard.
 DualGuard-Student is a local-side learning-integrity guard for K12 /
 college programming and block-programming classes. It gently reminds
 students to think independently, counts reminders, and locks features
 for 72h after repeated direct-copy attempts.
 .
 ⚠ For learning guidance only. No homework copying; no copying entire
 block-programming schemes. Mild wording; minor protection compliant.
```

### 5.4 编写 systemd 服务文件

`build-deb/dualguard-student/etc/systemd/system/dualguard-student.service`：

```ini
[Unit]
Description=DualGuard-Student learning-integrity guard (student edition)
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/dualguard-student
WorkingDirectory=/usr/lib/dualguard-student
Restart=on-failure
RestartSec=5
User=_dualguard
Group=_dualguard
Environment=DUALGUARD_DATA_ROOT=/var/lib/dualguard
ProtectSystem=strict
ReadWritePaths=/var/lib/dualguard /var/log/dualguard-student
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

### 5.5 编写维护脚本

`postinst`：

```bash
#!/bin/bash
set -e
if ! id _dualguard >/dev/null 2>&1; then
    useradd --system --no-create-home --shell /usr/sbin/nologin _dualguard
fi
install -d -o _dualguard -g _dualguard /var/lib/dualguard/student
install -d -o _dualguard -g _dualguard /var/log/dualguard-student
systemctl daemon-reload
systemctl enable dualguard-student.service
systemctl start dualguard-student.service
echo "DualGuard-Student 已安装并启动。策略文件位于 /etc/dualguard-student/"
exit 0
```

`prerm`：

```bash
#!/bin/bash
set -e
if [ "$1" = "remove" ] || [ "$1" = "deconfigure" ]; then
    systemctl stop dualguard-student.service || true
    systemctl disable dualguard-student.service || true
fi
exit 0
```

`postrm`：

```bash
#!/bin/bash
set -e
if [ "$1" = "purge" ]; then
    systemctl daemon-reload || true
    rm -rf /var/lib/dualguard/student /var/log/dualguard-student
    echo "已清除 DualGuard-Student 数据目录（purge）。"
fi
exit 0
```

### 5.6 启动脚本 wrapper

`build-deb/dualguard-student/usr/bin/dualguard-student`：

```bash
#!/bin/bash
exec /usr/lib/dualguard-student/DualGuard-Student "$@"
```

### 5.7 赋权并打包

```bash
cd build-deb
chmod 0755 dualguard-student/DEBIAN/postinst \
          dualguard-student/DEBIAN/prerm \
          dualguard-student/DEBIAN/postrm \
          dualguard-student/usr/bin/dualguard-student
chmod 0644 dualguard-student/etc/systemd/system/dualguard-student.service
sudo chown -R root:root dualguard-student
dpkg-deb --build --root-owner-group dualguard-student dualguard-student_1.0.0_amd64.deb
```

产物：`build-deb/dualguard-student_1.0.0_amd64.deb`。

校验：

```bash
dpkg-deb --info dualguard-student_1.0.0_amd64.deb
dpkg-deb --contents dualguard-student_1.0.0_amd64.deb
```

---

## 六、Linux：服务器安装与卸载

### 6.1 安装

```bash
sudo dpkg -i dualguard-student_1.0.0_amd64.deb
# 缺依赖时
sudo apt-get install -f -y
```

`postinst` 自动：建用户 → 建数据目录 → `enable` + `start`。

### 6.2 验证

```bash
systemctl status dualguard-student.service
ls -la /var/lib/dualguard/student/
journalctl -u dualguard-student.service -f
```

### 6.3 卸载

```bash
# 保留学习记录（推荐）
sudo dpkg -r dualguard-student
# 彻底清除
sudo dpkg --purge dualguard-student
```

---

## 七、Linux：后台服务启停与开机自启

```bash
sudo systemctl start   dualguard-student.service
sudo systemctl stop    dualguard-student.service
sudo systemctl restart dualguard-student.service
sudo systemctl status  dualguard-student.service
```

### 开机自启

```bash
sudo systemctl enable  dualguard-student.service   # 开启自启
sudo systemctl disable dualguard-student.service   # 关闭自启
systemctl is-enabled dualguard-student.service     # 查询是否自启
```

### 日志

- systemd journal：`journalctl -u dualguard-student -e --since "1 hour ago"`
- 应用日志文件：`/var/log/dualguard-student/`

### 更新学习诚信策略（不重装）

```bash
sudo cp audit_policy.json   /etc/dualguard-student/audit_policy.json
sudo cp audit_policy.sha256 /etc/dualguard-student/audit_policy.sha256
sudo chown _dualguard:_dualguard /etc/dualguard-student/audit_policy.*
sudo systemctl restart dualguard-student.service
```

> 策略与哈希必须成对更新，否则启动校验失败会触发"篡改程序警告"并从备份恢复。学生版策略文案请保持温和引导向。

---

## 八、部署后自检清单

| 检查项 | Windows | Linux |
|--------|---------|-------|
| 进程在运行 | 任务管理器可见 `DualGuard-Student.exe` | `systemctl status dualguard-student` 为 active |
| 数据目录已建 | `%PROGRAMDATA%\DualGuard\student\` 存在 | `/var/lib/dualguard/student/` 存在 |
| 策略哈希一致 | 启动无篡改弹窗 | 启动无篡改弹窗 |
| 弹窗文案温和 | 单次提示为"学习小提示"，无贬损 | 同左 |
| 冻结生效 | 达阈值后功能锁定 | 达阈值后功能锁定 |
| 监护人知情 | 部署前已留档 | 部署前已留档 |
| 开机自启 | 启动项存在 | `systemctl is-enabled` 返回 enabled |
| 卸载干净 | 控制面板无残留 | `dpkg -l \| grep dualguard-student` 无 |

---

> 如遇问题先看日志：Windows 看 `%PROGRAMDATA%\DualGuard\student\logs\`，Linux 看 `journalctl -u dualguard-student` 与 `/var/log/dualguard-student/`。
