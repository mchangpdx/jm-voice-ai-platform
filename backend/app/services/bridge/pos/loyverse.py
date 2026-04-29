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
from datetime import datetime, timezone
from typing import Any, Optional

import httpx


def _now_iso() -> str:
    # ISO-8601 UTC, used as Loyverse receipt_date (영수증 생성 시각)
    return datetime.now(timezone.utc).isoformat()

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
        raw_key = api_key if api_key is not None else settings.loyverse_api_key
        # Strip embedded control chars (\n \r \t) AND surrounding whitespace —
        # Supabase-stored keys frequently arrive with stray control characters
        # that survive plain .strip() because they sit in the middle of the value.
        # Without this, httpx raises "Invalid character in header content".
        # (DB 저장 키에 흔한 제어 문자 제거 — 헤더 오류 방지)
        cleaned = "".join(
            ch for ch in str(raw_key) if ch not in ("\n", "\r", "\t")
        ).strip()
        self.api_key = cleaned
        self.api_url = settings.loyverse_api_url.rstrip("/")
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

    async def fetch_payment_type_id(self) -> Optional[str]:
        """GET /payment_types — return the first active payment_type id, used to
        populate receipt.payments[].payment_type_id (required by Loyverse).
        (영수증 필수 필드 payment_type_id 조회 — 첫 활성 항목 반환)
        """
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.api_url}/payment_types",
                headers=self._headers(),
            )
        if resp.status_code != 200:
            log.error("Loyverse fetch_payment_type_id %s", resp.status_code)
            return None
        items = resp.json().get("payment_types") or []
        return str(items[0]["id"]) if items else None

    async def fetch_loyverse_store_id(self) -> Optional[str]:
        """GET /stores — return the Loyverse internal store id (NOT our Supabase
        UUID). Required on every receipt. Multi-store accounts return [0] today.
        (Loyverse 내부 매장 ID 조회 — 영수증 필수, Supabase UUID와 다름)
        """
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.api_url}/stores",
                headers=self._headers(),
            )
        if resp.status_code != 200:
            log.error("Loyverse fetch_loyverse_store_id %s", resp.status_code)
            return None
        items = resp.json().get("stores") or []
        return str(items[0]["id"]) if items else None

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

        # ── Pre-fetch required Loyverse references ──────────────────────────
        # Both calls hit Loyverse but are cheap (small payloads, can be cached
        # later in stores.pos_meta column). Done sequentially today; can be
        # gathered concurrently with asyncio.gather once we add a result cache.
        # (영수증 필수 참조 정보 사전 조회 — 추후 캐시 가능)
        payment_type_id  = await self.fetch_payment_type_id()
        loyverse_store_id = await self.fetch_loyverse_store_id()

        # ── Build line_items + canonical total from items[] ────────────────
        # line_items is the truth source for total_money. orderData.total_cents
        # is intentionally ignored — caller-supplied totals were the source of
        # MISMATCHED_PAYMENT errors in the legacy Node demo.
        # (line_items가 truth source — 호출자 total은 무시)
        line_items: list[dict[str, Any]] = []
        running_total: float = 0.0
        for item in payload.get("items", []) or []:
            qty   = int(item.get("quantity", 1))
            price = float(item.get("price", 0))
            li: dict[str, Any] = {
                "item_name":         item.get("name", ""),
                "quantity":          qty,
                "price":             round(price, 2),
                "gross_total_money": round(price * qty, 2),
                "total_money":       round(price * qty, 2),
            }
            if item.get("variant_id"): li["variant_id"] = item["variant_id"]
            if item.get("item_id"):    li["item_id"]    = item["item_id"]
            line_items.append(li)
            running_total += price * qty

        total_money = round(running_total, 2)

        # ── Build full receipt body ─────────────────────────────────────────
        receipt_payload: dict[str, Any] = {
            "store_id":     loyverse_store_id,
            "receipt_type": "SALE",
            "source":       "JM Voice AI",
            "receipt_date": _now_iso(),
            "note":         f"customer={payload.get('customer_name', '')} "
                            f"phone={payload.get('customer_phone', '')}",
            "line_items":   line_items,
            "total_money":  total_money,
            "payments": [
                {
                    "payment_type_id": payment_type_id,
                    "money_amount":    total_money,
                }
            ],
        }
        # Optional external order reference for traceability back to bridge_transactions
        if payload.get("bridge_tx_id"):
            receipt_payload["order"] = str(payload["bridge_tx_id"])

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

    async def _fetch_inventory_map(self, client: httpx.AsyncClient) -> dict[str, int]:
        """Pull the authoritative on-hand quantities from Loyverse /inventory.
        (권위 있는 재고 소스 — /items의 in_stock은 stale일 수 있음)

        Returns variant_id → in_stock dict. Empty dict on failure (caller falls
        back to whatever /items reported — not fatal).
        """
        try:
            resp = await client.get(
                f"{self.api_url}/inventory?limit=250",
                headers=self._headers(),
            )
        except Exception as exc:
            log.warning("Loyverse /inventory unreachable: %s", exc)
            return {}
        if resp.status_code != 200:
            log.warning("Loyverse /inventory %s — falling back to /items in_stock",
                        resp.status_code)
            return {}
        levels = resp.json().get("inventory_levels") or []
        out: dict[str, int] = {}
        for lvl in levels:
            vid = lvl.get("variant_id")
            qty = lvl.get("in_stock")
            if vid is None or qty is None:
                continue
            try:
                out[vid] = int(qty)
            except (TypeError, ValueError):
                continue
        return out

    async def fetch_menu(self) -> list[dict[str, Any]]:
        """Fetch full menu from Loyverse, normalized to vendor-agnostic shape.
        (Loyverse 메뉴를 공급자 독립적 형태로 정규화하여 조회)

        Calls /items for catalog + /inventory for authoritative on-hand counts.
        /items.in_stock is best-effort and frequently stale or 0 when an item
        was created without "Track stock" toggled on. /inventory is the truth
        source — /inventory takes priority when both are present.
        (재고 소스 우선순위: /inventory > /items.in_stock — 정확성 보장)
        """
        async with httpx.AsyncClient(timeout=10) as client:
            items_resp = await client.get(
                f"{self.api_url}/items?limit=250",
                headers=self._headers(),
            )
            if items_resp.status_code != 200:
                log.error("Loyverse fetch_menu %s", items_resp.status_code)
                return []
            inventory_map = await self._fetch_inventory_map(client)

        raw_items = items_resp.json().get("items", []) or []
        normalized: list[dict[str, Any]] = []
        for item in raw_items:
            variants_raw = item.get("variants", []) or []
            variants: list[dict[str, Any]] = []
            for v in variants_raw:
                stores_arr = v.get("stores") or []
                store_entry = stores_arr[0] if stores_arr else {}
                price = store_entry.get("price") if store_entry.get("price") is not None \
                        else (v.get("default_price") or 0)
                # Stock priority: /inventory authoritative → /items embedded → 0
                # (재고 우선순위: /inventory → /items embedded → 0)
                vid = v.get("variant_id")
                if vid in inventory_map:
                    stock = inventory_map[vid]
                else:
                    stock = store_entry.get("in_stock") if store_entry.get("in_stock") is not None \
                            else 0
                variants.append({
                    "variant_id":     vid,
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
