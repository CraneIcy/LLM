; CAgent 安装包脚本
; 用 Inno Setup 编译

[Setup]
; 应用基本信息
AppName=CAgent
AppVersion=1.0
AppPublisher=CraneIcy
AppPublisherURL=https://github.com/CraneIcy/LLM

; 安装目录
DefaultDirName={autopf}\CAgent
DefaultGroupName=CAgent

; 安装包输出
OutputDir=installer_output
OutputBaseFilename=CAgent_Setup_v1.0

; 权限
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; 图标（可选）
; SetupIconFile=icon.ico

; 压缩
Compression=lzma2
SolidCompression=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"

[Files]
; 打包整个 CAgent 目录（exe + _internal + 配置文件）
Source: "D:\LLM\Agent\CAgent\dist\CAgent\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
; 开始菜单快捷方式
Name: "{group}\CAgent"; Filename: "{app}\CAgent.exe"
Name: "{group}\卸载 CAgent"; Filename: "{uninstallexe}"

; 桌面快捷方式（可选任务）
Name: "{autodesktop}\CAgent"; Filename: "{app}\CAgent.exe"; Tasks: desktopicon

[Run]
; 安装完成后可选启动
Filename: "{app}\CAgent.exe"; Description: "立即启动 CAgent"; Flags: nowait postinstall skipifsilent
