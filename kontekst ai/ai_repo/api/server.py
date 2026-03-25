"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ai_repo.config import settings

logger = logging.getLogger(__name__)

# Project root (kontekst ai/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        from ai_repo.core.database import Database

        app.state.db = Database()
        logger.info("Database connected")

        # Load plugins
        try:
            from ai_repo.plugins.loader import PluginLoader
            loader = PluginLoader()
            loaded = loader.load_all(db=app.state.db)
            logger.info(f"Loaded {loaded} plugins")
        except Exception as e:
            logger.warning(f"Plugin loading failed: {e}")

        yield

        # Shutdown
        logger.info("Shutting down")

    app = FastAPI(
        title="AI-Aware Repo",
        version="0.1.0",
        description="Code indexing, graph analysis, and RAG for any repository.",
        lifespan=lifespan,
    )

    # Mount routers
    from ai_repo.api.routes.graph import router as graph_router
    from ai_repo.api.routes.memory import router as memory_router
    from ai_repo.api.routes.monitoring import router as monitoring_router
    from ai_repo.api.routes.query import router as query_router
    from ai_repo.api.routes.system import router as system_router

    app.include_router(query_router, prefix="/query", tags=["query"])
    app.include_router(graph_router, prefix="/graph", tags=["graph"])
    app.include_router(memory_router, prefix="/memory", tags=["memory"])
    app.include_router(monitoring_router, prefix="/monitoring", tags=["monitoring"])
    app.include_router(system_router, tags=["system"])

    # Mount MCP if available
    try:
        from ai_repo.api.mcp.server import router as mcp_router
        app.include_router(mcp_router, prefix="/mcp", tags=["mcp"])
    except ImportError:
        logger.debug("MCP module not available")

    # Static files (graph.html etc.)
    static_dir = _PROJECT_ROOT / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
        logger.info(f"Mounted static files from {static_dir}")

    # Mount Chainlit chat UI (MUST be after all routers)
    # NOTE: mount_chainlit may cause event loop issues, so we mount it carefully
    try:
        from chainlit.utils import mount_chainlit

        chainlit_app = str(_PROJECT_ROOT / "chainlit_app.py")
        # Mount chainlit - this should work now that /query uses retrieve_sync()
        mount_chainlit(app=app, target=chainlit_app, path="/chat")
        logger.info("Chainlit mounted at /chat")
    except ImportError:
        logger.debug("Chainlit not installed — chat UI disabled")
    except Exception as e:
        logger.warning(f"Failed to mount Chainlit: {e}")

    return app
