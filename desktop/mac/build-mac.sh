#!/usr/bin/env bash
# Construye "DDT Monitor.app" para macOS: VISOR DE ADMINISTRADOR (ver pantallas), no agente de tienda.
# Uso:  bash mac/build-mac.sh        (desde la carpeta desktop/)
# Requisitos: macOS 11+, Python 3.10+ (python3), Xcode Command Line Tools.
#
# Firma + notarización (opcional, si hay cuenta Apple Developer). Exporta antes:
#   export DEVELOPER_ID="Developer ID Application: NOMBRE (TEAMID)"
#   export NOTARY_PROFILE="ddt-notary"   # perfil guardado con: xcrun notarytool store-credentials
# Sin esas variables arma la app SIN firmar (se abre con clic derecho -> Abrir).
set -euo pipefail
cd "$(dirname "$0")/.."   # -> desktop/

PYTHON="${PYTHON:-python3}"
VENV=".venv-mac"
APP="dist/DDT Monitor.app"
ZIP="dist/DDT Monitor.zip"

echo "== Entorno virtual =="
"$PYTHON" -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet -r mac/requirements-mac.txt pyinstaller

echo "== Empaquetando =="
rm -rf build dist
pyinstaller --noconfirm --clean mac/ddt_mac.spec

if [ -n "${DEVELOPER_ID:-}" ]; then
  echo "== Firmando (hardened runtime) =="
  codesign --deep --force --options runtime --timestamp \
    --entitlements mac/entitlements.plist --sign "$DEVELOPER_ID" "$APP"
  codesign --verify --strict --verbose=2 "$APP"

  if [ -n "${NOTARY_PROFILE:-}" ]; then
    echo "== Notarizando (espera a Apple) =="
    ditto -c -k --keepParent "$APP" "$ZIP"
    xcrun notarytool submit "$ZIP" --keychain-profile "$NOTARY_PROFILE" --wait
    xcrun stapler staple "$APP"
    rm -f "$ZIP"
    echo "   Notarizada y grapada."
  else
    echo "   (Firmada sin notarizar: NOTARY_PROFILE no definido.)"
  fi
else
  echo "== Sin firmar (DEVELOPER_ID no definido): se abre con clic derecho -> Abrir =="
fi

echo "== Zip para distribuir =="
ditto -c -k --keepParent "$APP" "$ZIP"
echo
echo "Listo:"
echo "  App: $(pwd)/$APP"
echo "  Zip: $(pwd)/$ZIP   (cópialo a la Mac del administrador)"
