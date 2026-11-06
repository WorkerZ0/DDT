import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.config import settings
from src.config.db import init_db
from src.helpers import repo
from src.routes import auth, devices, users, ws

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
