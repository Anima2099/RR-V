#define MyAppName "RR-V"
#define MyAppVersion "1.4.0"
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
OutputBaseFilename=RR-V_Setup_{#MyAppVersion}
SetupIconFile=..\resources\icons\RR-V.ico
UninstallDisplayIcon={app}\RR-V.exe
UninstallDisplayName=RR-V {#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=RR-V.exe,RR-V-Auth-Helper.exe
RestartApplications=no
SetupLogging=yes
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany=Anima2099
VersionInfoDescription=RR-V Installer
VersionInfoProductName=RR-V
VersionInfoProductVersion={#MyAppVersion}

; Inno Setup의 외부 언어 파일 설치 여부에 의존하지 않고, RR-V가 실제로
; 사용하는 기본 설치/제거 UI 메시지를 이 스크립트 안에서 한국어로 통일한다.
[Messages]
SetupAppTitle=RR-V 설치
SetupWindowTitle=%1 설치
UninstallAppTitle=RR-V 제거
UninstallAppFullTitle=%1 제거
InformationTitle=정보
ConfirmTitle=확인
ErrorTitle=오류
SetupLdrStartupMessage=RR-V를 설치합니다. 계속하시겠습니까?
SetupAlreadyRunning=설치 프로그램이 이미 실행 중입니다.
SetupAppRunningError=설치 프로그램이 현재 RR-V가 실행 중인 것을 확인했습니다.%n%n실행 중인 RR-V를 모두 종료한 다음 확인을 눌러 계속하거나, 취소를 눌러 설치를 종료하세요.
UninstallAppRunningError=제거 프로그램이 현재 RR-V가 실행 중인 것을 확인했습니다.%n%n실행 중인 RR-V를 모두 종료한 다음 확인을 눌러 계속하거나, 취소를 눌러 제거를 종료하세요.
ExitSetupTitle=설치 종료
ExitSetupMessage=설치가 아직 완료되지 않았습니다. 지금 종료하면 프로그램이 설치되지 않습니다.%n%n나중에 설치 프로그램을 다시 실행하여 설치를 완료할 수 있습니다.%n%n설치를 종료하시겠습니까?
ButtonBack=< 이전(&B)
ButtonNext=다음(&N) >
ButtonInstall=설치(&I)
ButtonOK=확인
ButtonCancel=취소
ButtonYes=예(&Y)
ButtonYesToAll=모두 예(&A)
ButtonNo=아니요(&N)
ButtonNoToAll=모두 아니요(&O)
ButtonFinish=완료(&F)
ButtonBrowse=찾아보기(&B)...
ButtonWizardBrowse=찾아보기(&B)...
ButtonNewFolder=새 폴더 만들기(&M)
ClickNext=계속하려면 다음을 누르고, 설치를 종료하려면 취소를 누르세요.
BrowseDialogTitle=폴더 찾아보기
BrowseDialogLabel=아래 목록에서 폴더를 선택한 다음 확인을 누르세요.
NewFolderName=새 폴더
WizardSelectDir=설치 위치 선택
SelectDirDesc=RR-V를 어디에 설치하시겠습니까?
SelectDirLabel3=RR-V를 다음 폴더에 설치합니다.
SelectDirBrowseLabel=계속하려면 다음을 누르세요. 다른 폴더를 선택하려면 찾아보기를 누르세요.
DiskSpaceGBLabel=최소 [gb] GB의 사용 가능한 디스크 공간이 필요합니다.
DiskSpaceMBLabel=최소 [mb] MB의 사용 가능한 디스크 공간이 필요합니다.
CannotInstallToNetworkDrive=네트워크 드라이브에는 설치할 수 없습니다.
CannotInstallToUNCPath=UNC 경로에는 설치할 수 없습니다.
InvalidPath=드라이브 문자를 포함한 전체 경로를 입력해야 합니다. 예:%n%nC:\App%n%n또는 다음 형식의 UNC 경로:%n%n\\server\share
InvalidDrive=선택한 드라이브 또는 UNC 공유가 없거나 접근할 수 없습니다. 다른 위치를 선택해 주세요.
DiskSpaceWarningTitle=디스크 공간 부족
DiskSpaceWarning=설치하려면 최소 %1 KB의 여유 공간이 필요하지만, 선택한 드라이브에는 %2 KB만 사용할 수 있습니다.%n%n그래도 계속하시겠습니까?
DirNameTooLong=폴더 이름 또는 경로가 너무 깁니다.
InvalidDirName=폴더 이름이 올바르지 않습니다.
BadDirName32=폴더 이름에는 다음 문자를 사용할 수 없습니다:%n%n%1
DirExistsTitle=폴더가 이미 있습니다
DirExists=다음 폴더가 이미 있습니다:%n%n%1%n%n그래도 이 폴더에 설치하시겠습니까?
DirDoesntExistTitle=폴더가 없습니다
DirDoesntExist=다음 폴더가 없습니다:%n%n%1%n%n폴더를 새로 만드시겠습니까?
WizardSelectTasks=추가 작업 선택
SelectTasksDesc=어떤 추가 작업을 수행하시겠습니까?
SelectTasksLabel2=RR-V 설치 중 수행할 추가 작업을 선택한 뒤 다음 버튼을 누르세요.
WizardReady=설치 준비 완료
ReadyLabel1=RR-V를 설치할 준비가 되었습니다.
ReadyLabel2a=설치를 시작하려면 설치를 누르세요. 설정을 확인하거나 변경하려면 이전을 누르세요.
ReadyLabel2b=설치를 시작하려면 설치를 누르세요.
ReadyMemoUserInfo=사용자 정보:
ReadyMemoDir=설치 위치:
ReadyMemoType=설치 유형:
ReadyMemoComponents=선택한 구성 요소:
ReadyMemoGroup=시작 메뉴 폴더:
ReadyMemoTasks=추가 작업:
WizardPreparing=설치 준비 중
PreparingDesc=RR-V 설치를 준비하고 있습니다.
PreviousInstallNotCompleted=이전 프로그램의 설치 또는 제거가 완료되지 않았습니다. 해당 작업을 완료하려면 컴퓨터를 다시 시작해야 합니다.%n%n컴퓨터를 다시 시작한 뒤 설치 프로그램을 다시 실행하여 RR-V 설치를 완료하세요.
CannotContinue=설치를 계속할 수 없습니다. 취소를 눌러 종료하세요.
ApplicationsFound=다음 프로그램이 설치 프로그램에서 업데이트해야 하는 파일을 사용하고 있습니다. 설치 프로그램이 해당 프로그램을 자동으로 종료하도록 허용하는 것을 권장합니다.
ApplicationsFound2=다음 프로그램이 설치 프로그램에서 업데이트해야 하는 파일을 사용하고 있습니다. 설치 프로그램이 해당 프로그램을 자동으로 종료하도록 허용하는 것을 권장합니다. 설치가 끝나면 프로그램을 다시 실행하려고 시도합니다.
CloseApplications=프로그램을 자동으로 종료(&A)
DontCloseApplications=프로그램을 종료하지 않음(&D)
ErrorCloseApplications=일부 프로그램을 자동으로 종료하지 못했습니다. 계속하기 전에 업데이트할 파일을 사용 중인 프로그램을 직접 종료하는 것을 권장합니다.
PrepareToInstallNeedsRestart=컴퓨터를 다시 시작해야 합니다. 다시 시작한 뒤 설치 프로그램을 실행하여 RR-V 설치를 완료하세요.%n%n지금 다시 시작하시겠습니까?
WizardInstalling=설치 중
InstallingLabel=RR-V를 설치하는 동안 잠시 기다려 주세요.
FinishedHeadingLabel=RR-V 설치 완료
FinishedLabelNoIcons=RR-V 설치가 완료되었습니다.
FinishedLabel=RR-V 설치가 완료되었습니다. 설치된 바로가기를 통해 프로그램을 실행할 수 있습니다.
ClickFinish=설치 프로그램을 종료하려면 완료를 누르세요.
FinishedRestartLabel=RR-V 설치를 완료하려면 컴퓨터를 다시 시작해야 합니다. 지금 다시 시작하시겠습니까?
FinishedRestartMessage=RR-V 설치를 완료하려면 컴퓨터를 다시 시작해야 합니다.%n%n지금 다시 시작하시겠습니까?
RunEntryExec=%1 실행
SetupAborted=설치가 완료되지 않았습니다.%n%n문제를 해결한 뒤 설치 프로그램을 다시 실행해 주세요.
StatusClosingApplications=실행 중인 프로그램을 종료하는 중...
StatusCreateDirs=폴더를 만드는 중...
StatusExtractFiles=파일을 설치하는 중...
StatusCreateIcons=바로가기를 만드는 중...
StatusCreateRegistryEntries=Windows 등록 정보를 구성하는 중...
StatusSavingUninstall=제거 정보를 저장하는 중...
StatusRunProgram=설치를 마무리하는 중...
StatusRestartingApplications=프로그램을 다시 실행하는 중...
StatusRollback=변경 사항을 되돌리는 중...
ErrorExecutingProgram=파일을 실행할 수 없습니다:%n%1
UninstallNotFound=파일 "%1"을(를) 찾을 수 없어 제거할 수 없습니다.
UninstallOpenError=파일 "%1"을(를) 열 수 없어 제거할 수 없습니다.
UninstallUnsupportedVer=제거 로그 파일 "%1"의 형식을 현재 제거 프로그램에서 인식할 수 없어 제거할 수 없습니다.
UninstallUnknownEntry=제거 로그에서 알 수 없는 항목(%1)을 발견했습니다.
ConfirmUninstall=%1 및 관련 구성요소를 제거하시겠습니까?
UninstallOnlyOnWin64=이 프로그램은 64비트 Windows에서만 제거할 수 있습니다.
OnlyAdminCanUninstall=이 프로그램은 관리자 권한이 있는 사용자만 제거할 수 있습니다.
UninstallStatusLabel=RR-V를 제거하는 동안 잠시 기다려 주세요.
UninstalledAll=%1 제거가 완료되었습니다.
UninstalledMost=%1 제거가 완료되었습니다.%n%n일부 항목은 제거하지 못했습니다. 해당 항목은 직접 삭제할 수 있습니다.
UninstalledAndNeedsRestart=%1 제거를 완료하려면 컴퓨터를 다시 시작해야 합니다.%n%n지금 다시 시작하시겠습니까?
WizardUninstalling=제거 중
StatusUninstalling=%1 제거 중...

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
const
  RRVUninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{A9C3916B-6AA2-4FB8-9BCB-0D5DC6C5D8D4}_is1';
  InstallManifestName = 'RRV_INSTALL_MANIFEST.txt';

var
  DeleteUserDataOnUninstall: Boolean;
  PreviousInstallDetected: Boolean;
  CleanPreviousAppPayload: Boolean;
  ResetUserDataOnUpgrade: Boolean;
  UpgradeOptionsPage: TInputOptionWizardPage;

function IsPreviousInstallPresent: Boolean;
begin
  Result := RegKeyExists(HKCU, RRVUninstallKey) or
    FileExists(ExpandConstant('{app}\RR-V.exe'));
end;

procedure InitializeWizard;
begin
  PreviousInstallDetected := IsPreviousInstallPresent;
  CleanPreviousAppPayload := False;
  ResetUserDataOnUpgrade := False;

  UpgradeOptionsPage := CreateInputOptionPage(
    wpSelectDir,
    'RR-V 업데이트 옵션',
    '기존 설치를 어떻게 처리할까요?',
    '기존 RR-V 프로그램 파일은 새 버전 기준으로 정리한 뒤 설치합니다.' + #13#10 +
    '기본값은 설정, 로그인, 프리셋과 다운로드 도구를 그대로 유지합니다.',
    False,
    False
  );
  UpgradeOptionsPage.Add('설정, 로그인, 프리셋 및 다운로드 도구도 초기화');
  UpgradeOptionsPage.Values[0] := False;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PageID = UpgradeOptionsPage.ID then
    Result := not PreviousInstallDetected;
end;

function ManifestContains(
  const Entries: TArrayOfString;
  const RelativePath: String
): Boolean;
var
  I: Integer;
  Target: String;
begin
  Result := False;
  Target := Lowercase(RelativePath);
  for I := 0 to GetArrayLength(Entries) - 1 do
  begin
    if Lowercase(Trim(Entries[I])) = Target then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function IsUninstallerArtifact(const RelativePath: String): Boolean;
var
  LowerName: String;
begin
  if Pos('\', RelativePath) > 0 then
  begin
    Result := False;
    Exit;
  end;

  LowerName := Lowercase(RelativePath);
  Result := Pos('unins', LowerName) = 1;
end;

procedure RemoveStalePayloadInDirectory(
  const RootDir: String;
  const CurrentDir: String;
  const Entries: TArrayOfString
);
var
  FindRec: TFindRec;
  FullPath: String;
  RootPrefix: String;
  RelativePath: String;
begin
  RootPrefix := AddBackslash(RootDir);
  if FindFirst(AddBackslash(CurrentDir) + '*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
        begin
          FullPath := AddBackslash(CurrentDir) + FindRec.Name;
          RelativePath := Copy(
            FullPath,
            Length(RootPrefix) + 1,
            Length(FullPath)
          );

          if (FindRec.Attributes and FILE_ATTRIBUTE_REPARSE_POINT) <> 0 then
          begin
            Log('RR-V clean upgrade: reparse point skipped: ' + RelativePath);
          end
          else if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
          begin
            RemoveStalePayloadInDirectory(RootDir, FullPath, Entries);
            RemoveDir(FullPath);
          end
          else if
            (not IsUninstallerArtifact(RelativePath)) and
            (not ManifestContains(Entries, RelativePath))
          then
          begin
            if DeleteFile(FullPath) then
              Log('RR-V clean upgrade: removed stale file: ' + RelativePath)
            else
              Log('RR-V clean upgrade: could not remove stale file: ' + RelativePath);
          end;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

procedure RemoveStaleApplicationPayload;
var
  ManifestPath: String;
  Entries: TArrayOfString;
begin
  if not CleanPreviousAppPayload then
    Exit;

  ManifestPath := AddBackslash(ExpandConstant('{app}')) + InstallManifestName;
  if not LoadStringsFromFile(ManifestPath, Entries) then
  begin
    Log('RR-V clean upgrade: install manifest missing; stale-file cleanup skipped.');
    Exit;
  end;

  Log('RR-V clean upgrade: removing files not present in the new install manifest.');
  RemoveStalePayloadInDirectory(
    ExpandConstant('{app}'),
    ExpandConstant('{app}'),
    Entries
  );
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

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    // 새 파일을 넣기 전의 RR-V.exe 존재 여부를 기억한다. 사용자가 기존 설치와
    // 무관한 다른 폴더를 직접 선택한 경우 그 폴더의 임의 파일을 정리하지 않는다.
    CleanPreviousAppPayload := PreviousInstallDetected and
      FileExists(ExpandConstant('{app}\RR-V.exe'));
    ResetUserDataOnUpgrade := PreviousInstallDetected and
      UpgradeOptionsPage.Values[0];
  end;

  if CurStep = ssPostInstall then
  begin
    RemoveStaleApplicationPayload;
    if ResetUserDataOnUpgrade then
    begin
      Log('RR-V clean upgrade: resetting RR-V user/runtime data by user request.');
      RemoveIntegrationRegistrations;
      RemoveUserData;
    end;
  end;
end;

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
