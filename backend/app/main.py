import logging

from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import i18n
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select, text

from app.api import api_router
from app.config import get_settings
from app.db import SessionLocal
from app.models import PromptTemplate
from app.services import credentials, downloader, plans
from app.services.prompts import DEFAULT_TEMPLATE

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

settings = get_settings()
app = FastAPI(title="ClipRelay API", version="1.0.0", docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.exception_handler(plans.PlanLimit)
def plan_limit(request: Request, exc: plans.PlanLimit):
    """Something the account's plan does not allow: a 403 with the reason, for the page to show (in its language)."""
    return JSONResponse(status_code=403, content={"detail": i18n.translate(str(exc), request.headers.get("x-lang"))})


@app.exception_handler(StarletteHTTPException)
def http_error(request: Request, exc: StarletteHTTPException):
    """Every refusal goes out in the user's language when it is one of the common ones (the page sends X-Lang)."""
    detail = exc.detail
    if isinstance(detail, str):
        detail = i18n.translate(detail, request.headers.get("x-lang"))
    elif isinstance(detail, dict) and isinstance(detail.get("message"), str):
        detail = {**detail, "message": i18n.translate(detail["message"], request.headers.get("x-lang"))}
    return JSONResponse(status_code=exc.status_code, content={"detail": detail}, headers=getattr(exc, "headers", None))


@app.get("/api/health", tags=["health"])
def health():
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok"}
    finally:
        db.close()


@app.on_event("startup")
def start_credential_listener() -> None:
    credentials.start_listener()
    downloader.use_shared_packages()  # a yt-dlp updated from the app (in any container) is used from the start


@app.on_event("startup")
def start_inline_worker() -> None:
    if settings.inline_worker and settings.environment != "test":
        from app.services import local_runner

        local_runner.start()


@app.on_event("startup")
def seed_defaults() -> None:
    """Make sure a default prompt template exists so the pipeline can rewrite out of the box."""
    db = SessionLocal()
    try:
        if not db.scalar(select(func.count(PromptTemplate.id))):
            db.add(PromptTemplate(**DEFAULT_TEMPLATE, is_default=True))
            db.commit()
    except Exception as exc:  # tables may not exist yet if migrations haven't run
        logging.getLogger(__name__).warning("Skipping default seed: %s", exc)
    finally:
        db.close()
