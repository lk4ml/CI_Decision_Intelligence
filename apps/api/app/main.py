"""FastAPI app factory: CORS, routers under /api/v1, init_db + idempotent seed, scheduler."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import db
from app.routers import (agents, assets, briefs, events, hypotheses, me, models, patterns, positions, proposals,
                         scenarios, signals, sources)
from app.services.common import Conflict, Forbidden, NotFound

log = logging.getLogger("di")
API_PREFIX = "/api/v1"


def startup() -> None:
    db.init_db()
    from app.seed import seed

    s = db.SessionLocal()
    try:
        seed(s)
    finally:
        s.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup()
    sched = None
    try:
        from app.agents import scheduler as sched  # type: ignore
        sched.start(app)  # respects DI_DISABLE_SCHEDULER
    except ImportError as e:
        log.warning("agent scheduler unavailable: %s", e)
        sched = None
    except Exception:  # noqa: BLE001
        log.exception("scheduler failed to start")
    yield
    if sched is not None:
        try:
            sched.shutdown()
        except Exception:  # noqa: BLE001
            pass


def create_app() -> FastAPI:
    app = FastAPI(title="Decision Intelligence API", version="0.1.0", lifespan=lifespan)
    origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["X-Actor", "X-Role", "Content-Type", "Accept", "Cache-Control"])

    @app.exception_handler(Forbidden)
    async def _403(_: Request, e: Forbidden):
        return JSONResponse({"detail": str(e)}, status_code=403)

    @app.exception_handler(Conflict)
    async def _409(_: Request, e: Conflict):
        return JSONResponse({"detail": str(e)}, status_code=409)

    @app.exception_handler(NotFound)
    async def _404(_: Request, e: NotFound):
        return JSONResponse({"detail": str(e)}, status_code=404)

    for r in (assets, hypotheses, signals, proposals, patterns, models, scenarios, positions, briefs, agents, sources,
              events, me):
        app.include_router(r.router, prefix=API_PREFIX)

    @app.get("/health")
    def root_health():
        return {"ok": True}

    return app


app = create_app()
