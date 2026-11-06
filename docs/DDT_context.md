# DDT — Contexto

## Objetivo
App desktop de vigilancia de pantallas para tiendas (cajeros/vendedores).
- Login con roles: credencial **tienda** → solo transmite pantalla en vivo 24/7; credencial **supervisor/admin** → ve pantallas de otras PCs.
- Ligera para PCs de tienda.

## Decisiones
- Lenguaje: Python 3.12 (3.14 instalado pero peor soporte de wheels/Nuitka). Default `python` de la PC es 2.7 → usar `py -3.12`.
- UI: CustomTkinter (una sola app desktop; el rol del login decide modo agente o visor).
- Transporte: WebSockets (frames JPEG, baja fps).
- Descartado: Java (más RAM), web (usuario pidió nativo desktop).

## Arquitectura
- `back/` servidor relay WebSocket + auth.
- `desktop/` app CustomTkinter (agente + visor).
- `docs/` contexto y objetivos.

## Estado al 29/10/2026 — Fase 2 (backend) terminada y desplegada
- VPS `45.79.170.84` (Ubuntu 24.04, compartido con ~50 contenedores). Stack en `/opt/ddt`, compose `name: ddt`.
  - `ddt-api` (FastAPI + uvicorn, 1 worker, SQLite en volumen `ddt_data`) → solo red interna.
  - `ddt-caddy` (TLS `tls internal`, sin dominio) → `https://45.79.170.84:9443` / `wss://…:9443`.
  - Puerto 8443 ya estaba ocupado; se usó 9443.
- El cliente confía SOLO en la CA de Caddy: `desktop/shared/ddt_ca.crt` (si se borra el volumen `ddt_caddy_data`, la CA cambia y hay que reemplazar el .crt en el cliente).
- Admin inicial: `admin` (clave en `back/.env`). Rescate: `docker exec ddt-api python -m src.manage reset-password admin <clave>`.
- Deploy: tar de `back/` → `/opt/ddt` → `docker compose build && docker compose up -d` (build en server: imagen chica).

### API
- `POST /api/auth/login` {username,password} → {token,user}. Token admin 12 h; token tienda 365 d (se revoca al cambiar clave/rol/desactivar vía `token_version`).
- `GET /api/auth/me` · `GET|POST /api/users` · `PATCH|DELETE /api/users/{id}` · `GET /api/devices` · `DELETE /api/devices/{id}` (solo admin).
- No se puede quitar/borrar el último admin ni borrarse a sí mismo.

### Protocolo WebSocket
- Primer mensaje (texto): `{"type":"auth","token":…}` (+ `"hostname"` en agente). Cierres: 4400 auth mal, 4401 sesión inválida/revocada, 4403 rol, 4409 reemplazado, 4410 dispositivo borrado.
- `/ws/agent` (rol tienda): recibe `ready{device_id}` y `config{live, thumb_interval, thumb_width, thumb_quality, live_fps, live_width, live_quality}`. Envía binario `[1 byte tipo][JPEG]` (0 = miniatura cada thumb_interval siempre; 1 = vivo solo si `live`).
- `/ws/viewer` (rol admin): recibe `ready`, `devices{devices:[{id,hostname,user_id,username,display_name,last_seen,online,live,watchers}]}` y binario `[tipo][device_id u32 BE][JPEG]`. Envía `{"type":"watch","device_id":N}` / `{"type":"unwatch"}`.
- Visor con cola "último gana" (descarta frames viejos si va lento).

### Pendiente
- Fase 3: cliente desktop CustomTkinter (login → modo tienda o admin) + instalador.

## Estado al 29/10/2026 — Fase 3 (cliente desktop)
- `desktop/` Python 3.12 venv `.venv` · deps en `requirements.txt` (customtkinter, mss, Pillow, websockets, pystray).
- Una sola app (`main.py`): el rol del login decide el modo.
  - **Tienda**: sesión guardada cifrada con DPAPI en `%APPDATA%\DDTMonitor\session.dat`, autoarranque `HKCU\...\Run\DDTMonitor --autostart` (arranca oculta), icono de bandeja con estado. "Cerrar sesión" y "Salir" piden usuario+clave de un admin (valida con `/api/auth/login`). La X solo oculta. Instancia única (mutex).
  - **Admin**: no guarda sesión (token 12 h). Pestañas Pantallas / Usuarios. Grilla estilo videollamada (`compute_layout` en `pages/admin.py`) que se reacomoda según cuántas PCs son visibles; mínimo 250 px por tile y luego scroll. Filtros: buscar, tienda, "Solo en línea". Clic → ventana en vivo (F11); clic derecho → quitar PC offline.
- Agente: un hilo de captura dedicado (mss no es thread-safe); captura monitores[0] (todos unidos); recrea mss cada 60 s para detectar monitores nuevos.
- Logs del cliente: `%APPDATA%\DDTMonitor\ddt.log`.
- Desarrollo contra backend local: `DDT_SERVER=http://127.0.0.1:8765`.
- Build: `desktop/build.ps1` → Python 3.12.10 embebido oficial (firmado PSF) + tkinter/tcl/zlib1 copiados del Python base + deps en `runtime\Lib\site-packages` + código en `app\`, precompilado; lanzador `runtime\DDTMonitor.exe` (= pythonw renombrado, conserva la firma). Staging en `%LOCALAPPDATA%\DDTBuild`. Inno Setup (`installer/ddt.iss`, requiere admin, limpia autoarranque y mata el proceso al desinstalar) → `installer/Output/DDTMonitor-Setup-<ver>.exe` (~16 MB).
- **Se descartó Nuitka**: ESET (antivirus de la empresa) detectaba y borraba el exe compilado. Con el pythonw firmado no lo detecta.
- Limitación conocida: un cajero puede matar el proceso con el Administrador de tareas; el admin lo ve como PC desconectada.


## Estado al 29/10/2026 — En vivo 1080 / video H.264 + actividad (v1.1.0)
- **En vivo JPEG (fallback)**: 1080 nativo (LIVE_WIDTH=3840, LIVE_HEIGHT=1080), 8 fps, calidad 50, solo envía si el JPEG cambió (refresco cada 2 s), cursor dibujado (Windows no lo captura).
- **En vivo video H.264** (PCs con codificador por hardware): captura DXGI propia sobre piezas de dxcam (`services/video.py`: dxcam se cuelga en bucle infinito si la PC se bloquea/UAC → manejo propio con reintento cada 2 s), lienzo único reutilizado (1 copia GPU→RAM), BGRA→NV12 con OpenCV (cv2.merge), codificador `h264_mf` de Media Foundation con `hw_encoding=1` (falla si no hay HW → JPEG), CBR 2,5 Mbps por monitor 1080p, keyframe cada 2 s y a pedido.
  - `sys.coinit_flags = 0`: Media Foundation no funciona en COM STA (lo que comtypes/dxcam pone por defecto).
  - El codificador entrega con 2 frames de retraso → tras cada cambio se reenvía el último frame 2 veces para "empujarlo".
  - Solo codifica cuando DXGI reporta cambio (imagen o puntero).
  - Tope de CPU: el agente baja fps solo si capturar+codificar supera 40 % de un núcleo (`MAX_CPU_SHARE`).
  - Medido en PC dev (i7, 2 monitores 3840x1080): ~18 fps al 35 %; con 1 monitor ~25 fps ~30 %.
  - `probe()` al iniciar el agente decide video o JPEG; se informa al server en el auth (`"video": bool`). Kill-switch server: `VIDEO_ENABLED=0`.
- **Protocolo nuevo**: binario tipo 2 = H.264 delta, 3 = keyframe. Server mantiene cola ordenada por visor (máx 60 paquetes; si se atrasa vacía y pide keyframe). Server→agente `{"type":"keyframe"}` cuando entra un visor nuevo o se descartó video.
- **Actividad**: agente manda `{"type":"activity","idle":s}` cada miniatura (5 s) con `GetLastInputInfo` (teclado/mouse reales; SetCursorPos por software no cuenta). Server reenvía a visores y lo incluye en `devices` (`idle`). Tarjeta muestra "activo ahora / activo hace N s / inactivo N min (ámbar ≥5 min) / inactivo N h". Orden "Tienda | Actividad" (por actividad reordena cada 10 s).
- Visor: decodifica H.264 con PyAV y escala al tamaño de la ventana (`display_box`); ventana en vivo con PhotoImage reutilizado (paste) y contador "Video H.264 · N fps" / "JPEG".
- Deps nuevas cliente: av 14.0.1, numpy 2.1.3, opencv-python-headless 4.10.0.84, comtypes 1.4.8, dxcam 0.0.5 (`--no-deps`). Instalador ~66 MB.
