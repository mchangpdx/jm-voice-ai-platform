# AI Voice Bot settings API — persona prompts + Retell agent status
# (AI Voice Bot 설정 API — 페르소나 프롬프트 + Retell 에이전트 상태)
#
# GET  /api/store/voice-bot              — system_prompt, temporary_prompt, retell_agent_id
# PATCH /api/store/voice-bot             — update prompts
# GET  /api/store/voice-bot/agent-status — live Retell agent info (voice, name, ws_url)

from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import get_tenant_id
from app.core.config import settings

router = APIRouter(prefix="/api/store", tags=["Voice Bot"])

_SUPABASE_HEADERS = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type":  "application/json",
    "Prefer":        "return=representation",
}
_REST = f"{settings.supabase_url}/rest/v1"

_RETELL_HEADERS = {
    "Authorization": f"Bearer {settings.retell_api_key}",
    "Content-Type":  "application/json",
}


# ── Schemas ───────────────────────────────────────────────────────────────────

class VoiceBotSettings(BaseModel):
    store_name:       str
    retell_agent_id:  Optional[str]
    system_prompt:    Optional[str]
    temporary_prompt: Optional[str]
    business_hours:   Optional[str]
    custom_knowledge: Optional[str]
    is_active:        bool = True


class VoiceBotPatch(BaseModel):
    system_prompt:    Optional[str] = None
    temporary_prompt: Optional[str] = None
    business_hours:   Optional[str] = None
    custom_knowledge: Optional[str] = None


class AgentStatus(BaseModel):
    agent_id:         str
    agent_name:       str
    voice_id:         str
    llm_websocket_url: Optional[str]


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _resolve_store(client: httpx.AsyncClient, owner_id: str) -> dict:
    resp = await client.get(
        f"{_REST}/stores",
        headers=_SUPABASE_HEADERS,
        params={
            "owner_id": f"eq.{owner_id}",
            "select":   "id,name,retell_agent_id,system_prompt,temporary_prompt,business_hours,custom_knowledge,is_active",
        },
    )
    stores = resp.json()
    if not stores:
        raise HTTPException(status_code=404, detail="Store not found")
    return stores[0]


# ── GET /api/store/voice-bot ──────────────────────────────────────────────────

@router.get("/voice-bot", response_model=VoiceBotSettings)
async def get_voice_bot(owner_id: str = Depends(get_tenant_id)):
    async with httpx.AsyncClient() as client:
        store = await _resolve_store(client, owner_id)
    return VoiceBotSettings(
        store_name=store["name"],
        retell_agent_id=store.get("retell_agent_id"),
        system_prompt=store.get("system_prompt"),
        temporary_prompt=store.get("temporary_prompt"),
        business_hours=store.get("business_hours"),
        custom_knowledge=store.get("custom_knowledge"),
        is_active=store.get("is_active", True),
    )


# ── PATCH /api/store/voice-bot ────────────────────────────────────────────────

@router.patch("/voice-bot", response_model=VoiceBotSettings)
async def patch_voice_bot(
    body: VoiceBotPatch,
    owner_id: str = Depends(get_tenant_id),
):
    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    if not payload:
        raise HTTPException(status_code=400, detail="No fields to update")

    async with httpx.AsyncClient() as client:
        store = await _resolve_store(client, owner_id)

        resp = await client.patch(
            f"{_REST}/stores",
            headers=_SUPABASE_HEADERS,
            params={"id": f"eq.{store['id']}"},
            json=payload,
        )
        updated = resp.json()
        if not updated:
            raise HTTPException(status_code=500, detail="Update failed")
        row = updated[0]

    return VoiceBotSettings(
        store_name=row["name"],
        retell_agent_id=row.get("retell_agent_id"),
        system_prompt=row.get("system_prompt"),
        temporary_prompt=row.get("temporary_prompt"),
        business_hours=row.get("business_hours"),
        custom_knowledge=row.get("custom_knowledge"),
        is_active=row.get("is_active", True),
    )


# ── GET /api/store/voice-bot/agent-status ─────────────────────────────────────

@router.get("/voice-bot/agent-status", response_model=AgentStatus)
async def get_agent_status(owner_id: str = Depends(get_tenant_id)):
    async with httpx.AsyncClient() as client:
        store = await _resolve_store(client, owner_id)

        agent_id = store.get("retell_agent_id")
        if not agent_id:
            raise HTTPException(status_code=404, detail="No Retell agent linked to this store")

        resp = await client.get(
            f"{settings.retell_api_url}/get-agent/{agent_id}",
            headers=_RETELL_HEADERS,
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Retell API error")

        agent = resp.json()

    ws_url = agent.get("response_engine", {}).get("llm_websocket_url")
    return AgentStatus(
        agent_id=agent["agent_id"],
        agent_name=agent["agent_name"],
        voice_id=agent.get("voice_id", ""),
        llm_websocket_url=ws_url,
    )
