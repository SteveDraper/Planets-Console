; v1 console package Windows installer wrapper (Inno Setup).
; Per-user, unsigned. Do not add uninstall rules for per-user support files.

#ifndef MyAppVersion
  #error MyAppVersion must be defined (ISCC /DMyAppVersion=...)
#endif
#ifndef MyAppName
  #error MyAppName must be defined (ISCC /DMyAppName=...)
#endif
#ifndef MyAppExeName
  #error MyAppExeName must be defined (ISCC /DMyAppExeName=...)
#endif
#ifndef MyAppId
  #error MyAppId must be defined (ISCC /DMyAppId=...)
#endif
#ifndef SourceDir
  #error SourceDir must be defined (ISCC /DSourceDir=...)
#endif
#ifndef OutputDir
  #error OutputDir must be defined (ISCC /DOutputDir=...)
#endif
#ifndef OutputBaseFilename
  #error OutputBaseFilename must be defined (ISCC /DOutputBaseFilename=...)
#endif

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
DefaultDirName={localappdata}\Programs\{#MyAppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
DisableDirPage=yes
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
CloseApplications=yes
MinVersion=10.0
UsePreviousAppDir=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
