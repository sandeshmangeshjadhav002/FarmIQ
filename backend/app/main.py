"""FarmIQ FastAPI application entrypoint.

Run from the backend/ directory:
    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.errors import register_handlers
from app.logging_conf import setup_logging
from app.routers import auth, chat, dashboard, devices, farms, health, predictions, sensors, users, voice

setup_logging()
logger = logging.getLogger("farmiq")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("FarmIQ API starting — CORS origins: %s", settings.cors_origins)
    logger.info("ML processed dir: %s", settings.ml_processed_dir)
    logger.info("ML models dir:    %s", settings.ml_models_dir)
    
    # Warm up RAG pipeline in a background thread to avoid blocking startup
    # or the first request delay.
    import threading
    from app import rag_service
    threading.Thread(target=rag_service.get_status, daemon=True).start()
    
    yield
    logger.info("FarmIQ API shutting down.")


app = FastAPI(title="FarmIQ API", version="2.0.0", lifespan=lifespan)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+)(:\d+)?",  # LAN IPs for dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_handlers(app)

for module in (health, auth, users, farms, devices, sensors, predictions, dashboard, chat, voice):
    app.include_router(module.router)
