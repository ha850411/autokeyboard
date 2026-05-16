[Setup]
AppId={{A9D31B90-EC5D-4A51-8792-55F52C39391C}
AppName=AutoKeyboard
AppVersion=1.5.4
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
SetupIconFile=assets\AutoKeyboard.ico
WizardStyle=modern
CloseApplications=force
CloseApplicationsFilter=*.exe
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\AutoKeyboard.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\AutoKeyboard"; Filename: "{app}\AutoKeyboard.exe"
Name: "{autodesktop}\AutoKeyboard"; Filename: "{app}\AutoKeyboard.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AutoKeyboard.exe"; Description: "{cm:LaunchProgram,AutoKeyboard}"; Flags: nowait postinstall skipifsilent

[Code]
procedure KillRunningAutoKeyboard();
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM AutoKeyboard.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  KillRunningAutoKeyboard();
  Result := '';
end;
