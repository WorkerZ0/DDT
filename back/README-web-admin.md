# Panel web de admin tras el proxy central (radio.distefanoshop.com:9444)

Objetivo: abrir el panel en `https://radio.distefanoshop.com:9444` con **certificado válido**
(sin "No seguro", sin instalar CA en cada Mac), reusando el proxy central que ya sirve ese dominio.

Arquitectura:

    navegador admin ──TLS──> proxy central (80/443, ya tiene el cert de radio.distefanoshop.com)
                             listener :9444 ──HTTP──> ddt-api:8000  (web + /ws/viewer + /api)

Los AGENTES de tienda no cambian: siguen en `https://45.79.170.84:9443` con la CA interna.
El panel pasa directo por `ddt-api` (FastAPI ya sirve la web, el WS del visor y la API).

## 1. Desplegar DDT (incluye la web)
Ejecuta el deploy habitual (`deploy/deploy.py`, con la clave de root en la variable de entorno
`DDT_ROOT_PW`). Reconstruye `ddt-api` con el panel (`/app`). Tras esto, `ddt-api` responde la web en
el puerto 8000 (interno).

## 2. Que el proxy central pueda ver a `ddt-api` (misma red de Docker)
Averigua la red del proxy central y conecta el contenedor `ddt-api` a ella:

    # nombre del contenedor del proxy (ajústalo): p.ej. caddy, proxy, npm...
    docker inspect <contenedor-proxy> -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}'
    docker network connect <esa-red> ddt-api

Para que persista entre deploys, en `/opt/ddt/docker-compose.yml` agrega la red externa a `ddt-api`:

    services:
      ddt-api:
        networks: [ddt-net, <esa-red>]
    networks:
      ddt-net:
      <esa-red>:
        external: true

## 3. Agregar el sitio en el PROXY CENTRAL
### Si el proxy central es Caddy
En su Caddyfile:

    radio.distefanoshop.com:9444 {
        reverse_proxy ddt-api:8000
    }

Reusa el cert existente de `radio.distefanoshop.com` (mismo dominio) y maneja el WebSocket solo.
Recarga: `docker exec <contenedor-proxy> caddy reload --config /etc/caddy/Caddyfile` (o el de tu flujo).

### Si el proxy central es nginx
En un server block para el puerto 9444 con el cert del dominio:

    server {
        listen 9444 ssl;
        server_name radio.distefanoshop.com;
        ssl_certificate     /ruta/fullchain.pem;
        ssl_certificate_key /ruta/privkey.pem;
        location / {
            proxy_pass http://ddt-api:8000;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;      # WebSocket del visor
            proxy_set_header Connection "upgrade";
            proxy_set_header Host $host;
            proxy_read_timeout 86400;
        }
    }

## 4. Abrir el puerto 9444 en el firewall
    ufw allow 9444/tcp          # o en el firewall de Linode

## 5. Usar
Abre `https://radio.distefanoshop.com:9444`, inicia sesión con la cuenta de administrador.
Candado verde, sin instalar nada en la Mac.

## Alternativa sin red compartida (proxy en modo host)
Si el proxy central corre con `network_mode: host`, en vez del paso 2 publica `ddt-api` en loopback:
en `ddt-api` de `/opt/ddt/docker-compose.yml` agrega `ports: ["127.0.0.1:9081:8000"]`, y en el proxy
usa `reverse_proxy 127.0.0.1:9081` (Caddy) o `proxy_pass http://127.0.0.1:9081;` (nginx).
