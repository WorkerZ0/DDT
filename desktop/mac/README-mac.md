# DDT Monitor — versión macOS (VISOR DE ADMINISTRADOR)

La app para Mac es **solo para administradores**: sirve para **ver las pantallas** de las tiendas, no
para ser monitoreada. En Mac el modo tienda está deshabilitado (si entras con una cuenta de tienda,
avisa y no hace nada). El backend es el mismo servidor (`45.79.170.84:9443`).

Por ser solo visor:
- **No** pide permiso de Grabación de Pantalla (no captura la Mac).
- **No** se instala en autoarranque ni deja nada corriendo de fondo: la abres cuando quieres mirar.
- Decodifica el **video H.264** que mandan las PCs Windows (incluye PyAV).

## 1. Construir (en una Mac)
Requisitos: macOS 11+, `python3` (3.10+), Xcode Command Line Tools (`xcode-select --install`).

```bash
cd desktop
bash mac/build-mac.sh
```
Genera `desktop/dist/DDT Monitor.app` y `desktop/dist/DDT Monitor.zip` (para repartir).

### Firmar y notarizar (hay cuenta Apple Developer)
Una sola vez, guarda las credenciales de notarización:
```bash
xcrun notarytool store-credentials "ddt-notary" \
  --apple-id "TU_APPLE_ID" --team-id "TEAMID" --password "APP_SPECIFIC_PASSWORD"
```
Luego exporta y construye:
```bash
export DEVELOPER_ID="Developer ID Application: NOMBRE (TEAMID)"   # tu certificado en el llavero
export NOTARY_PROFILE="ddt-notary"
bash mac/build-mac.sh
```
El script firma con hardened runtime (`mac/entitlements.plist`), notariza y **grapa** el ticket.
Así la app abre con doble clic en cualquier Mac, sin advertencias de Gatekeeper.

## 2. Instalar en la Mac del administrador
1. Copia **DDT Monitor.app** a `/Applications`.
2. Si está **notarizada**: doble clic y listo.
   Si la armaste **sin firmar**: la primera vez **clic derecho → Abrir → Abrir**.
3. Inicia sesión con la **cuenta de administrador** → se abre el panel con las pantallas de las tiendas.

## 3. Límites conocidos
- No se auto-actualiza: para una versión nueva se reinstala el `.app`.
- Es la vista de administrador; la configuración de tiendas se sigue haciendo en las PCs Windows.
