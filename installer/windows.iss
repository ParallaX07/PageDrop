; PageDrop — Windows installer (Inno Setup 6+)
;
; Prerequisites:
;   uv sync --group dev
;   uv run --with pillow python scripts/generate_icons.py   ; if app-icon.ico missing
;   uv run pyinstaller --noconfirm pagedrop.spec            ; dist/pagedrop/pagedrop.exe
;
; Build installer (version from pyproject.toml via /DAppVersion=…):
;   .\scripts\build_windows_installer.ps1
;   ; or: iscc /DAppVersion=0.5.0 installer/windows.iss
;
; Output: installer/Output/PageDrop-<version>-Setup.exe

#ifndef AppVersion
  #define AppVersion "0.5.0"
#endif

#define AppExeName "pagedrop.exe"
#define AppName "PageDrop"
#define AppPublisher "PageDrop"
#define DistDir "..\dist\pagedrop"

[Setup]
AppId={{A7C3E91F-2B4D-4F8A-9E1C-6D5B0A8F3C21}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=PageDrop-{#AppVersion}-Setup
Compression=lzma2/max
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
WizardStyle=modern
SetupIconFile=..\src\pagedrop\assets\app-icon.ico
LicenseFile=..\LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; PyInstaller onedir tree (exe + Qt/plugins + bundled datas)
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Licence texts from repo root (also in onedir datas; keep explicit install copies)
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; \
  Flags: nowait postinstall skipifsilent
