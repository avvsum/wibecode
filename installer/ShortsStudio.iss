#ifndef RepoRoot
  #define RepoRoot ".."
#endif
#ifndef SetupAppId
  #define SetupAppId "ShortsStudio"
#endif
#ifndef SetupAppName
  #define SetupAppName "Shorts Studio"
#endif
#ifndef SetupOutputName
  #define SetupOutputName "ShortsStudio-Setup"
#endif
#ifndef SetupOutputDir
  #define SetupOutputDir RepoRoot + "\dist\setup"
#endif
#ifndef SetupDefaultDir
  #define SetupDefaultDir "{localappdata}\Programs\ShortsStudio"
#endif

[Setup]
AppId={#SetupAppId}
AppName={#SetupAppName}
AppVersion=2026.10.25
AppPublisher=Shorts Studio
DefaultDirName={#SetupDefaultDir}
DefaultGroupName={#SetupAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
OutputDir={#SetupOutputDir}
OutputBaseFilename={#SetupOutputName}
Compression=lzma2/fast
SolidCompression=yes
DiskSpanning=yes
DiskSliceSize=max
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\ShortsStudio.exe
SetupLogging=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Types]
Name: "full"; Description: "Приложение и локальная озвучка"
Name: "compact"; Description: "Только приложение"
Name: "custom"; Description: "Выбор компонентов"; Flags: iscustom

[Components]
Name: "main"; Description: "Shorts Studio, персонажи, музыка и FFmpeg"; Types: full compact custom; Flags: fixed
Name: "voice"; Description: "Локальная озвучка Chatterbox с готовой моделью"; Types: full

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"

[Files]
Source: "{#RepoRoot}\dist\ShortsStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main
Source: "{#RepoRoot}\build\voice-runtime\*"; DestDir: "{app}\voice-runtime"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: voice
Source: "{#RepoRoot}\build\voice-models\*"; DestDir: "{app}\voice-models"; Excludes: "*.part,*.incomplete"; Flags: ignoreversion nocompression; Components: voice

[Icons]
Name: "{group}\{#SetupAppName}"; Filename: "{app}\ShortsStudio.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\{#SetupAppName}"; Filename: "{app}\ShortsStudio.exe"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{group}\Удалить Shorts Studio"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\ShortsStudio.exe"; Description: "Запустить Shorts Studio"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\voice-runtime"
Type: filesandordirs; Name: "{app}\voice-models"
