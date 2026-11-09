"""
RAG System — FastAPI Application Entry Point
"""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from config import settings
from core.database import engine, Base
from api.rate_limit import limiter
from api.routes import auth, chat, documents, collections, system

logger = logging.getLogger("rag")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logging.basicConfig(
        level=getattr(logging, settings.app.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("RAG System starting up...")
    logger.info(f"Ollama URL: {settings.ai.ollama_url}")
    logger.info(f"Database: {settings.database.host}:{settings.database.port}/{settings.database.name}")
    yield
    from api.routes.chat import service as chat_service
    await chat_service.close()
    await engine.dispose()
    logger.info("RAG System shut down.")


app = FastAPI(
    title="RAG System API",
    description="Self-hosted RAG pipeline with multimodal document processing",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration_ms = int((time.time() - start) * 1000)
    if duration_ms > 1000 or response.status_code >= 400:
        logger.info(
            "%s %s → %d (%dms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
    return response


# Routes
app.include_router(system.router, prefix="/api/v1", tags=["system"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(documents.router, prefix="/api/v1/documents", tags=["documents"])
app.include_router(collections.router, prefix="/api/v1", tags=["collections"])
app.include_router(chat.router, prefix="/api/v1/chat", tags=["chat"])
