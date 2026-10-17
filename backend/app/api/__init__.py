from fastapi import APIRouter

from app.api import accounts, auth, buffer, channels, cloud, credentials, downloader, dashboard, editing, integrations, events, helper, jobs, llm_providers, logs, prompts, settings, system, users

api_router = APIRouter(prefix="/api")
for module in (auth, accounts, users, dashboard, buffer, channels, editing, downloader, integrations, prompts, jobs, logs, settings, credentials, llm_providers, events, system, helper, cloud):
    api_router.include_router(module.router)
