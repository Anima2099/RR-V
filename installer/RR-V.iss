#define MyAppName "RR-V"
#define MyAppVersion "1.2.0"
#define MyAppPublisher "Anima2099"
#define MyAppURL "https://github.com/Anima2099/RR-V"
#define MyAppExeName "RR-V.exe"

[Setup]
AppId={{A9C3916B-6AA2-4FB8-9BCB-0D5DC6C5D8D4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
AppCopyright=Copyright (c) 2026 Anima2099
DefaultDirName={localappdata}\Programs\RR-V
DefaultGroupName=RR-V
DisableProgramGroupPage=yes
DisableDirPage=no
AlwaysShowDirOnReadyPage=yes
DirExistsWarning=no
UsePreviousAppDir=yes
UsePreviousGroup=yes
UsePreviousTasks=yes
PrivilegesRequired=lowest
SetupArchitecture=x64
OutputDir=..\installer-output
OutputBaseFilename=RR-V_Setup_1.2.0
SetupIconFile=..\resources\icons\RR-V.ico
UninstallDisplayIcon={app}\RR-V.exe
UninstallDisplayName=RR-V 1.2.0
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=RR-V.exe,RR-V-Auth-Helper.exe
RestartApplications=no
SetupLogging=yes
VersionInfoVersion=1.2.0.0
VersionInfoCompany=Anima2099
VersionInfoDescription=RR-V Installer
VersionInfoProductName=RR-V
VersionInfoProductVersion=1.2.0

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 RR-V 바로가기 만들기"; GroupDescription: "추가 바로가기:"; Flags: unchecked

[Files]
Source: "..\dist\RR-V\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\RR-V"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{userdesktop}\RR-V"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "RR-V 실행"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[Code]
var
  DeleteUserDataOnUninstall: Boolean;

function ShowUninstallOptions: Boolean;
var
  OptionsForm: TSetupForm;
  HeadingLabel: TNewStaticText;
  DataCheckBox: TNewCheckBox;
  DetailLabel: TNewStaticText;
  KeepHintLabel: TNewStaticText;
  ContinueButton: TNewButton;
  CancelButton: TNewButton;
begin
  OptionsForm := CreateCustomForm(ScaleX(520), ScaleY(235), False, False);
  try
    OptionsForm.Caption := 'RR-V 제거 옵션';

    HeadingLabel := TNewStaticText.Create(OptionsForm);
    HeadingLabel.Parent := OptionsForm;
    HeadingLabel.Left := ScaleX(24);
    HeadingLabel.Top := ScaleY(20);
    HeadingLabel.Caption := 'RR-V 프로그램 파일은 항상 제거됩니다.';
    HeadingLabel.Font.Style := [fsBold];
    HeadingLabel.AutoSize := True;

    DataCheckBox := TNewCheckBox.Create(OptionsForm);
    DataCheckBox.Parent := OptionsForm;
    DataCheckBox.Left := ScaleX(24);
    DataCheckBox.Top := ScaleY(58);
    DataCheckBox.Width := ScaleX(460);
    DataCheckBox.Caption := 'RR-V 사용자 데이터도 함께 삭제';
    DataCheckBox.Checked := False;

    DetailLabel := TNewStaticText.Create(OptionsForm);
    DetailLabel.Parent := OptionsForm;
    DetailLabel.Left := ScaleX(44);
    DetailLabel.Top := ScaleY(88);
    DetailLabel.Width := ScaleX(440);
    DetailLabel.Height := ScaleY(46);
    DetailLabel.AutoSize := False;
    DetailLabel.WordWrap := True;
    DetailLabel.Caption := '체크하면 설정, 로그인 정보, 로그, 백업, 다운로드한 yt-dlp / FFmpeg / Deno와 인증 런타임까지 삭제합니다.';

    KeepHintLabel := TNewStaticText.Create(OptionsForm);
    KeepHintLabel.Parent := OptionsForm;
    KeepHintLabel.Left := ScaleX(44);
    KeepHintLabel.Top := ScaleY(137);
    KeepHintLabel.Width := ScaleX(440);
    KeepHintLabel.Height := ScaleY(34);
    KeepHintLabel.AutoSize := False;
    KeepHintLabel.WordWrap := True;
    KeepHintLabel.Caption := '체크하지 않으면 나중에 RR-V를 다시 설치할 때 사용할 수 있도록 사용자 데이터를 보존합니다.';

    ContinueButton := TNewButton.Create(OptionsForm);
    ContinueButton.Parent := OptionsForm;
    ContinueButton.Width := ScaleX(92);
    ContinueButton.Height := ScaleY(26);
    ContinueButton.Left := OptionsForm.ClientWidth - ScaleX(204);
    ContinueButton.Top := OptionsForm.ClientHeight - ScaleY(42);
    ContinueButton.Caption := '계속';
    ContinueButton.Default := True;
    ContinueButton.ModalResult := mrOk;

    CancelButton := TNewButton.Create(OptionsForm);
    CancelButton.Parent := OptionsForm;
    CancelButton.Width := ScaleX(92);
    CancelButton.Height := ScaleY(26);
    CancelButton.Left := OptionsForm.ClientWidth - ScaleX(104);
    CancelButton.Top := OptionsForm.ClientHeight - ScaleY(42);
    CancelButton.Caption := '취소';
    CancelButton.Cancel := True;
    CancelButton.ModalResult := mrCancel;

    OptionsForm.ActiveControl := ContinueButton;
    Result := OptionsForm.ShowModal = mrOk;
    if Result then
      DeleteUserDataOnUninstall := DataCheckBox.Checked;
  finally
    OptionsForm.Free;
  end;
end;

function InitializeUninstall: Boolean;
begin
  DeleteUserDataOnUninstall := False;
  Result := ShowUninstallOptions;
end;

procedure RemoveIntegrationRegistrations;
var
  LocalRRVDir: String;
  ManifestPath: String;
  EndpointPath: String;
begin
  RegDeleteValue(
    HKCU,
    'Software\Microsoft\Windows\CurrentVersion\Run',
    'RR-V'
  );

  RegDeleteKeyIncludingSubkeys(
    HKCU,
    'Software\Google\Chrome\NativeMessagingHosts\com.rrv.browser_bridge'
  );
  RegDeleteKeyIncludingSubkeys(
    HKCU,
    'Software\Microsoft\Edge\NativeMessagingHosts\com.rrv.browser_bridge'
  );

  LocalRRVDir := ExpandConstant('{localappdata}\RR-V');
  ManifestPath := LocalRRVDir + '\browser-integration\com.rrv.browser_bridge.json';
  EndpointPath := LocalRRVDir + '\external-url-endpoint.json';
  DeleteFile(ManifestPath);
  DeleteFile(EndpointPath);
  RemoveDir(LocalRRVDir + '\browser-integration');
end;

procedure RemoveUserData;
begin
  DelTree(ExpandConstant('{localappdata}\RR-V'), True, True, True);
  DelTree(ExpandConstant('{userappdata}\RR-V'), True, True, True);
  RegDeleteKeyIncludingSubkeys(HKCU, 'Software\RR-V');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    RemoveIntegrationRegistrations;

  if CurUninstallStep = usPostUninstall then
  begin
    if DeleteUserDataOnUninstall then
      RemoveUserData;
  end;
end;
