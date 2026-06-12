#define AppName "NGA Wolf Watcher"
#define AppPublisher "huangbwww"
#define AppExeName "NGA-Wolf-Watcher.exe"
#ifndef AppVersion
#define AppVersion "0.0.0"
#endif
#ifndef SourceDir
#define SourceDir "..\\..\\dist\\NGA-Wolf-Watcher"
#endif
#ifndef OutputDir
#define OutputDir "..\\..\\dist"
#endif
#ifndef OutputBaseFilename
#define OutputBaseFilename "nga-wolf-watcher-windows-x86_64-setup"
#endif

[Setup]
AppId={{A5A20856-41EA-4A4F-B6D1-2B7C5900D43D}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\NGA Wolf Watcher
DefaultGroupName=NGA Wolf Watcher
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\..\assets\app_icon.ico
UninstallDisplayIcon={app}\NGA-Wolf-Watcher.exe

[Languages]
Name: "chinesesimplified"; MessagesFile: ".\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\NGA Wolf Watcher"; Filename: "{app}\{#AppExeName}"
Name: "{userdesktop}\NGA Wolf Watcher"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,NGA Wolf Watcher}"; Flags: nowait postinstall skipifsilent
