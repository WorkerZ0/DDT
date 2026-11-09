import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from src.config import settings
from src.config.db import init_db
from src.helpers import repo
from src.routes import auth, devices, users, ws

WEB_DIR = Path(__file__).resolve().parent / "web"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    repo.ensure_admin(settings.ADMIN_USER, settings.ADMIN_PASSWORD)
    yield


app = FastAPI(title="DDT", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

for module in (auth, users, devices, ws):
    app.include_router(module.router)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/")
def root():
    return RedirectResponse("/app/")


# Panel web de administrador (visor). Sirve para cualquier navegador/SO sin instalar nada.
if WEB_DIR.is_dir():
    app.mount("/app", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
