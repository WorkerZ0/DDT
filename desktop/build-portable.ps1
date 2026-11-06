# Arma la version PORTABLE de DDT Monitor a partir de lo que ya genero build.ps1
# (runtime + runtime-legacy + app en %LOCALAPPDATA%\DDTBuild). No instala nada, no pide admin:
# se copia una carpeta y se ejecuta "Iniciar DDT Monitor.cmd".
#
# Uso (desde desktop/, despues de haber corrido build.ps1):
#   powershell -ExecutionPolicy Bypass -File build-portable.ps1
# Archivo solo ASCII: PowerShell 5.1 lo lee como ANSI.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = ".\.venv\Scripts\python.exe"
$version = (& $python -c "from shared.version import VERSION; print(VERSION)").Trim()
$buildDir = "$env:LOCALAPPDATA\DDTBuild"

foreach ($d in "runtime", "runtime-legacy", "app") {
    if (-not (Test-Path "$buildDir\$d")) { throw "Falta $buildDir\$d. Corre build.ps1 primero." }
}

$name = "DDTMonitor-Portable-$version"
$out = "installer\Output\$name"
Remove-Item -Recurse -Force $out -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $out | Out-Null

# Los dos runtimes: el lanzador elige segun el Windows destino (modern = 3.12 x64, legacy = 3.8 win32)
Copy-Item -Recurse "$buildDir\runtime" "$out\runtime"
Copy-Item -Recurse "$buildDir\runtime-legacy" "$out\runtime-legacy"
Copy-Item -Recurse "$buildDir\app" "$out\app"

# Marca que activa el modo portable en la app (config.PORTABLE)
New-Item -ItemType File -Force "$out\app\portable.flag" | Out-Null
Set-Content -Encoding ascii "$out\app\portable.flag" "portable"

# Lanzador: se autocopia a %LOCALAPPDATA%\DDTMonitor (ruta estable, sin admin) y abre la app.
# Elige runtime como el instalador (UseModernRuntime): 64 bits y Windows >= 6.3 (8.1/10/11).
$launcher = @'
@echo off
setlocal enabledelayedexpansion
set "SRC=%~dp0"
set "TARGET=%LOCALAPPDATA%\DDTMonitor"

rem Si no corremos ya desde la carpeta estable, copiarnos alla y relanzar (no necesita admin).
if /i not "%SRC%"=="%TARGET%\" (
    echo Instalando DDT Monitor en %TARGET% ...
    robocopy "%SRC%." "%TARGET%" /E /NFL /NDL /NJH /NJS /NP >nul
    start "" "%TARGET%\Iniciar DDT Monitor.cmd"
    exit /b
)

rem Elegir runtime segun arquitectura y version de Windows.
set "ARCH=32"
if /i "%PROCESSOR_ARCHITECTURE%"=="AMD64" set "ARCH=64"
if defined PROCESSOR_ARCHITEW6432 set "ARCH=64"
set "WINVER=6.1"
for /f "tokens=3" %%v in ('reg query "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion" /v CurrentVersion 2^>nul ^| findstr /i CurrentVersion') do set "WINVER=%%v"
for /f "tokens=1,2 delims=." %%a in ("%WINVER%") do (set "MAJ=%%a" & set "MIN=%%b")
if not defined MIN set "MIN=0"
set "RT=runtime-legacy"
if "%ARCH%"=="64" (
    if %MAJ% GEQ 10 set "RT=runtime"
    if %MAJ%==6 if %MIN% GEQ 3 set "RT=runtime"
)

start "" "%TARGET%\%RT%\DDTMonitor.exe" "%TARGET%\app\main.py"
endlocal
'@
Set-Content -Encoding ascii "$out\Iniciar DDT Monitor.cmd" $launcher

# Nota breve para quien despliega
$readme = @"
DDT Monitor $version - version PORTABLE (sin instalador, sin admin)

1. Copia esta carpeta a la PC (USB o red) y ejecuta "Iniciar DDT Monitor.cmd".
   Se copia sola a %LOCALAPPDATA%\DDTMonitor y abre el programa.
2. Inicia sesion con la cuenta de la tienda. Queda en autoarranque al iniciar sesion.

Diferencia con la version instalada: la portable corre como el usuario, no como SYSTEM.
Reabre al iniciar sesion. Para que reabra si la cierran en el Administrador de tareas hay
que activar el watchdog de usuario (lo decide el administrador en el despliegue).
No se auto-actualiza (eso requiere la version instalada, con admin).
"@
Set-Content -Encoding ascii "$out\LEEME.txt" $readme

$zip = "installer\Output\$name.zip"
Remove-Item -Force $zip -ErrorAction SilentlyContinue
Compress-Archive -Path "$out\*" -DestinationPath $zip
Write-Host "Portable listo: $out"
Write-Host "ZIP: $zip"
