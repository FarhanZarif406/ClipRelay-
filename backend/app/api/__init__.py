from fastapi import APIRouter

from app.api import audit, auth, channels, credentials, downloader, dashboard, events, jobs, llm_providers, logs, prompts, settings, tiktok, users

api_router = APIRouter(prefix="/api")
for module in (auth, users, dashboard, channels, downloader, tiktok, prompts, jobs, audit, logs, settings, credentials, llm_providers, events):
    api_router.include_router(module.router)
