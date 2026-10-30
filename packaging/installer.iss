; Inno Setup 6 script — compile with:  iscc packaging\installer.iss
#define AppName "HEC-RAS SUFI-2 Calibrator"
#define AppVersion "1.0.0"
#define AppPublisher "University of West London"
#define AppExe "HECRAS-SUFI2.exe"

[Setup]
AppId={{6C1E2B57-3F0E-4E7A-9C61-8F2B7B1D5A21}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://github.com/Saeid-Najjarghabel/HECRAS-SUFI2
DefaultDirName={autopf}\HECRAS-SUFI2
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist\installer
OutputBaseFilename=HECRAS-SUFI2-Setup-{#AppVersion}
SetupIconFile=..\sufi2_gui\resources\app_icon.ico
UninstallDisplayIcon={app}\{#AppExe}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#ifexist "build_assets\wizard_small.bmp"
WizardSmallImageFile=build_assets\wizard_small.bmp,build_assets\wizard_small@2x.bmp
WizardImageFile=build_assets\wizard_large.bmp,build_assets\wizard_large@2x.bmp
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\HECRAS-SUFI2\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
