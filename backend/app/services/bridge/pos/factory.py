# Bridge Server — POS adapter factory (store-based selection)
# (Bridge Server — POS 어댑터 팩토리: 매장별 선택)
#
# Each store has a pos_provider column ('supabase' | 'loyverse' | 'quantic' | future).
# Factory reads it from the stores table and instantiates the right adapter.
# Default is 'supabase' so existing stores keep working with no migration.
#
# Per-store API keys: stores.pos_api_key column (optional). If absent, adapter
# falls back to global env (settings.loyverse_api_key etc.). This supports both:
#   - Single-tenant deployment (one global key)
#   - Multi-tenant deployment (per-store keys, env left empty)

from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.core.config import settings
from app.services.bridge.pos.base import POSAdapter
from app.services.bridge.pos.loyverse import LoyversePOSAdapter
from app.services.bridge.pos.supabase import SupabasePOSAdapter

log = logging.getLogger(__name__)

_SUPABASE_HEADERS = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
}
_REST = f"{settings.supabase_url}/rest/v1"

# Registered providers — adding a new POS = one entry + one adapter file
_PROVIDERS: dict[str, str] = {
    "supabase": "SupabasePOSAdapter",
    "loyverse": "LoyversePOSAdapter",
    # 'quantic' arrives with white-label deal
}


async def _read_store_pos_config(store_id: str) -> Optional[dict]:
    """Read the store's pos_provider + pos_api_key from the stores table.
    (stores 테이블에서 매장의 pos_provider + pos_api_key 조회)
    """
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get(
            f"{_REST}/stores",
            headers=_SUPABASE_HEADERS,
            params={
                "id":     f"eq.{store_id}",
                "select": "id,pos_provider,pos_api_key",
                "limit":  "1",
            },
        )
    if resp.status_code != 200:
        return None
    rows = resp.json()
    return rows[0] if rows else None


async def get_pos_adapter_for_store(store_id: str) -> POSAdapter:
    """Resolve the POS adapter for a given store from its pos_provider config.
    (매장의 pos_provider 설정을 읽어 적절한 POS 어댑터 반환)

    Raises:
        LookupError: store not found
        ValueError:  unknown pos_provider value
    """
    cfg = await _read_store_pos_config(store_id)
    if cfg is None:
        raise LookupError(f"store {store_id!r} not found")

    provider = (cfg.get("pos_provider") or "supabase").lower()
    api_key  = cfg.get("pos_api_key")  # may be None (uses global setting)

    if provider == "supabase":
        return SupabasePOSAdapter()
    if provider == "loyverse":
        return LoyversePOSAdapter(api_key=api_key) if api_key else LoyversePOSAdapter()
    if provider not in _PROVIDERS:
        raise ValueError(f"unknown pos_provider: {provider!r}; allowed={list(_PROVIDERS)}")

    # Should never reach here — _PROVIDERS keys are exhaustive above
    raise ValueError(f"unknown pos_provider: {provider!r}")
