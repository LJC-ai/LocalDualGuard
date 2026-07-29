; ==========================================================================
;  DualGuard-Student Windows 安装包 NSIS 配置
;  与 installer_sec.nsi 结构对称，仅 APP_NAME / 数据目录不同，
;  确保学生版与安全版同机并存时数据完全隔离。
;
;  构建命令（由 build_student.bat 自动调用）：
;    makensis packaging\windows\installer_student.nsi
; ==========================================================================

!define APP_NAME        "DualGuard-Student"
!define APP_VERSION     "1.0.0.0"
!define APP_PUBLISHER   "DualGuard Project"
!define APP_EXE          "DualGuard-Student.exe"
!define APP_REGKEY       "Software\DualGuard-Student"
!define APP_UNINSTKEY    "Software\Microsoft\Windows\CurrentVersion\Uninstall\DualGuard-Student"
!define APP_DATAROOT     "$PROGRAMDATA\DualGuard\student"

Name "${APP_NAME}"
OutFile "..\..\dist\DualGuard-Student-Setup.exe"
Unicode True
ShowInstDetails show
ShowUnInstDetails show
RequestExecutionLevel admin

InstallDir "$PROGRAMFILES64\${APP_NAME}"
InstallDirRegKey HKLM "${APP_REGKEY}" "InstallDir"

!include "MUI2.nsh"
!include "FileFunc.nsh"

!define MUI_ABORTWARNING

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"

Section "Install" SecInstall
  SectionIn RO
  SetOutPath "$INSTDIR"
  File /r "..\..\dist\${APP_NAME}\*.*"

  ; --- 运行期数据目录（与 sec 版完全隔离） ---
  CreateDirectory "${APP_DATAROOT}"
  CreateDirectory "${APP_DATAROOT}\backup"
  CreateDirectory "${APP_DATAROOT}\logs"
  nsExec::ExecToLog 'icacls "${APP_DATAROOT}" /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F"'

  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" \
                 "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\卸载 ${APP_NAME}.lnk" \
                 "$INSTDIR\Uninstall.exe" "" "" 0
  CreateShortcut "$DESKTOP\${APP_NAME}.lnk" \
                 "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0

  WriteUninstaller "$INSTDIR\Uninstall.exe"

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

  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKLM "${APP_UNINSTKEY}" "EstimatedSize" "$0"

  ; 安装后立即生成审核策略 + 哈希备份
  nsExec::ExecToLog '"$INSTDIR\${APP_EXE}" --status'
SectionEnd

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

  ; 同样保留违规记录，防止卸载重装绕过锁定
  MessageBox MB_ICONINFORMATION|MB_OK \
    "${APP_NAME} 已卸载。$\r$\n违规记录与锁定状态已保留在：${APP_DATAROOT}（防止绕过）。"
SectionEnd
