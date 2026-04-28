# Bridge Server — Loyverse POS Adapter
# (Bridge Server — Loyverse POS 어댑터)
#
# Phase 2-B.1.5 — second concrete adapter, validates the abstraction.
# Loyverse REST API: https://api.loyverse.com/v1.0
# Auth: Authorization: Bearer {api_key}
#
# Endpoints used:
#   POST /receipts            — create order ("receipt" in Loyverse vocabulary)
#   GET  /items?limit=250     — fetch full menu (variants + per-store inventory)
#   GET  /categories          — fetch category names
#   GET  /receipts/{id}       — fetch receipt by id
#
# Important: Loyverse has NO reservation object. For reservation creation,
# adapter raises NotSupported and orchestration falls back to SupabasePOSAdapter
# (handled in pos/factory.py via vertical-aware routing).
#
# Per-store API keys: Loyverse is one-key-per-tenant. The factory passes the
# store-specific key from stores.pos_api_key column; falls back to global
# settings.loyverse_api_key (multi-tenant: per-store; single-tenant: global).

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.services.bridge.pos.base import POSAdapter

log = logging.getLogger(__name__)


class NotSupported(Exception):
    """Raised when an operation is not supported by this POS provider.
    (이 POS 공급자가 지원하지 않는 작업 호출 시 예외)
    """
    pass


class LoyversePOSAdapter(POSAdapter):
    """Loyverse cloud POS adapter — read menu, write receipts, read receipts.
    (Loyverse 클라우드 POS 어댑터 — 메뉴 조회, 영수증 생성, 영수증 조회)
    """

    SUPPORTS_MENU_SYNC    = True
    SUPPORTS_INVENTORY    = True
    SUPPORTS_PAYMENT_SYNC = True

    def __init__(self, api_key: Optional[str] = None) -> None:
        # Per-store key takes precedence; fall back to global env setting
        # (매장별 키 우선; 글로벌 환경 설정 fallback)
        self.api_key  = api_key or settings.loyverse_api_key
        self.api_url  = settings.loyverse_api_url.rstrip("/")
        if not self.api_key:
            raise ValueError(
                "LoyversePOSAdapter requires api_key (per-store or via "
                "settings.loyverse_api_key)"
            )

    # ── Internal HTTP helpers ───────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type":  "application/json",
        }

    # ── POSAdapter implementation ───────────────────────────────────────────

    async def create_pending(
        self,
        *,
        vertical: str,
        store_id: str,
        payload:  dict[str, Any],
    ) -> str:
        # Loyverse has no concept of a 'reservation' — bail out so the factory
        # can fall back to SupabasePOSAdapter for reservation flows.
        # (Loyverse는 예약 객체가 없음 — 예약 흐름은 SupabasePOSAdapter로 fallback)
        if payload.get("pos_object_type") == "reservation":
            raise NotSupported(
                "Loyverse does not support reservation objects. "
                "Route reservation creation through SupabasePOSAdapter."
            )

        # Build a minimal Loyverse /receipts payload. The full Loyverse schema
        # is rich (taxes, tips, store_id, customer_id) — kept lean here to
        # validate the adapter contract; richer mapping arrives with Phase 2-B
        # (create_order tool) once we have the full menu sync online.
        # (최소 페이로드로 어댑터 계약 검증 — 풍부한 매핑은 Phase 2-B에서 추가)
        receipt_payload: dict[str, Any] = {
            "source": "JM Voice AI",
            "note":   f"customer={payload.get('customer_name', '')} "
                      f"phone={payload.get('customer_phone', '')}",
            "line_items": [
                {
                    "variant_id": item.get("variant_id"),
                    "quantity":   item.get("quantity", 1),
                    "price":      item.get("price"),
                }
                for item in payload.get("items", [])
            ],
        }

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.api_url}/receipts",
                headers=self._headers(),
                json=receipt_payload,
            )
        if resp.status_code not in (200, 201):
            log.error("Loyverse create_pending %s: %s",
                      resp.status_code, resp.text[:200] if hasattr(resp, "text") else "")
            raise RuntimeError(f"Loyverse /receipts {resp.status_code}")

        body = resp.json()
        # Prefer receipt_number (human-readable, e.g. "1-1042") over UUID id
        return str(body.get("receipt_number") or body.get("id") or "")

    async def mark_paid(
        self,
        *,
        vertical:  str,
        object_id: str,
        extra:     Optional[dict[str, Any]] = None,
    ) -> None:
        # Loyverse receipts are paid at POST time — POS already considers the
        # receipt 'closed'. mark_paid is a no-op for the v1 contract.
        # When we wire real-money flows (Maverick), payment confirmation will
        # patch the receipt with payment_method='JMAI Pay' via a future endpoint.
        # (Loyverse 영수증은 POST 시점에 paid — v1 계약에서는 no-op)
        return None

    async def get_object(
        self,
        *,
        vertical:  str,
        object_id: str,
    ) -> Optional[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.api_url}/receipts/{object_id}",
                headers=self._headers(),
            )
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            return None
        return resp.json()

    # ── Loyverse-specific (capability: SUPPORTS_MENU_SYNC) ──────────────────

    async def fetch_menu(self) -> list[dict[str, Any]]:
        """Fetch full menu from Loyverse, normalized to vendor-agnostic shape.
        (Loyverse 메뉴를 공급자 독립적 형태로 정규화하여 조회)

        Pattern ported from jm-saas-platform/src/services/pos/loyverseAdapter.js.
        Each item carries a list of variants; each variant has price + stock_quantity
        from the primary store entry. Categories/inventory endpoints are separate
        calls handled elsewhere.
        """
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.api_url}/items?limit=250",
                headers=self._headers(),
            )
        if resp.status_code != 200:
            log.error("Loyverse fetch_menu %s", resp.status_code)
            return []

        raw_items = resp.json().get("items", []) or []
        normalized: list[dict[str, Any]] = []
        for item in raw_items:
            variants_raw = item.get("variants", []) or []
            variants: list[dict[str, Any]] = []
            for v in variants_raw:
                stores_arr = v.get("stores") or []
                store_entry = stores_arr[0] if stores_arr else {}
                price = store_entry.get("price") if store_entry.get("price") is not None \
                        else (v.get("default_price") or 0)
                stock = store_entry.get("in_stock") if store_entry.get("in_stock") is not None \
                        else 0
                variants.append({
                    "variant_id":     v.get("variant_id"),
                    "sku":            v.get("sku"),
                    "option_value":   v.get("option1_value"),
                    "price":          float(price),
                    "stock_quantity": int(stock),
                })

            normalized.append({
                "pos_item_id": item.get("id"),
                "name":        item.get("item_name"),
                "category_id": item.get("category_id"),
                "color":       item.get("color"),
                "description": item.get("description"),
                "variants":    variants,
            })
        return normalized
