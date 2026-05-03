[Setup]
AppId={{A9D31B90-EC5D-4A51-8792-55F52C39391C}
AppName=AutoKeyboard
AppVersion=1.0.0
AppPublisher=AutoKeyboard
DefaultDirName={localappdata}\Programs\AutoKeyboard
DefaultGroupName=AutoKeyboard
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=AutoKeyboard_Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\AutoKeyboard.exe
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\AutoKeyboard.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\scripts.json"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist
Source: "assets\icon.ico"; DestDir: "{app}\assets"; Flags: ignoreversion

[Icons]
Name: "{group}\AutoKeyboard"; Filename: "{app}\AutoKeyboard.exe"; IconFilename: "{app}\assets\icon.ico"
Name: "{group}\{cm:UninstallProgram,AutoKeyboard}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\AutoKeyboard"; Filename: "{app}\AutoKeyboard.exe"; IconFilename: "{app}\assets\icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\AutoKeyboard.exe"; Description: "{cm:LaunchProgram,AutoKeyboard}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\scripts.json"
Type: dirifempty; Name: "{app}\assets"
Type: dirifempty; Name: "{app}"
