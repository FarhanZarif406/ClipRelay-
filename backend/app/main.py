import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select, text

from app.api import api_router
from app.config import get_settings
from app.db import SessionLocal
from app.models import PromptTemplate
from app.services import credentials
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
