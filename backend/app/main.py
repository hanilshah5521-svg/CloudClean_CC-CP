import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes import (
    analysis, analytics, archive, auth, compression, duplicates, files, gmail,
    history, jobs, recommendations, rules, settings as settings_routes, storage,
)
from app.api.routes import organize as organize_routes
from app.api.routes import s3 as s3_routes
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

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.resolved_secret_key,
    same_site="lax",
    https_only=settings.cookie_secure,
    max_age=7 * 24 * 3600,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(PermissionError)
@app.exception_handler(RefreshError)
async def google_auth_error_handler(request: Request, exc: Exception):
    # Token missing, expired beyond refresh, or revoked by the user in their Google account.
    logger.warning("Google authorization failed on %s: %s", request.url.path, exc)
    return JSONResponse(status_code=401, content={"detail": "Google authorization expired or was revoked. Please reconnect your Google account."})


@app.exception_handler(HttpError)
async def google_api_error_handler(request: Request, exc: HttpError):
    logger.warning("Google API error on %s: %s", request.url.path, exc)
    return JSONResponse(status_code=502, content={"detail": f"Google API error ({exc.resp.status}): {exc.reason}. Nothing further was changed."})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Never leak stack traces to the client — log server-side, return a generic message.
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on our end. Please try again."})


@app.get("/health")
def health():
    return {"status": "ok"}


for router in (auth.router, storage.router, files.router, analysis.router, analytics.router, recommendations.router,
               duplicates.router, compression.router, archive.router, gmail.router, history.router, settings_routes.router,
               jobs.router, rules.router):
    app.include_router(router)
app.include_router(s3_routes.router)  # AWS S3 provider
app.include_router(organize_routes.router)  # folder grouping by naming convention
