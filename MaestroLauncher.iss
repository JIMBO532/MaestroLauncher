; Inno Setup script for MaestroLauncher.
;
;     "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" MaestroLauncher.iss
;
; Normally you want build.bat instead, which builds the exe first and then
; calls this with the version read out of core/__init__.py. Compiling this on
; its own works too and falls back to the version defined below.
;
; Produces launcher\MaestroLauncherSetup.exe. launcher\ is gitignored, so the
; installer lands in the same one place the exe does and neither can reach a
; commit.
;
; Installs per-user into %LOCALAPPDATA%\Programs, not Program Files, so no
; administrator rights are needed and no UAC prompt appears. That is also why
; PrivilegesRequired is lowest: with it set, Inno's {auto*} constants all
; resolve to their per-user form, so the Start Menu entry and the
; Add/Remove Programs registration go under HKCU rather than being refused.

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

#define AppName "MaestroLauncher"
#define AppPublisher "Dimitris"
#define AppExeName "MaestroLauncher.exe"

[Setup]
; Never reuse this GUID for another program: it is the identity Windows uses
; to recognise an upgrade of this one and to find it again to uninstall it.
AppId={{6BDC25FF-3343-4B71-9AA2-691883FEFB4D}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}

DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; The Mojang notice goes here rather than in LicenseFile: the licence page is
; the MIT terms for this launcher's own source, which is a different thing
; from "this is not a Mojang product", and burying the second inside the
; first is how people end up never reading either.
LicenseFile=LICENSE
InfoBeforeFile=installer\disclaimer.txt

SetupIconFile=installer\MaestroLauncher.ico
; What Add/Remove Programs shows beside the entry. Pointing it at the
; installed exe rather than at a copied .ico means it cannot go stale.
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}

OutputDir=launcher
OutputBaseFilename={#AppName}Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; Unchecked by default, which is the Windows convention: a desktop icon
; nobody asked for is the thing every installer gets complained about.
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "launcher\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

; Nothing here removes %APPDATA%\MaestroLauncher or %APPDATA%\.minecraft on
; uninstall, and that is deliberate. The first holds a background image the
; person chose; the second is their Minecraft installation, which this
; launcher adds versions to but does not own. An uninstaller that deletes
; either would be destroying data it was never asked to manage.
