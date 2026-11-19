"""FastAPI application factory. Run locally: ``uvicorn recallspring_api.main:app --host 127.0.0.1 --port 4318``."""

from __future__ import annotations

import logging

from fastapi import FastAPI

from . import __version__, errors
from .api import attempts, auth, connector, courses, health, notes, questions, reviews, settings, sources, study
from .config import get_settings
from .security import LoginRateLimiter

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    config = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    dev = config.environment != "production"
    app = FastAPI(
        title="RecallSpring API",
        version=__version__,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs" if dev else None,
        redoc_url=None,
    )
    app.state.login_limiter = LoginRateLimiter(config.login_max_failures, config.login_failure_window_seconds)
    errors.install(app)
    for module in (health, auth, courses, sources, notes, study, questions, attempts, reviews, settings, connector):
        app.include_router(module.router, prefix=API_PREFIX)
    return app


app = create_app()
