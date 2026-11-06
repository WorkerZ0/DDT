import logging

from src.config.db import db
from src.helpers.security import hash_password

log = logging.getLogger("ddt.repo")


def public_user(row: dict) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "display_name": row["display_name"],
        "active": bool(row["active"]),
        "created_at": row["created_at"],
    }


# ---------- usuarios ----------

def get_user(user_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_username(username: str) -> dict | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return dict(row) if row else None


def list_users() -> list[dict]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY role, username").fetchall()
    return [public_user(dict(r)) for r in rows]


def count_active_admins() -> int:
    with db() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1"
        ).fetchone()[0]


def create_user(username: str, password: str, role: str, display_name: str) -> dict:
    """Lanza sqlite3.IntegrityError si el usuario ya existe."""
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, role, display_name) VALUES (?, ?, ?, ?)",
            (username, hash_password(password), role, display_name),
        )
        user_id = cur.lastrowid
    return get_user(user_id)


def update_user(user_id: int, *, password=None, role=None, display_name=None, active=None) -> tuple[dict, bool]:
    """Devuelve (usuario, sesiones_revocadas). Cambiar clave, rol o estado invalida los tokens."""
    sets, args = [], []
    revoke = False
    if display_name is not None:
        sets.append("display_name = ?")
        args.append(display_name)
    if password is not None:
        sets.append("password_hash = ?")
        args.append(hash_password(password))
        revoke = True
    if role is not None:
        sets.append("role = ?")
        args.append(role)
        revoke = True
    if active is not None:
        sets.append("active = ?")
        args.append(int(active))
        revoke = revoke or not active
    if revoke:
        sets.append("token_version = token_version + 1")
    if sets:
        with db() as conn:
            conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", (*args, user_id))
    return get_user(user_id), revoke


def delete_user(user_id: int) -> None:
    with db() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


def ensure_admin(username: str, password: str) -> None:
    with db() as conn:
        exists = conn.execute("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1").fetchone()
    if exists:
        return
    if not password:
        log.warning("No hay admin y ADMIN_PASSWORD está vacío: no se creó ninguno")
        return
    create_user(username, password, "admin", "Administrador")
    log.info("Admin inicial '%s' creado", username)


# ---------- dispositivos ----------

def upsert_device(user_id: int, hostname: str) -> int:
    with db() as conn:
        conn.execute(
            """INSERT INTO devices (user_id, hostname, last_seen) VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT (user_id, hostname) DO UPDATE SET last_seen = CURRENT_TIMESTAMP""",
            (user_id, hostname),
        )
        return conn.execute(
            "SELECT id FROM devices WHERE user_id = ? AND hostname = ?", (user_id, hostname)
        ).fetchone()[0]


def touch_device(device_id: int) -> None:
    with db() as conn:
        conn.execute("UPDATE devices SET last_seen = CURRENT_TIMESTAMP WHERE id = ?", (device_id,))


def list_devices() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """SELECT d.id, d.hostname, d.first_seen, d.last_seen, d.user_id,
                      u.username, u.display_name, u.active
               FROM devices d JOIN users u ON u.id = d.user_id
               ORDER BY u.display_name, u.username, d.hostname"""
        ).fetchall()
    return [dict(r) for r in rows]


def delete_device(device_id: int) -> bool:
    with db() as conn:
        return conn.execute("DELETE FROM devices WHERE id = ?", (device_id,)).rowcount > 0
