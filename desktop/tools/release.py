"""Firma de actualizaciones (solo en la PC del desarrollador; no va en el instalador).

  python tools/release.py keygen                 crea la llave privada (una sola vez) e imprime la pública
  python tools/release.py sign <instalador.exe>  genera updates/latest.json + latest.json.sig junto al .exe

La llave privada vive fuera del repo (DDT_SIGNING_KEY o %USERPROFILE%\\.ddt\\update_signing.key).
Si se pierde no se pueden publicar actualizaciones automáticas: hay que reinstalar a mano con otra llave.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import ed25519  # noqa: E402

KEY_FILE = Path(os.getenv("DDT_SIGNING_KEY", Path.home() / ".ddt" / "update_signing.key"))


def keygen() -> None:
    if KEY_FILE.exists():
        sys.exit(f"Ya existe {KEY_FILE}: no se sobrescribe")
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    seed = secrets.token_bytes(32)
    KEY_FILE.write_text(seed.hex(), encoding="ascii")
    print(f"Llave privada: {KEY_FILE}  (respaldarla en un lugar seguro)")
    print(f"UPDATE_PUBKEY = \"{ed25519.public_key(seed).hex()}\"")


def sign(installer: Path) -> None:
    if not KEY_FILE.exists():
        sys.exit(f"No hay llave de firma en {KEY_FILE}")
    match = re.fullmatch(r"DDTMonitor-Setup-(\d+(?:\.\d+)*)\.exe", installer.name)
    if not match:
        sys.exit(f"Nombre inesperado: {installer.name}")
    seed = bytes.fromhex(KEY_FILE.read_text(encoding="ascii").strip())
    out = installer.parent / "updates"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir()
    shutil.copy2(installer, out / installer.name)
    manifest = json.dumps({
        "version": match.group(1),
        "file": installer.name,
        "size": installer.stat().st_size,
        "sha256": hashlib.sha256(installer.read_bytes()).hexdigest(),
    }, indent=2).encode("utf-8")
    (out / "latest.json").write_bytes(manifest)
    (out / "latest.json.sig").write_text(ed25519.sign(seed, manifest).hex(), encoding="ascii")
    print(f"Actualizacion firmada en {out}")


if __name__ == "__main__":
    if sys.argv[1:] == ["keygen"]:
        keygen()
    elif len(sys.argv) == 3 and sys.argv[1] == "sign":
        sign(Path(sys.argv[2]).resolve())
    else:
        sys.exit(__doc__)
