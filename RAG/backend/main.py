"""
RAG System — FastAPI Application Entry Point
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from core.database import engine, Base
from api.routes import auth, documents, collections, system

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

# Routes
app.include_router(system.router, prefix="/api/v1", tags=["system"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(documents.router, prefix="/api/v1/documents", tags=["documents"])
app.include_router(collections.router, prefix="/api/v1", tags=["collections"])
