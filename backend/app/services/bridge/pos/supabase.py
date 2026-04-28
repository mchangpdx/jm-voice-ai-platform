# Bridge Server — Supabase POS Adapter
# (Bridge Server — Supabase POS 어댑터)
#
# Implements POSAdapter against our own Supabase tables:
#   restaurant    → reservations
#   home_services → jobs
#   beauty        → appointments
#   auto_repair   → service_orders
#
# This adapter is the "system of record" today. After the Quantic white-label
# deal closes, QuanticPOSAdapter will replace it for restaurants. The other
# 3 verticals stay on Supabase (no Quantic equivalent for home/beauty/auto).
#
# Per-vertical "paid" status name varies by table convention — see _STATUS_PAID.

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.services.bridge.pos.base import POSAdapter

log = logging.getLogger(__name__)

# Vertical → table name (matches existing schema)
_TABLE: dict[str, str] = {
    "restaurant":    "reservations",
    "home_services": "jobs",
    "beauty":        "appointments",
    "auto_repair":   "service_orders",
}

# Vertical → status string used for "paid / confirmed" state
# (existing seed data uses 'confirmed' for reservations, 'scheduled' for jobs, etc.)
_STATUS_PAID: dict[str, str] = {
    "restaurant":    "confirmed",
    "home_services": "scheduled",
    "beauty":        "confirmed",
    "auto_repair":   "scheduled",
}

_SUPABASE_HEADERS = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type":  "application/json",
}
_REST = f"{settings.supabase_url}/rest/v1"


class SupabasePOSAdapter(POSAdapter):
    """Persists POS objects in our own Supabase tables.
    (자체 Supabase 테이블에 POS 객체 저장)
    """

    # ── Pure helpers (testable without I/O) ────────────────────────────────

    def _table_for_vertical(self, vertical: str) -> str:
        if vertical not in _TABLE:
            raise ValueError(f"unknown vertical: {vertical!r}; allowed={sorted(_TABLE)}")
        return _TABLE[vertical]

    def _paid_status_for_vertical(self, vertical: str) -> str:
        if vertical not in _STATUS_PAID:
            raise ValueError(f"unknown vertical: {vertical!r}")
        return _STATUS_PAID[vertical]

    # ── POSAdapter implementation ──────────────────────────────────────────

    async def create_pending(
        self,
        *,
        vertical: str,
        store_id: str,
        payload:  dict[str, Any],
    ) -> str:
        table = self._table_for_vertical(vertical)
        row = {**payload, "store_id": store_id, "status": "pending"}
        # Strip empty values (Supabase prefers explicit NULL over empty string)
        row = {k: v for k, v in row.items() if v is not None and v != ""}

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{_REST}/{table}",
                headers={**_SUPABASE_HEADERS, "Prefer": "return=representation"},
                json=row,
            )
        if resp.status_code not in (200, 201):
            log.error("Supabase POS create_pending failed %s: %s",
                      resp.status_code, resp.text[:200])
            raise RuntimeError(f"create_pending failed: {resp.status_code}")

        rows = resp.json()
        new_id = rows[0]["id"] if rows else None
        if new_id is None:
            raise RuntimeError("create_pending returned no id")

        return str(new_id)

    async def mark_paid(
        self,
        *,
        vertical:  str,
        object_id: str,
        extra:     Optional[dict[str, Any]] = None,
    ) -> None:
        table  = self._table_for_vertical(vertical)
        status = self._paid_status_for_vertical(vertical)

        patch_body: dict[str, Any] = {"status": status}
        if extra:
            patch_body.update(extra)

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.patch(
                f"{_REST}/{table}",
                headers={**_SUPABASE_HEADERS, "Prefer": "return=minimal"},
                params={"id": f"eq.{object_id}"},
                json=patch_body,
            )
        if resp.status_code not in (200, 204):
            log.error("Supabase POS mark_paid failed %s: %s",
                      resp.status_code, resp.text[:200])
            raise RuntimeError(f"mark_paid failed: {resp.status_code}")

    async def get_object(
        self,
        *,
        vertical:  str,
        object_id: str,
    ) -> Optional[dict[str, Any]]:
        table = self._table_for_vertical(vertical)
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_REST}/{table}",
                headers=_SUPABASE_HEADERS,
                params={"id": f"eq.{object_id}", "limit": "1"},
            )
        if resp.status_code != 200:
            return None
        rows = resp.json()
        return rows[0] if rows else None
