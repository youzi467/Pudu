; 谱渡 Pudu · Inno Setup 安装脚本
; -----------------------------------
; 用法（需先安装 Inno Setup 6.x，并已完成 PyInstaller onedir 构建）：
;   ISCC.exe packaging\pudu_setup.iss
; 产出：build\_pkg\dist\PuduSetup-<ver>-win64.exe（安装包，per-user 免 UAC）
;
; 说明：
;   * PrivilegesRequired=lowest → 安装到 %LOCALAPPDATA%\Programs\Pudu，无需管理员。
;   * 绿色版同名产物为 build\_pkg\dist\pudu-desktop-win64.zip（二者内容一致）。
;   * 文件关联（.pdf/.png/.musicxml）暂不做——桌面壳尚不支持 argv 传文件打开。

#define MyAppName "谱渡 Pudu · 五线谱 ⇄ 简谱"
#define MyAppVersion "0.9.0"
#define MyAppExeName "pudu_desktop.exe"
#define MyAppPublisher "朱禹泽"
#define MyAppURL "https://github.com/"
#define DistDir "..\dist\pudu_desktop"

[Setup]
AppId={{B3F7C21E-8A5D-4A61-9E0C-2D8F5A1B7C04}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\Pudu
DefaultGroupName=谱渡 Pudu
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\build\_pkg\dist
OutputBaseFilename=PuduSetup-{#MyAppVersion}-win64
SetupIconFile=..\favicon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
ChangesEnvironment=no
; 单文件大包（含 Audiveris ~160MB）用 lzma2 慢速压缩省体积；赶发布可改 normal

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; 整个 onedir 目录原样入包（_internal 全量：冻结模块 + 数据 + Pudu.exe + AV + runtime）
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\谱渡 Pudu"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\谱渡 Pudu"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行谱渡 Pudu"; Flags: nowait postinstall skipifsilent
