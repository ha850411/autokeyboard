[Setup]
AppId={{A9D31B90-EC5D-4A51-8792-55F52C39391C}
AppName=AutoKeyboard
AppVersion=1.5.6
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
Source: "dist\AutoKeyboard.exe"; DestDir: "{app}"; Flags: ignoreversion restartreplace; BeforeInstall: KillRunningAutoKeyboard

[Icons]
Name: "{group}\AutoKeyboard"; Filename: "{app}\AutoKeyboard.exe"
Name: "{autodesktop}\AutoKeyboard"; Filename: "{app}\AutoKeyboard.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AutoKeyboard.exe"; Description: "{cm:LaunchProgram,AutoKeyboard}"; Flags: nowait postinstall skipifsilent

[Code]
function AutoKeyboardExePath(): String;
begin
  Result := ExpandConstant('{app}\AutoKeyboard.exe');
end;

function CanReplaceAutoKeyboardExe(): Boolean;
var
  AppExePath: String;
  ProbePath: String;
begin
  AppExePath := AutoKeyboardExePath();
  if not FileExists(AppExePath) then
  begin
    Result := True;
    Exit;
  end;

  ProbePath := AppExePath + '.replacecheck';
  DeleteFile(ProbePath);
  Result := RenameFile(AppExePath, ProbePath);
  if Result then
  begin
    if not RenameFile(ProbePath, AppExePath) then
    begin
      CopyFile(ProbePath, AppExePath, False);
      DeleteFile(ProbePath);
    end;
  end;
end;

procedure KillRunningAutoKeyboard();
var
  ResultCode: Integer;
  Attempt: Integer;
begin
  for Attempt := 1 to 10 do
  begin
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM AutoKeyboard.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(500);

    if CanReplaceAutoKeyboardExe() then
      Exit;
  end;
end;

procedure CleanupPyInstallerTempDirs();
var
  FindRec: TFindRec;
  TempPath: String;
begin
  TempPath := GetTempDir();
  if FindFirst(TempPath + '_MEI*', FindRec) then
  begin
    try
      repeat
        if FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0 then
          DelTree(TempPath + FindRec.Name, True, True, True);
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  KillRunningAutoKeyboard();
  CleanupPyInstallerTempDirs();
  if CanReplaceAutoKeyboardExe() then
    Result := ''
  else
    Result := 'AutoKeyboard.exe 仍在執行或被鎖定，請關閉 AutoKeyboard 後再重新安裝。';
end;
