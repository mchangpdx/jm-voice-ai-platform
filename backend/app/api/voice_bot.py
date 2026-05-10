# AI Voice Bot settings API — persona prompts + OpenAI Realtime agent status
# (AI Voice Bot 설정 API — 페르소나 프롬프트 + OpenAI Realtime 에이전트 상태)
#
# GET  /api/store/voice-bot              — system_prompt, temporary_prompt
# PATCH /api/store/voice-bot             — update prompts
# GET  /api/store/voice-bot/agent-status — live OpenAI Realtime agent info
#                                          (model, voice, system_prompt_loaded, last_call_at)
#
# Phase 2-D migration: Retell API dependency removed. last_call_at is derived
# from bridge_transactions.created_at MAX (per store).
# (Phase 2-D: Retell API 의존 제거. last_call_at은 bridge_transactions에서 직접 조립)

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


# ── Schemas ───────────────────────────────────────────────────────────────────

class VoiceBotSettings(BaseModel):
    store_name:       str
    retell_agent_id:  Optional[str] = None  # deprecated — always None post-OpenAI Realtime migration
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
    model:                str            # e.g. "gpt-realtime-1.5" / "gpt-realtime-mini"
    voice:                str            # e.g. "marin"
    system_prompt_loaded: bool           # True iff stores.system_prompt is non-empty
    last_call_at:         Optional[str]  # ISO timestamp of latest bridge_transactions row, or None


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _resolve_store(client: httpx.AsyncClient, owner_id: str) -> dict:
    resp = await client.get(
        f"{_REST}/stores",
        headers=_SUPABASE_HEADERS,
        params={
            "owner_id": f"eq.{owner_id}",
            "select":   "id,name,system_prompt,temporary_prompt,business_hours,custom_knowledge,is_active",
        },
    )
    stores = resp.json()
    if not stores:
        raise HTTPException(status_code=404, detail="Store not found")
    return stores[0]


async def _last_call_at(client: httpx.AsyncClient, store_id: str) -> Optional[str]:
    """Return ISO timestamp of the most recent bridge_transactions row for the
    given store, or None if no calls have been recorded.
    (해당 매장의 bridge_transactions 최신 행의 created_at — 없으면 None)
    """
    resp = await client.get(
        f"{_REST}/bridge_transactions",
        headers=_SUPABASE_HEADERS,
        params={
            "store_id": f"eq.{store_id}",
            "select":   "created_at",
            "order":    "created_at.desc",
            "limit":    "1",
        },
    )
    if resp.status_code != 200:
        return None
    rows = resp.json()
    return rows[0]["created_at"] if rows else None


# ── GET /api/store/voice-bot ──────────────────────────────────────────────────

@router.get("/voice-bot", response_model=VoiceBotSettings)
async def get_voice_bot(owner_id: str = Depends(get_tenant_id)):
    async with httpx.AsyncClient() as client:
        store = await _resolve_store(client, owner_id)
    return VoiceBotSettings(
        store_name=store["name"],
        retell_agent_id=None,
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
        retell_agent_id=None,
        system_prompt=row.get("system_prompt"),
        temporary_prompt=row.get("temporary_prompt"),
        business_hours=row.get("business_hours"),
        custom_knowledge=row.get("custom_knowledge"),
        is_active=row.get("is_active", True),
    )


# ── GET /api/store/voice-bot/agent-status ─────────────────────────────────────

@router.get("/voice-bot/agent-status", response_model=AgentStatus)
async def get_agent_status(owner_id: str = Depends(get_tenant_id)):
    """Return OpenAI Realtime agent status assembled from local DB (no external API).
    (외부 API 호출 없이 DB에서 직접 조립)
    """
    async with httpx.AsyncClient() as client:
        store = await _resolve_store(client, owner_id)
        last_at = await _last_call_at(client, store["id"])

    return AgentStatus(
        model=settings.openai_realtime_model,
        voice=settings.openai_realtime_voice,
        system_prompt_loaded=bool(store.get("system_prompt")),
        last_call_at=last_at,
    )
