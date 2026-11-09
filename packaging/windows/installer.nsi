Unicode true
RequestExecutionLevel user
SetCompressor /SOLID lzma

!include "MUI2.nsh"

!ifndef APP_VERSION
  !define APP_VERSION "0.1.0-beta.1"
!endif
!ifndef APP_VERSION_NUM
  !define APP_VERSION_NUM "0.1.0.0"
!endif
!ifndef BUILD_DIR
  !error "BUILD_DIR is required"
!endif
!ifndef OUTPUT_FILE
  !define OUTPUT_FILE "MingyanAI-${APP_VERSION}-Setup.exe"
!endif

!define PRODUCT_NAME "明琰AI平台"
!define PRODUCT_PUBLISHER "吉林省明琰科技发展有限公司"
!define PRODUCT_UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\MingyanAI"

Name "${PRODUCT_NAME}"
OutFile "${OUTPUT_FILE}"
InstallDir "$LOCALAPPDATA\Programs\MingyanAI"
InstallDirRegKey HKCU "Software\MingyanAI" "InstallDir"

VIProductVersion "${APP_VERSION_NUM}"
VIAddVersionKey /LANG=2052 "ProductName" "${PRODUCT_NAME}"
VIAddVersionKey /LANG=2052 "CompanyName" "${PRODUCT_PUBLISHER}"
VIAddVersionKey /LANG=2052 "FileDescription" "${PRODUCT_NAME} Windows 安装程序"
VIAddVersionKey /LANG=2052 "FileVersion" "${APP_VERSION}"

!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\MingyanAI.exe"
!define MUI_FINISHPAGE_RUN_TEXT "启动明琰AI平台"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"

Section "安装明琰AI平台" MainSection
  SetShellVarContext current
  SetOutPath "$INSTDIR"
  File /r "${BUILD_DIR}\*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  CreateDirectory "$SMPROGRAMS\明琰AI平台"
  CreateShortcut "$SMPROGRAMS\明琰AI平台\明琰AI平台.lnk" "$INSTDIR\MingyanAI.exe"
  CreateShortcut "$SMPROGRAMS\明琰AI平台\卸载明琰AI平台.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortcut "$DESKTOP\明琰AI平台.lnk" "$INSTDIR\MingyanAI.exe"

  WriteRegStr HKCU "Software\MingyanAI" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${PRODUCT_UNINSTALL_KEY}" "DisplayName" "${PRODUCT_NAME}"
  WriteRegStr HKCU "${PRODUCT_UNINSTALL_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "${PRODUCT_UNINSTALL_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"
  WriteRegStr HKCU "${PRODUCT_UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${PRODUCT_UNINSTALL_KEY}" "UninstallString" '$"$INSTDIR\Uninstall.exe$"'
  WriteRegDWORD HKCU "${PRODUCT_UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${PRODUCT_UNINSTALL_KEY}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  nsExec::ExecToLog 'taskkill /IM MingyanAI.exe /F'
  Delete "$DESKTOP\明琰AI平台.lnk"
  RMDir /r "$SMPROGRAMS\明琰AI平台"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "${PRODUCT_UNINSTALL_KEY}"
  DeleteRegKey HKCU "Software\MingyanAI"
SectionEnd
