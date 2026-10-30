"""Unified AI agent endpoints.

Endpoints
---------
``POST /api/agent/chat``    – one farm question → tool-assisted, evidence-based
                              answer (structured sections + supporting context).
``GET  /api/agent/context`` – the complete, structured context of the caller's
                              farm (ML, sensors, weather, profile, freshness).

Both require authentication and are scoped to the caller's own rows: the tools
read through :mod:`app.db`, which filters on ``owner_id``, and no endpoint
accepts an ``owner_id`` from the client.

Why the work runs in a threadpool
---------------------------------
This router is ``async`` so FastAPI can keep serving other requests, but the
database client (``supabase-py``) and the ML adapter are synchronous. The
blocking call is therefore dispatched with ``run_in_threadpool`` instead of
being awaited inline, so a slow weather lookup or model read cannot stall the
event loop for every other farmer.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from starlette.concurrency import run_in_threadpool

from app import agent_service, farm_context_manager
from app.auth import AuthUser, get_current_user
from app.schemas import AgentChatRequest, AgentChatResponse, AgentContextResponse
from app.supabase_client import get_admin_client

logger = logging.getLogger("farmiq.agent.api")

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/chat", response_model=AgentChatResponse)
async def agent_chat(
    payload: AgentChatRequest,
    user: AuthUser = Depends(get_current_user),
    client: Any = Depends(get_admin_client),
) -> AgentChatResponse:
    """Answer one farm question with the tool-enabled agent.

    The agent decides which tools the question needs, reads only those, and
    replies with the values it actually found. The optional assistant
    explanation is additive: if it is unavailable the structured answer is
    still returned.
    """
    result = await run_in_threadpool(
        agent_service.answer,
        payload.message,
        client=client,
        owner_id=user.id,
        farm_id=payload.farm_id,
        language=payload.language,
        history=payload.history,
    )
    return AgentChatResponse(**result)


@router.get("/context", response_model=AgentContextResponse)
async def agent_context(
    farm_id: Optional[str] = Query(default=None, max_length=100),
    include_weather: bool = Query(default=True),
    user: AuthUser = Depends(get_current_user),
    client: Any = Depends(get_admin_client),
) -> AgentContextResponse:
    """The caller's farm context as structured JSON, built on demand.

    Nothing is cached across requests here beyond the short-lived weather
    cache, so the context always reflects the account's current data.
    """
    context = await run_in_threadpool(
        farm_context_manager.build_context,
        client,
        user.id,
        farm_id=farm_id,
        include_weather=include_weather,
    )
    return AgentContextResponse(**context)
