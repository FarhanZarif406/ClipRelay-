from fastapi import APIRouter

from app.api import audit, auth, dashboard, events, jobs, logs, prompts, settings, sources, tiktok, users

api_router = APIRouter(prefix="/api")
for module in (auth, users, dashboard, sources, tiktok, prompts, jobs, audit, logs, settings, events):
    api_router.include_router(module.router)
