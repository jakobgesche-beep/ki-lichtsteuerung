; Installer für Windows (Inno Setup 6). Aufruf: iscc /DVERSION=1.2.3 packaging\lichtsteuerung.iss
; Installiert nur für den angemeldeten Benutzer, ohne Administrator-Rechte, nach
; %LOCALAPPDATA%\Programs\Lichtsteuerung. Die Show-Daten liegen getrennt in %APPDATA%\Lichtsteuerung
; und bleiben bei Updates und beim Deinstallieren erhalten.
#ifndef VERSION
  #define VERSION "0.0.0"
#endif

[Setup]
AppId={{6F3B9C2E-8B1D-4C55-9E57-4C0E2A9B7D11}
AppName=Lichtsteuerung
AppVersion={#VERSION}
AppVerName=Lichtsteuerung {#VERSION}
AppPublisher=Technik-AG
DefaultDirName={localappdata}\Programs\Lichtsteuerung
DefaultGroupName=Lichtsteuerung
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Lichtsteuerung-Setup
SetupIconFile=symbol.ico
UninstallDisplayIcon={app}\Lichtsteuerung.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktop"; Description: "Symbol auf dem Desktop"; GroupDescription: "Zusätzlich:"

[InstallDelete]
; Alte Programmdateien weg, damit nichts von einer früheren Version übrig bleibt
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\Lichtsteuerung\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Lichtsteuerung"; Filename: "{app}\Lichtsteuerung.exe"
Name: "{userdesktop}\Lichtsteuerung"; Filename: "{app}\Lichtsteuerung.exe"; Tasks: desktop

[Run]
Filename: "{app}\Lichtsteuerung.exe"; Description: "Lichtsteuerung jetzt starten"; Flags: nowait postinstall skipifsilent
