"""Server-Sent Events stream for live dashboard updates (EventSource can't send headers → token in query)."""

import asyncio
import json

import redis.asyncio as aioredis
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from redis.exceptions import RedisError

from app.api.deps import user_from_token
from app.config import get_settings
from app.db import SessionLocal
from app.services.events import CHANNEL

router = APIRouter(tags=["live"])


@router.get("/events")
async def events(request: Request, token: str):
    db = SessionLocal()
    try:
        user_from_token(db, token)
    finally:
        db.close()

    async def stream():
        client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
        pubsub = client.pubsub()
        try:
            await pubsub.subscribe(CHANNEL)
        except RedisError:
            # No Redis (for example a local install): keep the connection open and let the pages poll instead.
            await client.aclose()
            yield f"data: {json.dumps({'type': 'hello', 'live': False})}\n\n"
            while not await request.is_disconnected():
                yield ": keep-alive\n\n"
                await asyncio.sleep(15)
            return
        try:
            yield f"data: {json.dumps({'type': 'hello'})}\n\n"
            while not await request.is_disconnected():
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15)
                if message:
                    yield f"data: {message['data']}\n\n"
                else:
                    yield ": keep-alive\n\n"
                await asyncio.sleep(0.05)
        finally:
            await pubsub.unsubscribe(CHANNEL)
            await client.aclose()

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
