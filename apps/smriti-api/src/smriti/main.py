"""Smriti API gateway skeleton."""

from __future__ import annotations

import subprocess
from importlib.metadata import PackageNotFoundError, version as pkg_version

import asyncpg
import httpx
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from smriti.config import settings
from smriti.db.connection import get_pool
from smriti.logging_config import configure_logging
from smriti.middleware import ConsentMiddleware, RateLimitMiddleware, RequestIDMiddleware
from smriti.routes.clinician import router as clinician_router
from smriti.routes.patient import router as patient_router
from smriti.routes.provider import router as provider_router

configure_logging()
logger = structlog.get_logger("smriti_api")

app = FastAPI(
    title="Smriti API",
    description="AI-agent-powered patient memory layer",
    version=settings.app_version,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware execution order required: RequestID -> RateLimit -> Consent.
# Starlette wraps in reverse of insertion, so add in reverse order.
app.add_middleware(ConsentMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestIDMiddleware)

app.include_router(patient_router)
app.include_router(clinician_router)
app.include_router(provider_router)


@app.on_event("startup")
async def on_startup() -> None:
    logger.info("smriti_api_starting", port=settings.smriti_api_port)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    logger.info("smriti_api_stopping")


@app.get("/health")
async def health() -> dict[str, object]:
    db_ok = False
    mock_abha_ok = False
    groq_ok = False

    try:
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            db_ok = True
        except Exception as e:
            logger.warning("health_check_db_failed", error=str(e))
            db_ok = False

        async with httpx.AsyncClient(timeout=3.0) as client:
            try:
                resp = await client.head(f"{settings.mock_abha_url}/health")
                mock_abha_ok = resp.status_code < 500
            except Exception:
                mock_abha_ok = False

            try:
                resp = await client.head("https://api.groq.com/openai/v1/models")
                groq_ok = resp.status_code < 500
            except Exception:
                groq_ok = False
    except Exception as e:
        logger.error("health_check_exception", error=str(e))

    overall = "ok" if all([db_ok, mock_abha_ok, groq_ok]) else "degraded"
    return {
        "status": overall,
        "checks": {
            "database": db_ok,
            "mock_abha": mock_abha_ok,
            "groq": groq_ok,
        },
    }


@app.get("/version")
async def api_version() -> dict[str, str]:
    app_version = settings.app_version
    try:
        app_version = pkg_version("smriti-api")
    except PackageNotFoundError:
        pass

    git_commit = settings.git_commit
    if git_commit == "unknown":
        try:
            git_commit = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], text=True
            ).strip()
        except Exception:
            git_commit = "unknown"

    return {"app_version": app_version, "git_commit": git_commit}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=settings.smriti_api_port)
