import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from core.database import db
from plugins.registry import plugin_registry
from api.routes import scan, vin, reports, plugins
from api.websocket import router as ws_router

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ]
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await db.connect()
    db_configs = await db.get_plugin_configs()
    plugin_registry.discover()
    plugin_registry.apply_db_config(db_configs)
    logger.info("vinhunter.started", plugins=len(plugin_registry.get_all()))
    yield
    # Shutdown
    await db.disconnect()
    logger.info("vinhunter.stopped")


app = FastAPI(
    title="VINhunter API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scan.router, prefix="/api")
app.include_router(vin.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(plugins.router, prefix="/api")
app.include_router(ws_router)


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "plugins": len(plugin_registry.get_enabled()),
    }
