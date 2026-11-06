; Instalador de DDT Monitor. Lo invoca build.ps1 (Python embebido oficial + codigo de la app).
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef BuildDir
  #define BuildDir "..\build"
#endif
#define AppName "DDT Monitor"
#define AppExe "DDTMonitor.exe"

[Setup]
AppId={{6C1F3E2A-8D4B-4F7E-9A51-DD7A0C2B1E10}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Grupo Distefano
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Instalar/desinstalar requiere admin: un cajero sin permisos no puede quitarlo
PrivilegesRequired=admin
; Sin ArchitecturesAllowed: tambien instala en Windows de 32 bits (runtime legacy)
ArchitecturesInstallIn64BitMode=x64compatible
; Windows 7 SP1 en adelante
MinVersion=6.1sp1
OutputDir=Output
OutputBaseFilename=DDTMonitor-Setup-{#AppVersion}
SetupIconFile=..\assets\ddt.ico
UninstallDisplayIcon={app}\app\assets\ddt.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; Flags: unchecked

[InstallDelete]
; Actualizaciones limpias: no dejar modulos viejos
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\runtime"

[Files]
; Un solo runtime se instala en {app}\runtime: el moderno (Python 3.12 x64, video H.264) o el legacy
; (Python 3.8 win32, solo JPEG) para Windows 7 / 8 / 32 bits. Asi los accesos directos no cambian.
Source: "{#BuildDir}\runtime\*"; DestDir: "{app}\runtime"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: UseModernRuntime
Source: "{#BuildDir}\runtime-legacy\*"; DestDir: "{app}\runtime"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: not UseModernRuntime
Source: "{#BuildDir}\app\*"; DestDir: "{app}\app"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\runtime\{#AppExe}"; Parameters: """{app}\app\main.py"""; WorkingDir: "{app}\app"; IconFilename: "{app}\app\assets\ddt.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\runtime\{#AppExe}"; Parameters: """{app}\app\main.py"""; WorkingDir: "{app}\app"; IconFilename: "{app}\app\assets\ddt.ico"; Tasks: desktopicon

[Run]
; Tarea programada (SYSTEM) que busca e instala actualizaciones firmadas
Filename: "{app}\runtime\python.exe"; Parameters: """{app}\app\updater.py"" --install-task"; WorkingDir: "{app}\app"; Flags: runhidden
; Actualizacion automatica (silenciosa): reabrir la app en las sesiones donde estaba abierta
Filename: "{app}\runtime\python.exe"; Parameters: """{app}\app\updater.py"" --relaunch"; WorkingDir: "{app}\app"; Flags: runhidden; Check: WizardSilent
; Refrescar la cache de iconos del shell para que el icono nuevo se vea sin reiniciar (no reinicia explorer)
Filename: "{sys}\ie4uinit.exe"; Parameters: "-show"; Flags: runhidden
Filename: "{sys}\ie4uinit.exe"; Parameters: "-ClearIconCache"; Flags: runhidden
Filename: "{app}\runtime\{#AppExe}"; Parameters: """{app}\app\main.py"""; WorkingDir: "{app}\app"; Description: "Abrir {#AppName}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallRun]
Filename: "{app}\runtime\python.exe"; Parameters: """{app}\app\updater.py"" --remove-task"; WorkingDir: "{app}\app"; Flags: runhidden; RunOnceId: "RemoveTask"
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#AppExe}"; Flags: runhidden; RunOnceId: "KillApp"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Registry]
; El autoarranque lo crea la app al iniciar sesion de tienda; aqui solo se limpia al desinstalar
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "DDTMonitor"; Flags: uninsdeletevalue dontcreatekey

[Code]
function GetModuleHandle(lpModuleName: String): Cardinal; external 'GetModuleHandleW@kernel32.dll stdcall';
function GetProcAddress(hModule: Cardinal; lpProcName: AnsiString): Cardinal; external 'GetProcAddress@kernel32.dll stdcall';

// Python 3.12 pide Windows 8.1+ de 64 bits; el resto usa el runtime legacy
function UseModernRuntime: Boolean;
var
  V: TWindowsVersion;
begin
  GetWindowsVersionEx(V);
  Result := Is64BitInstallMode and ((V.Major > 6) or ((V.Major = 6) and (V.Minor >= 3)));
end;

// Python 3.8 en Windows 7 necesita el Universal C Runtime (KB2999226) y KB2533623
function InitializeSetup: Boolean;
var
  Missing: String;
begin
  Result := True;
  if UseModernRuntime then
    Exit;
  if not FileExists(ExpandConstant('{syswow64}\ucrtbase.dll')) then
    Missing := Missing + #13#10 + '- KB2999226 (Universal C Runtime)';
  if GetProcAddress(GetModuleHandle('kernel32.dll'), 'AddDllDirectory') = 0 then
    Missing := Missing + #13#10 + '- KB2533623';
  if Missing <> '' then
  begin
    MsgBox('A este Windows le faltan actualizaciones necesarias para {#AppName}:' + Missing + #13#10#13#10 +
           'Instalalas con Windows Update (o descargalas del Catalogo de Microsoft Update) y vuelve a ejecutar el instalador.',
           mbCriticalError, MB_OK);
    Result := False;
  end;
end;
