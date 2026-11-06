"""Rescate por consola. Ej.: docker exec -it ddt-api python -m src.manage reset-password admin NuevaClave"""
import sys

from src.config.db import init_db
from src.helpers import repo


def main() -> None:
    if len(sys.argv) != 4 or sys.argv[1] != "reset-password":
        sys.exit("Uso: python -m src.manage reset-password <usuario> <clave>")
    init_db()
    user = repo.get_user_by_username(sys.argv[2])
    if not user:
        sys.exit("Usuario no existe")
    repo.update_user(user["id"], password=sys.argv[3], active=True)
    print(f"Clave de '{user['username']}' cambiada y usuario activado")


if __name__ == "__main__":
    main()
