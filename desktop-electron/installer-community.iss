; 老马AI工作台 Community Inno Setup Script
; Open Core · AGPL-3.0 · GitHub 开源免费版
;
; 与 Pro 版关键差异:
;   1. AppId 不同(允许两版本共存安装)
;   2. AppName 带 "Community" 后缀
;   3. Uninstall 只清 Community 用户数据
;   4. 不包含 Hermes Agent / Hermes WebUI (Pro 版专属)
;   5. AI 走本地自配 key(AI_MODE=local_key)
#define MyAppName "老马AI工作台 Community"
#define MyAppPublisher "Laihiujin"
#define MyAppURL "https://github.com/Laihiujin/laoma-ai-workbench"
#define MyAppExeName "LaomaAICommunity.exe"
#define APP_VERSION "1.1.0"

; These will be replaced by the batch script
#define MyAppVersion GetEnv("APP_VERSION")
#define MyAppBuildNum GetEnv("APP_BUILD_NUM")
#define MyAppVersionFull MyAppVersion + "." + MyAppBuildNum
#define SourceDir GetEnv("SOURCE_DIR")
#define OutputDir GetEnv("OUTPUT_DIR")
#if OutputDir == ""
  #define OutputDir GetEnv("OUTPUT_DIR_INNO")
#endif
#define IconFile GetEnv("ICON_FILE")
#define SkipOpt "dontcopy recursesubdirs skipifsourcedoesntexist"
#define PrismenvDir SourceDir + "\resources\prismenv"
#define PrismenvPythonHome PrismenvDir + "\_python"
#define PrismenvSite PrismenvDir + "\Lib\site-packages"
#define PrismBackendDir SourceDir + "\resources\prism_backend"
#define AppPrismenv "{app}\resources\prismenv"
#define AppPrismenvPythonHome "{app}\resources\prismenv\_python"
#define AppPrismenvSite "{app}\resources\prismenv\Lib\site-packages"
#define AppPrismBackend "{app}\resources\prism_backend"
#define ExcludeTests "*\tests\*;*\test\*"

[Setup]
; 唯一 GUID:Community 专属(AppId 与 Pro 不同,允许两版本共存安装)
AppId={{3A7C9D2E-5F4B-4D6E-8B1C-2D3E4F5A6B7C}
AppName={#MyAppName}
AppVersion={#MyAppVersionFull}
AppVerName={#MyAppName} {#MyAppVersion}
VersionInfoVersion={#MyAppVersionFull}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=
OutputDir={#OutputDir}
OutputBaseFilename=老马AI工作台-Community-Setup-v{#MyAppVersionFull}
SetupIconFile={#IconFile}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=yes
CloseApplicationsFilter=LaomaAICommunity.exe

[Languages]
#ifexist "compiler:Languages\ChineseSimplified.isl"
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#endif
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Dirs]
Name: "{app}\resources\prism_backend\data\cookies"
Name: "{app}\resources\prism_backend\cookiesFile"
Name: "{app}\resources\prism_backend\browser_profiles"
Name: "{app}\resources\prism_backend\videoFile"
Name: "{app}\resources\prism_backend\logs"
Name: "{app}\resources\prism_backend\backups"
Name: "{app}\resources\prism_backend\db"
; Community 版不包含 fingerprints 目录(Persona 指纹是 Pro 特性)
Name: "{app}\resources\prism_backend\social-media-copilot-api\chrome-profile"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs overwritereadonly; Excludes: "resources\prism_backend\*;resources\prismenv\*"
Source: "{#PrismenvDir}\*"; DestDir: "{#AppPrismenv}"; Flags: ignoreversion recursesubdirs createallsubdirs overwritereadonly skipifsourcedoesntexist; Excludes: "Lib\site-packages\*"
Source: "{#PrismenvPythonHome}\*"; DestDir: "{#AppPrismenvPythonHome}"; Flags: ignoreversion recursesubdirs createallsubdirs overwritereadonly skipifsourcedoesntexist
Source: "{#PrismenvSite}\*"; DestDir: "{#AppPrismenvSite}"; Flags: ignoreversion recursesubdirs createallsubdirs overwritereadonly skipifsourcedoesntexist; Excludes: "{#ExcludeTests}"
Source: "{#PrismBackendDir}\*"; DestDir: "{#AppPrismBackend}"; Flags: ignoreversion recursesubdirs createallsubdirs overwritereadonly; Excludes: "browser_profiles\*;cookiesFile\*;fingerprints\*"
Source: "{#SourceDir}\resources\prism_backend\social-media-copilot-api\chrome-profile\*"; DestDir: "{app}\resources\prism_backend\social-media-copilot-api\chrome-profile"; Flags: {#SkipOpt}
Source: "{#SourceDir}\resources\prism_backend\data\cookies\*"; DestDir: "{app}\resources\prism_backend\data\cookies"; Flags: {#SkipOpt}
Source: "{#SourceDir}\resources\prism_backend\cookiesFile\*"; DestDir: "{app}\resources\prism_backend\cookiesFile"; Flags: {#SkipOpt}
Source: "{#SourceDir}\resources\prism_backend\browser_profiles\*"; DestDir: "{app}\resources\prism_backend\browser_profiles"; Flags: {#SkipOpt}
Source: "{#SourceDir}\resources\prism_backend\videoFile\*"; DestDir: "{app}\resources\prism_backend\videoFile"; Flags: {#SkipOpt}
Source: "{#SourceDir}\resources\prism_backend\logs\*"; DestDir: "{app}\resources\prism_backend\logs"; Flags: {#SkipOpt}
Source: "{#SourceDir}\resources\prism_backend\backups\*"; DestDir: "{app}\resources\prism_backend\backups"; Flags: {#SkipOpt}
Source: "{#SourceDir}\resources\prism_backend\__pycache__\*"; DestDir: "{app}\resources\prism_backend\__pycache__"; Flags: {#SkipOpt}
Source: "{#SourceDir}\resources\prism_backend\*.pyc"; DestDir: "{app}\resources\prism_backend"; Flags: {#SkipOpt}
Source: "{#SourceDir}\resources\prism_backend\*.pyo"; DestDir: "{app}\resources\prism_backend"; Flags: {#SkipOpt}
Source: "{#SourceDir}\resources\prism_backend\db\*.db*"; DestDir: "{app}\resources\prism_backend\db"; Flags: {#SkipOpt}
Source: "{#SourceDir}\resources\prism_backend\db\*.sqlite*"; DestDir: "{app}\resources\prism_backend\db"; Flags: {#SkipOpt}
Source: "{#SourceDir}\resources\prism_backend\db\frontend_accounts_snapshot.json"; DestDir: "{app}\resources\prism_backend\db"; Flags: dontcopy skipifsourcedoesntexist

; Community 版不打包 Hermes Agent / Hermes WebUI (Pro 版专属付费内核)
; Pro 版的 tools/hermes-agent、tools/hermes-webui 在此被显式排除
; (通过上面的 SourceDir 排除模式:Excludes 仅影响 prismenv/prism_backend)
; 由于 electron-builder 侧已通过 package.community.json 的 extraResources
; 未包含 hermes-agent / hermes-webui 目录,这里无需再排除。

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
; Community 版 AppData 目录与 Pro 版独立(通过 AppId 隔离)
Type: filesandordirs; Name: "{userappdata}\老马AI工作台 Community\data"; Check: ShouldDeleteUserData
Type: filesandordirs; Name: "{localappdata}\老马AI工作台 Community\data"; Check: ShouldDeleteUserData

[Code]
var
  DeleteUserDataCheckBox: TNewCheckBox;
  DeleteUserData: Boolean;
  ResultCode: Integer;

procedure ForceCloseRunningApp();
begin
  Exec('taskkill', '/F /IM LaomaAICommunity.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function InitializeSetup(): Boolean;
begin
  ForceCloseRunningApp();
  Result := True;
end;

procedure InitializeUninstallProgressForm();
begin
  DeleteUserData := False;
  DeleteUserDataCheckBox := TNewCheckBox.Create(UninstallProgressForm);
  DeleteUserDataCheckBox.Parent := UninstallProgressForm.StatusLabel.Parent;
  DeleteUserDataCheckBox.Caption := 'Remove user data (AppData)';
  DeleteUserDataCheckBox.Left := UninstallProgressForm.StatusLabel.Left;
  DeleteUserDataCheckBox.Top := UninstallProgressForm.StatusLabel.Top + UninstallProgressForm.StatusLabel.Height + ScaleY(8);
  DeleteUserDataCheckBox.Width := UninstallProgressForm.StatusLabel.Width;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usUninstall) and (DeleteUserDataCheckBox <> nil) then
    DeleteUserData := DeleteUserDataCheckBox.Checked;
end;

function ShouldDeleteUserData(): Boolean;
begin
  Result := DeleteUserData;
end;
