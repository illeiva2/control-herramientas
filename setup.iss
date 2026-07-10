; Instalador de Control de Herramientas (Inno Setup 6)
; Compilar:  ISCC.exe /DMyAppVersion=x.y.z setup.iss
; - Instala por usuario (sin admin) en %LOCALAPPDATA%\ControlHerramientas,
;   la misma carpeta que usa el auto-update.
; - Registra el desinstalador en "Agregar o quitar programas".
; - NUNCA incluye ni borra la carpeta data\ (la base se crea sola al
;   primer arranque y se conserva al reinstalar/desinstalar).

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

[Setup]
AppId=ControlHerramientas
AppName=Control de Herramientas
AppVersion={#MyAppVersion}
AppPublisher=GRF
DefaultDirName={localappdata}\ControlHerramientas
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=ControlHerramientas-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
MinVersion=6.1sp1
UninstallDisplayIcon={app}\ControlHerramientas.exe
UninstallDisplayName=Control de Herramientas (Pañol)
CloseApplications=no

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "Crear acceso directo en el escritorio"
Name: "inicio"; Description: "Iniciar automáticamente al prender la PC"; Flags: unchecked
Name: "vcredist"; Description: "Instalar componente de Microsoft (solo necesario en Windows 7)"; Flags: unchecked

[Files]
Source: "dist\ControlHerramientas\*"; DestDir: "{app}"; Excludes: "data\*"; \
  Flags: recursesubdirs ignoreversion
Source: "instalador\vc_redist.x86.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Tasks: vcredist

[Icons]
Name: "{autodesktop}\Control de Herramientas"; Filename: "{app}\ControlHerramientas.exe"; \
  WorkingDir: "{app}"; Tasks: escritorio
Name: "{autoprograms}\Control de Herramientas"; Filename: "{app}\ControlHerramientas.exe"; \
  WorkingDir: "{app}"
Name: "{userstartup}\Control de Herramientas"; Filename: "{app}\ControlHerramientas.exe"; \
  WorkingDir: "{app}"; Tasks: inicio

[Run]
Filename: "{tmp}\vc_redist.x86.exe"; Parameters: "/install /passive /norestart"; \
  StatusMsg: "Instalando componente de Microsoft..."; Flags: shellexec waituntilterminated; Tasks: vcredist
Filename: "{app}\ControlHerramientas.exe"; Description: "Abrir Control de Herramientas"; \
  Flags: postinstall nowait skipifsilent

[Code]
procedure CerrarApp();
var
  R: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM ControlHerramientas.exe',
       '', SW_HIDE, ewWaitUntilTerminated, R);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  CerrarApp();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  CerrarApp();
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Db, Respaldo: String;
begin
  // antes de desinstalar, dejar una copia de la base en el escritorio
  if CurUninstallStep = usUninstall then begin
    Db := ExpandConstant('{app}\data\panol.db');
    Respaldo := ExpandConstant('{userdesktop}\panol-respaldo.db');
    if FileExists(Db) then
      FileCopy(Db, Respaldo, False);
  end;
end;
