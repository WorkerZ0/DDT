# Arma DDT Monitor con el Python embebido oficial (firmado por la PSF) y genera el instalador.
# No se compila ningun exe propio: ESET borraba el exe de Nuitka por heuristica.
# Dos runtimes en un solo instalador (Inno elige al instalar):
#   runtime         Python 3.12 x64 + video H.264       -> Windows 8.1 / 10 / 11 de 64 bits
#   runtime-legacy  Python 3.8 win32, solo JPEG (minimo) -> Windows 7 / 8 y cualquier Windows de 32 bits
# Uso (desde desktop/):  powershell -ExecutionPolicy Bypass -File build.ps1
# Archivo solo ASCII: PowerShell 5.1 lo lee como ANSI.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = ".\.venv\Scripts\python.exe"
$version = (& $python -c "from shared.version import VERSION; print(VERSION)").Trim()
$buildDir = "$env:LOCALAPPDATA\DDTBuild"
$cache = "$buildDir\cache"
$app = "$buildDir\app"
$rcedit = "C:\Tools\rcedit-x64.exe"
if (-not (Test-Path $rcedit)) { throw "Falta rcedit en $rcedit" }
$icon = ".\assets\ddt.ico"


$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "No se encontro Inno Setup 6 (ISCC.exe)" }

New-Item -ItemType Directory -Force $cache | Out-Null

function Get-Cached($url, $file) {
    $path = "$cache\$file"
    if (-not (Test-Path $path)) { Invoke-WebRequest $url -OutFile $path }
    return $path
}

# Pone nombre e icono "DDT Monitor" a un exe del runtime. Rompe la firma de Python (queda sin firma).
function Set-Brand($path) {
    & $rcedit $path `
        --set-version-string FileDescription "DDT Monitor" `
        --set-version-string ProductName "DDT Monitor" `
        --set-version-string CompanyName "Grupo Distefano" `
        --set-file-version $version --set-product-version $version `
        --set-icon $icon
    if ($LASTEXITCODE -ne 0) { throw "rcedit falló en $path" }
}


# Python embebido + rutas de busqueda + lanzador (pythonw renombrado: conserva la firma de la PSF)
function New-Runtime($dir, $pyVersion, $arch) {
    $tag = ($pyVersion -split "\.")[0..1] -join ""
    Remove-Item -Recurse -Force $dir -ErrorAction SilentlyContinue
    Expand-Archive (Get-Cached "https://www.python.org/ftp/python/$pyVersion/python-$pyVersion-embed-$arch.zip" "python-$pyVersion-embed-$arch.zip") $dir
    @("python$tag.zip", ".", "Lib", "Lib\site-packages", "..\app") | Set-Content -Encoding ascii "$dir\python$tag._pth"
        Copy-Item "$dir\pythonw.exe" "$dir\DDTMonitor.exe"
        Set-Brand "$dir\DDTMonitor.exe"   # la app
        Set-Brand "$dir\pythonw.exe"      # lo abre el vigilante
        Set-Brand "$dir\python.exe"       # lo abre el actualizador

}

# tkinter no viene en el embebido
function Add-Tk($dir, $src) {
    foreach ($f in "_tkinter.pyd", "tcl86t.dll", "tk86t.dll", "zlib1.dll") {
        if (Test-Path "$src\DLLs\$f") { Copy-Item "$src\DLLs\$f" $dir }
    }
    Copy-Item -Recurse "$src\Lib\tkinter" "$dir\Lib\tkinter"
    Copy-Item -Recurse "$src\tcl" "$dir\tcl"
    Remove-Item -Recurse -Force "$dir\Lib\tkinter\test" -ErrorAction SilentlyContinue
}

function Invoke-Pip($dir, [string[]]$pipArgs) {
    & $python -m pip install --quiet --no-compile --target "$dir\Lib\site-packages" @pipArgs
    if ($LASTEXITCODE -ne 0) { throw "pip fallo: $pipArgs" }
}

# 1. Runtime moderno: tkinter del Python base del venv (misma version)
$runtime = "$buildDir\runtime"
New-Runtime $runtime "3.12.10" "amd64"
Add-Tk $runtime (& $python -c "import sys; print(sys.base_prefix)").Trim()
Invoke-Pip $runtime @("-r", "requirements.txt")
# dxcam sin dependencias: pide opencv-python, que choca con opencv-python-headless
Invoke-Pip $runtime @("--no-deps", "dxcam==0.0.5")

# 2. Runtime legacy: tkinter sale del MSI oficial (instalacion administrativa = solo extrae, no instala nada)
$legacy = "$buildDir\runtime-legacy"
$legacyPy = "3.8.10"
New-Runtime $legacy $legacyPy "win32"
$tkSrc = "$cache\tcltk-$legacyPy-win32"
if (-not (Test-Path "$tkSrc\DLLs\_tkinter.pyd")) {
    $msi = Get-Cached "https://www.python.org/ftp/python/$legacyPy/win32/tcltk.msi" "tcltk-$legacyPy-win32.msi"
    $p = Start-Process msiexec.exe -ArgumentList "/a `"$msi`" /qn TARGETDIR=`"$tkSrc`"" -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "no se pudo extraer tcltk.msi ($($p.ExitCode))" }
}
Add-Tk $legacy $tkSrc
Invoke-Pip $legacy @("--only-binary=:all:", "--platform", "win32", "--python-version", "3.8", "--implementation", "cp", "-r", "requirements-legacy.txt")

foreach ($rt in $runtime, $legacy) { Remove-Item "$rt\Lib\site-packages\*.whl" -ErrorAction SilentlyContinue }

# 3. Codigo de la app (compartido por los dos runtimes)
Remove-Item -Recurse -Force $app -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $app | Out-Null
Copy-Item main.py, updater.py $app
foreach ($d in "shared", "services", "components", "pages", "assets") { Copy-Item -Recurse $d "$app\$d" }
Get-ChildItem $app -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force

# 4. Precompilar con cada runtime (en Program Files el usuario no puede escribir __pycache__).
#    Los .pyc llevan la version en el nombre (cpython-38 / cpython-312): conviven en la misma carpeta.
#    Compilar con 3.8 tambien valida que el codigo no use sintaxis nueva.
foreach ($rt in $runtime, $legacy) {
    & "$rt\python.exe" -m compileall -q $app "$rt\Lib"
    if ($LASTEXITCODE -ne 0) { throw "compileall fallo en $rt" }
}

# 5. Instalador
& $iscc "/DAppVersion=$version" "/DBuildDir=$buildDir" installer\ddt.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup fallo" }
Write-Host "Instalador listo en installer\Output"

# 6. Actualizacion automatica: latest.json firmado (llave privada fuera del repo, ver tools\release.py)
& $python tools\release.py sign "installer\Output\DDTMonitor-Setup-$version.exe"
if ($LASTEXITCODE -ne 0) { Write-Warning "Sin firma: este build no se puede publicar como actualizacion" }
else { Write-Host "Subir installer\Output\updates\* a /opt/ddt/updates del servidor" }
