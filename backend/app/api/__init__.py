from fastapi import APIRouter

from app.api import auth, buffer, channels, credentials, downloader, dashboard, editing, integrations, events, jobs, llm_providers, logs, prompts, settings, users

api_router = APIRouter(prefix="/api")
for module in (auth, users, dashboard, buffer, channels, editing, downloader, integrations, prompts, jobs, logs, settings, credentials, llm_providers, events):
    api_router.include_router(module.router)
