from fastapi import APIRouter

from app.api import auth, buffer, channels, credentials, downloader, dashboard, editing, integrations, events, jobs, llm_providers, logs, prompts, settings, system, users

api_router = APIRouter(prefix="/api")
for module in (auth, users, dashboard, buffer, channels, editing, downloader, integrations, prompts, jobs, logs, settings, credentials, llm_providers, events, system):
    api_router.include_router(module.router)
