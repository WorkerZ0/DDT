# DDT — Objetivos

## Stack
- Python 3.12 · CustomTkinter · WebSockets (FastAPI + uvicorn) · SQLite · JWT
- Servidor en VPS (wss/TLS vía Nginx o Caddy) · 20–100 PCs
- Roles: **admin** (ve todo, gestiona usuarios/tiendas) · **tienda** (solo transmite)

## Fase 2 — Backend (`back/`)
- [x] Config (.env) y conexión SQLite
- [x] Modelos: usuarios, dispositivos (PC = usuario tienda + hostname), roles
- [x] Hash de contraseñas (scrypt) + login JWT + rate limit de login
- [x] Middleware auth por rol
- [x] CRUD de usuarios/PCs (solo admin)
- [x] WebSocket `/ws/agent` (recibe frames de las tiendas)
- [x] WebSocket `/ws/viewer` (reparte frames a los admin)
- [x] Ahorro de ancho de banda: miniatura cada ~5 s sin espectadores y alta fps solo si un admin mira esa PC
- [x] Estado online/offline + heartbeat (ping WS 20 s)
- [x] Admin inicial automático + `python -m src.manage reset-password`

## Fase 3 — Desktop (`desktop/`)
- [x] Pantalla de login (CustomTkinter)
- [x] Modo tienda: captura `mss` (todos los monitores unidos) → JPEG → WS, icono en bandeja, reconexión automática
- [x] Modo tienda: arranque con Windows, sesión cifrada DPAPI, cerrar/salir exige clave de admin
- [x] Modo admin: cuadrícula auto-ajustable (se reacomoda según PCs en línea) + buscador + filtro tienda/en línea
- [x] Modo admin: vista en vivo de una PC (F11 pantalla completa)
- [x] Modo admin: gestión de usuarios y quitar PCs offline

## Fase 3b — En vivo fluido + actividad
- [x] En vivo a 1080 nativo con cursor visible (JPEG 8 fps como respaldo)
- [x] Video H.264 por hardware (DXGI + Media Foundation) con detección automática y tope de CPU
- [x] Última actividad (teclado/mouse) por pantalla + ordenar por actividad
- [ ] Probar en PC de tienda real: ¿tiene codificador por hardware? fps y CPU reales
- [ ] Reducir tamaño del instalador (OpenCV/FFmpeg ~66 MB)

## Fase 4 — Integración
- [x] Pruebas end-to-end en local (servidor + agente + visor + UI con capturas)
- [ ] Medir RAM/CPU del agente en PC de tienda real (en dev: ~50 MB RAM con UI)

## Fase 5 — Deploy
- [x] Servidor en VPS con TLS (Caddy CA interna, puerto 9443)
- [x] Instalador Windows del cliente (Python embebido oficial + Inno Setup) → `desktop/installer/Output/DDTMonitor-Setup-1.0.0.exe`
