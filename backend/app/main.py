"""FarmIQ FastAPI application entrypoint.

Run from the backend/ directory:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import API_VERSION, get_settings
from app.errors import register_handlers
from app.logging_conf import setup_logging
from app.rate_limit import RateLimitMiddleware
from app.routers import (
    alerts,
    auth,
    chat,
    dashboard,
    demo,
    devices,
    drought,
    farms,
    farming,
    health,
    mlops,
    predictions,
    schemes,
    sensors,
    simulator,
    users,
    voice,
    weather,
)

setup_logging()
logger = logging.getLogger("farmiq")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info(
        "FarmIQ API starting — environment=%s CORS origins: %s",
        settings.environment,
        settings.cors_origins,
    )
    logger.info("ML processed dir: %s", settings.ml_processed_dir)
    logger.info("ML models dir:    %s", settings.ml_models_dir)
    logger.info(
        "Rate limiting: %s (trust proxy headers: %s)",
        "enabled" if settings.rate_limit_enabled else "DISABLED",
        settings.trust_proxy_headers,
    )
    
    # Warm up RAG pipeline in a background thread to avoid blocking startup
    # or the first request delay.
    import threading
    from app import rag_service
    threading.Thread(target=rag_service.get_status, daemon=True).start()
    
    yield
    # Release pooled outbound connections (weather providers).
    from app import weather
    weather.close_clients()
    logger.info("FarmIQ API shutting down.")


app = FastAPI(title="FarmIQ API", version=API_VERSION, lifespan=lifespan)

settings = get_settings()

# Middleware ordering matters: Starlette applies the LAST added middleware as
# the OUTERMOST layer. The limiter is therefore added first so that
# CORSMiddleware stays outermost and a 429 still carries CORS headers — without
# this the browser reports an opaque CORS failure instead of the real status.
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # Empty string -> None, i.e. no regex matching at all.
    allow_origin_regex=settings.effective_cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_handlers(app)

for module in (
    health,
    auth,
    users,
    farms,
    devices,
    sensors,
    predictions,
    dashboard,
    chat,
    voice,
    weather,
    simulator,
    schemes,
    mlops,
    farming,
    drought,
    demo,
    alerts,
):
    app.include_router(module.router)
