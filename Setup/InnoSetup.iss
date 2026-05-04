; 脚本由 Inno Setup 脚本向导生成。
; 有关创建 Inno Setup 脚本文件的详细信息，请参阅帮助文档！

#define MyAppName "SurveyController"
#ifndef MyReleaseTag
  #define MyReleaseTag "v3.1.1"
#endif
#define MyAppVersion MyReleaseTag
#define MyAppPublisher "HUNGRY_M0"
#define MyAppURL "https://surveydoc.hungrym0.top/"
#define MyAppExeName "SurveyController.exe"

[Setup]
; 注意：AppId 的值唯一标识此应用程序。不要在其他应用程序的安装程序中使用相同的 AppId 值。
; (若要生成新的 GUID，请在 IDE 中单击 "工具|生成 GUID"。)
AppId={{56ED8449-9773-4519-832C-0CD98D8D1F50}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
;AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
; "ArchitecturesAllowed=x64compatible" 指定
; 安装程序只能在 x64 和 Windows 11 on Arm 上运行。
ArchitecturesAllowed=x64compatible
; "ArchitecturesInstallIn64BitMode=x64compatible" 要求
; 在 X64 或 Windows 11 on Arm 上以 "64-位模式" 进行安装，
; 这意味着它应该使用本地 64 位 Program Files 目录
; 和注册表的 64 位视图。
ArchitecturesInstallIn64BitMode=x64compatible
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
; 移除以下行以在管理安装模式下运行 (为所有用户安装)。
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
OutputDir=.
OutputBaseFilename=SurveyController_{#MyReleaseTag}_setup
SetupIconFile=..\dist\lib\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=4
WizardStyle=modern
WizardImageFile=.\bg.bmp
WizardSmallImageFile=.\icon.bmp
; 安装前显示的信息文件
InfoBeforeFile=LICENSE\before_install.txt
; 安装后显示的信息文件
InfoAfterFile=LICENSE\after_install.txt

[Languages]
; 直接使用仓库内置语言文件，避免 CI 上 Inno Setup 安装不完整时缺少语言包
Name: "chinesesimplified"; MessagesFile: ".\ChineseSimplified.isl"

[InstallDelete]
; 覆盖安装时先清理旧版残留文件，防止新旧 DLL 路径冲突
Type: filesandordirs; Name: "{app}\PySide6"
Type: filesandordirs; Name: "{app}\shiboken6"
Type: files; Name: "{app}\Qt6*.dll"
Type: files; Name: "{app}\Qt*.pyd"
Type: files; Name: "{app}\pyside6*.dll"
Type: files; Name: "{app}\shiboken6*.dll"

[Files]
; 全量覆盖安装：所有文件始终覆盖，确保环境一致
Source: "..\dist\lib\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; 注意：ignoreversion 会强制覆盖所有文件，不管版本和时间戳

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:ProgramOnTheWeb,{#MyAppName}}"; Filename: "{#MyAppURL}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

