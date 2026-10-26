; Digital Library setup program (NSIS 3 + Modern UI 2).
;
; Build with:
;   makensis /DVERSION=2.4.0 /DSRCDIR=<installed build folder> ^
;            /DOUTFILE=<setup.exe> installer\DigitalLibrary.nsi
;
; The wizard installs the folder build under Program Files, writes the
; install_info.json marker that lets the app update itself in place and
; registers a normal uninstaller entry.

!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"

!ifndef VERSION
  !define VERSION "0.0.0"
!endif
!ifndef SRCDIR
  !define SRCDIR "dist\installed\DigitalLibrary"
!endif
!ifndef OUTFILE
  !define OUTFILE "DigitalLibrary-Setup.exe"
!endif
; NSIS resolves relative paths against this script, not the working directory,
; so the icon is addressed from the installer folder.
!ifndef APP_ICON
  !define APP_ICON "${__FILEDIR__}\..\assets\icon.ico"
!endif

!define APP_NAME "Digital Library"
!define APP_EXE "DigitalLibrary.exe"
!define APP_PUBLISHER "AmirGFno"
!define APP_URL "https://github.com/AmirGFno/digital_library"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\DigitalLibrary"
!define INSTALL_MARKER "install_info.json"

Name "${APP_NAME} ${VERSION}"
OutFile "${OUTFILE}"
Unicode true
RequestExecutionLevel admin
!ifdef NO_COMPRESSION
  SetCompressor none
!else
  SetCompressor /SOLID lzma
!endif
InstallDir "$PROGRAMFILES64\${APP_NAME}"
InstallDirRegKey HKLM "${UNINST_KEY}" "InstallLocation"
ShowInstDetails show
ShowUninstDetails show
BrandingText "${APP_NAME} ${VERSION}"

VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${APP_NAME}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "FileDescription" "${APP_NAME} Setup"
VIAddVersionKey "FileVersion" "${VERSION}.0"
VIAddVersionKey "CompanyName" "${APP_PUBLISHER}"
VIAddVersionKey "LegalCopyright" "Free for personal use"

!define MUI_ABORTWARNING
!define MUI_ICON "${APP_ICON}"
!define MUI_UNICON "${APP_ICON}"
!define MUI_WELCOMEPAGE_TITLE "Install ${APP_NAME} ${VERSION}"
!define MUI_WELCOMEPAGE_TEXT "This wizard installs ${APP_NAME} on this computer.$\r$\n$\r$\nThe program keeps itself up to date: a new release downloads only the files that changed and is applied in place, without downloading or installing everything again.$\r$\n$\r$\nYour comics stay in your own library folder and your settings stay in your user profile. Updating or uninstalling never touches them."
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Open ${APP_NAME}"
!define MUI_FINISHPAGE_LINK "Project page"
!define MUI_FINISHPAGE_LINK_LOCATION "${APP_URL}"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "Farsi"

Section "Application" SEC_APP
  SectionIn RO
  SetOutPath "$INSTDIR"
  SetOverwrite on
  File /r "${SRCDIR}\*.*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  ; The marker turns this folder into an "installed edition": user data moves
  ; to the profile and the app may update its own files.
  FileOpen $0 "$INSTDIR\${INSTALL_MARKER}" w
  FileWrite $0 '{$\r$\n  "installed": true,$\r$\n  "version": "${VERSION}",$\r$\n  "installer": "nsis"$\r$\n}$\r$\n'
  FileClose $0

  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\Uninstall ${APP_NAME}.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"

  WriteRegStr HKLM "${UNINST_KEY}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKLM "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKLM "${UNINST_KEY}" "Publisher" "${APP_PUBLISHER}"
  WriteRegStr HKLM "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\${APP_EXE}"
  WriteRegStr HKLM "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${UNINST_KEY}" "URLInfoAbout" "${APP_URL}"
  WriteRegDWORD HKLM "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINST_KEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKLM "${UNINST_KEY}" "EstimatedSize" "$0"
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\${APP_NAME}.lnk"
  RMDir /r "$SMPROGRAMS\${APP_NAME}"
  DeleteRegKey HKLM "${UNINST_KEY}"
  RMDir /r "$INSTDIR"
SectionEnd
