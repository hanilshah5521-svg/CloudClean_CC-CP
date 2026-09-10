import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes import (
    analysis, analytics, archive, auth, compression, duplicates, files,
    history, recommendations, settings as settings_routes, storage,
)
from app.core.config import settings
from app.core.database import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cloudclean")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="CloudClean API",
    description="Intelligent Google Drive Storage Optimization & Lifecycle Management Platform",
    lifespan=lifespan,
)

app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, same_site="lax", https_only=False)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Never leak stack traces to the client — log server-side, return a generic message.
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on our end. Please try again."})


@app.get("/health")
def health():
    return {"status": "ok"}


for router in (auth.router, storage.router, files.router, analysis.router, analytics.router, recommendations.router,
               duplicates.router, compression.router, archive.router, history.router, settings_routes.router):
    app.include_router(router)
