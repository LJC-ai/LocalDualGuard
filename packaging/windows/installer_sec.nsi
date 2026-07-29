; ==========================================================================
;  DualGuard-Sec Windows 安装包 NSIS 配置
;
;  功能：
;    1. 把 PyInstaller 产物安装到 $PROGRAMFILES64\DualGuard-Sec
;    2. 创建 ProgramData\DualGuard\sec 运行期数据目录（违规记录/备份/日志）
;       并设置 ACL（仅当前用户与 SYSTEM 可访问）
;    3. 创建开始菜单 / 桌面快捷方式
;    4. 写入卸载注册表项
;    5. 卸载时清理程序文件（保留 ProgramData 下的违规记录以防绕过卸载规避）
;
;  构建命令（由 build_sec.bat 自动调用）：
;    makensis packaging\windows\installer_sec.nsi
; ==========================================================================

!define APP_NAME        "DualGuard-Sec"
!define APP_VERSION     "1.0.0.0"
!define APP_PUBLISHER   "DualGuard Project"
!define APP_EXE          "DualGuard-Sec.exe"
!define APP_REGKEY       "Software\DualGuard-Sec"
!define APP_UNINSTKEY    "Software\Microsoft\Windows\CurrentVersion\Uninstall\DualGuard-Sec"
!define APP_DATAROOT     "$PROGRAMDATA\DualGuard\sec"

; ---------- 基本设置 ----------
Name "${APP_NAME}"
OutFile "..\..\dist\DualGuard-Sec-Setup.exe"
Unicode True
ShowInstDetails show
ShowUnInstDetails show
RequestExecutionLevel admin   ; 需管理员权限：写 ProgramFiles + ProgramData

InstallDir "$PROGRAMFILES64\${APP_NAME}"
InstallDirRegKey HKLM "${APP_REGKEY}" "InstallDir"

; ---------- 现代化 UI ----------
!include "MUI2.nsh"
!include "FileFunc.nsh"

!define MUI_ABORTWARNING
; 可选：放置图标到 packaging/windows/nsis_assets/app.ico 并取消下面注释
;!define MUI_ICON "packaging\windows\nsis_assets\app.ico"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"

; ==========================================================================
;  安装段
; ==========================================================================
Section "Install" SecInstall
  SectionIn RO
  SetOutPath "$INSTDIR"
  File /r "..\..\dist\${APP_NAME}\*.*"

  ; --- 运行期数据目录 ---
  CreateDirectory "${APP_DATAROOT}"
  CreateDirectory "${APP_DATAROOT}\backup"
  CreateDirectory "${APP_DATAROOT}\logs"
  ; ACL：仅 SYSTEM 与 Administrators 完全控制，Users 只读
  ; （使用 icacls 在安装期一次性设置）
  nsExec::ExecToLog 'icacls "${APP_DATAROOT}" /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F"'

  ; --- 开始菜单快捷方式 ---
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" \
                 "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\卸载 ${APP_NAME}.lnk" \
                 "$INSTDIR\Uninstall.exe" "" "" 0

  ; --- 桌面快捷方式 ---
  CreateShortcut "$DESKTOP\${APP_NAME}.lnk" \
                 "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0

  ; --- 卸载程序 ---
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  ; --- 注册表 ---
  WriteRegStr HKLM "${APP_REGKEY}" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "${APP_REGKEY}" "Version"    "${APP_VERSION}"
  WriteRegStr HKLM "${APP_UNINSTKEY}" "DisplayName"     "${APP_NAME}"
  WriteRegStr HKLM "${APP_UNINSTKEY}" "DisplayVersion"  "${APP_VERSION}"
  WriteRegStr HKLM "${APP_UNINSTKEY}" "Publisher"       "${APP_PUBLISHER}"
  WriteRegStr HKLM "${APP_UNINSTKEY}" "DisplayIcon"     "$INSTDIR\${APP_EXE}"
  WriteRegStr HKLM "${APP_UNINSTKEY}" "UninstallString"  "$\"$INSTDIR\Uninstall.exe$\""
  WriteRegStr HKLM "${APP_UNINSTKEY}" "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKLM "${APP_UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKLM "${APP_UNINSTKEY}" "NoRepair" 1

  ; --- 估算占用空间 ---
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKLM "${APP_UNINSTKEY}" "EstimatedSize" "$0"

  ; --- 安装完成后立即做一次启动自检，生成审核策略与哈希备份 ---
  ;     （若失败仅警告，不回滚安装）
  nsExec::ExecToLog '"$INSTDIR\${APP_EXE}" --status'
SectionEnd

; ==========================================================================
;  卸载段
; ==========================================================================
Section "Uninstall"
  Delete "$INSTDIR\${APP_EXE}"
  RMDir /r "$INSTDIR\_internal"
  RMDir /r "$INSTDIR"
  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\卸载 ${APP_NAME}.lnk"
  RMDir  "$SMPROGRAMS\${APP_NAME}"
  Delete "$DESKTOP\${APP_NAME}.lnk"

  DeleteRegKey HKLM "${APP_UNINSTKEY}"
  DeleteRegKey HKLM "${APP_REGKEY}"

  ; 注意：故意 *不* 删除 ${APP_DATAROOT} 下的违规记录 / 哈希 / 备份，
  ; 防止攻击者通过"卸载-重装"重置违规计数与锁定状态。
  ; 如需彻底清理，管理员手动删除该目录。
  MessageBox MB_ICONINFORMATION|MB_OK \
    "${APP_NAME} 已卸载。$\r$\n违规记录与锁定状态已保留在：${APP_DATAROOT}（防止绕过）。"
SectionEnd
