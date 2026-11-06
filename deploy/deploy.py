"""Deploy DDT a /opt/ddt (VPS). Clave de root por env DDT_ROOT_PW (no se guarda)."""
import io
import os
import sys
import tarfile
import time
from pathlib import Path

import paramiko

HOST = "45.79.170.84"
ROOT = Path(r"C:\Users\Javier Herrera\Desktop\Distefano\Proyectos\DDT")
BACK = ROOT / "back"
UPDATES = ROOT / "desktop" / "installer" / "Output" / "updates"
SKIP = {".env", "updates", "__pycache__"}

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username="root", password=os.environ["DDT_ROOT_PW"], timeout=20, look_for_keys=False, allow_agent=False)


def run(cmd: str, check: bool = True) -> str:
    print(f"$ {cmd}")
    _, out, err = ssh.exec_command(cmd, timeout=900)
    code = out.channel.recv_exit_status()
    text = (out.read() + err.read()).decode("utf-8", "replace").strip()
    if text:
        print(text[-3000:])
    if check and code != 0:
        sys.exit(f"fallo ({code}): {cmd}")
    return text


stamp = time.strftime("%Y%m%d-%H%M")
run("cd /opt/ddt && docker compose ps --format '{{.Name}} {{.Status}}'")
run(f"cp -a /opt/ddt /opt/ddt.bak-{stamp} && echo respaldo /opt/ddt.bak-{stamp}")

buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode="w:gz") as tar:
    for path in BACK.rglob("*"):
        rel = path.relative_to(BACK)
        if path.is_file() and not (set(rel.parts) & SKIP):
            tar.add(path, arcname=rel.as_posix())
buf.seek(0)
sftp = ssh.open_sftp()
sftp.putfo(buf, "/tmp/ddt-back.tgz")
run("tar -xzf /tmp/ddt-back.tgz -C /opt/ddt && rm /tmp/ddt-back.tgz && mkdir -p /opt/ddt/updates")

for f in UPDATES.iterdir():
    print(f"subiendo {f.name} ({f.stat().st_size:,} bytes)")
    sftp.put(str(f), f"/opt/ddt/updates/{f.name}.tmp")
# latest.json al final: las PCs no ven la versión nueva hasta que el instalador esté completo
for name in sorted((f.name for f in UPDATES.iterdir()), key=lambda n: n.startswith("latest")):
    run(f"mv -f /opt/ddt/updates/{name}.tmp /opt/ddt/updates/{name}")
sftp.close()

run("set -o pipefail; cd /opt/ddt && docker run --rm -e PUBLIC_HOST=$(grep ^PUBLIC_HOST .env | cut -d= -f2) "
    "-v /opt/ddt/Caddyfile:/etc/caddy/Caddyfile:ro caddy:2.8.4-alpine caddy validate --config /etc/caddy/Caddyfile "
    "--adapter caddyfile 2>&1 | tail -3")
run("set -o pipefail; cd /opt/ddt && docker compose build ddt-api 2>&1 | tail -5")
run("set -o pipefail; cd /opt/ddt && docker compose up -d 2>&1 | tail -5")
time.sleep(5)
run("cd /opt/ddt && docker compose ps --format '{{.Name}} {{.Status}}'")
run("curl -sk https://127.0.0.1:9443/api/health; echo; curl -sk https://127.0.0.1:9443/updates/latest.json")
run("docker logs --tail 5 ddt-api 2>&1; docker logs --tail 5 ddt-caddy 2>&1 | cut -c1-300")
ssh.close()
