"""Loyverse direct push — wizard's "POS sync" without Back Office input.

Generalizes `scripts/auto_loyverse_setup.py` (single-store JM Pizza
script) into an async service the wizard's `/finalize` can call after
DB seed. Three POST waves:
  1. categories — `category_id` referenced by every item
  2. modifiers  — `modifier_ids` per-item array; `size` is excluded
                  because Loyverse treats size as an item variant
                  (option1) rather than a modifier
  3. items      — `variants` carry size pricing, `modifier_ids`
                  carry cross-cutting groups (crust, cheese, sauce)

Idempotent via name + handle dedupe: re-running on the same Loyverse
account skips existing entries instead of duplicating. Rate-limited
to ~10 req/sec (Loyverse cap is 300/5min ≈ 1/sec, but we batch with
short waits between item POSTs).
(auto_loyverse_setup.py async 일반화 — 3-wave POST, idempotent)

Plan: docs/strategic-research/2026-05-11_menu-onboarding-automation/
section 4 Phase 4 loyverse_api_pusher.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)


_LOYVERSE_API = "https://api.loyverse.com/v1.0"
_ITEM_POST_SLEEP_S = 0.10  # rate-limit cushion between item creates


class LoyversePushError(RuntimeError):
    """Raised when a Loyverse POST returns non-2xx.

    Carries the failing path + status + first 300 chars of response
    so the wizard can show the operator exactly which step blew up
    (and whether it's a 401 to refresh token, or a 400 to fix payload).
    (path + status + body — operator-actionable error)
    """
    def __init__(self, path: str, status: int, body: str) -> None:
        super().__init__(f"Loyverse POST /{path} failed: {status} {body[:300]}")
        self.path = path
        self.status = status
        self.body = body


def _headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type":  "application/json",
    }


async def _get(
    client:       httpx.AsyncClient,
    access_token: str,
    path:         str,
    params:       Optional[dict] = None,
) -> dict:
    resp = await client.get(
        f"{_LOYVERSE_API}/{path}",
        headers=_headers(access_token),
        params=params or {},
    )
    if resp.status_code != 200:
        raise LoyversePushError(path, resp.status_code, resp.text)
    return resp.json() or {}


async def _post(
    client:       httpx.AsyncClient,
    access_token: str,
    path:         str,
    body:         dict,
) -> dict:
    resp = await client.post(
        f"{_LOYVERSE_API}/{path}",
        headers=_headers(access_token),
        json=body,
    )
    if resp.status_code not in (200, 201):
        raise LoyversePushError(path, resp.status_code, resp.text)
    return resp.json() or {}


def _item_modifier_codes(item: dict, groups: dict[str, dict]) -> list[str]:
    """Which non-size groups apply to this item, by category.

    Mirrors the wizard's modifier-group editor: groups with
    `applies_to_categories=None` apply to everything; groups with a
    list apply only when the item's category is included. Size is
    excluded because Loyverse handles it as a variant.
    (size 제외, applies_to_categories 기반 매칭)
    """
    cat = item.get("category")
    if not cat:
        return []
    out = []
    for code, g in groups.items():
        if code == "size":
            continue
        applies = g.get("applies_to_categories")
        if applies and cat not in applies:
            continue
        out.append(code)
    return out


# ── Wave 1: categories ──────────────────────────────────────────────────────

async def push_categories(
    client:       httpx.AsyncClient,
    access_token: str,
    items_yaml:   list[dict],
) -> dict[str, str]:
    """POST one category per unique `category` value in items.

    Returns {yaml_category_id: loyverse_uuid}. Existing categories
    (matched by display name) are skipped so the operator can re-run
    push without duplicating. Display name is the category id with
    underscores→spaces and titlecase — operator can rename in Loyverse
    Back Office afterward.
    (yaml category → Loyverse uuid, 이름 기반 dedupe)
    """
    listing = await _get(client, access_token, "categories", {"limit": "100"})
    by_name = {c["name"]: c["id"] for c in (listing.get("categories") or [])}

    unique_cats: list[str] = []
    seen: set[str] = set()
    for it in items_yaml:
        cat = it.get("category")
        if cat and cat not in seen:
            seen.add(cat)
            unique_cats.append(cat)

    out: dict[str, str] = {}
    for cat_id in unique_cats:
        display = cat_id.replace("_", " ").title()
        if display in by_name:
            out[cat_id] = by_name[display]
            continue
        resp = await _post(client, access_token, "categories", {
            "name":  display,
            "color": "GREY",
        })
        out[cat_id] = resp["id"]
    return out


# ── Wave 2: modifiers (size excluded — handled as variant) ──────────────────

async def push_modifiers(
    client:             httpx.AsyncClient,
    access_token:       str,
    groups:             dict[str, dict],
    loyverse_store_id:  str,
) -> dict[str, str]:
    """POST one modifier per group in modifier_groups.yaml except 'size'.

    Loyverse modifiers without a `stores` array are invisible in the
    cashier app (Back Office shows them but in-store ordering can't
    use them). Assigning the store id at create-time makes them usable
    immediately.
    (stores 배열 필수 — cashier UI 노출 위해)
    """
    listing = await _get(client, access_token, "modifiers", {"limit": "100"})
    by_name = {m["name"]: m["id"] for m in (listing.get("modifiers") or [])}

    out: dict[str, str] = {}
    for code, g in groups.items():
        if code == "size":
            continue
        display = code.replace("_", " ").title()
        if display in by_name:
            out[code] = by_name[display]
            continue
        options = []
        for opt in (g.get("options") or []):
            # Loyverse modifier_options rejects negative prices.
            price = max(0.0, float(opt.get("price_delta", 0.0)))
            options.append({"name": opt["en"], "price": round(price, 2)})
        resp = await _post(client, access_token, "modifiers", {
            "name":             display,
            "modifier_options": options,
            "stores":           [loyverse_store_id],
        })
        out[code] = resp["id"]
    return out


# ── Wave 3: items + variants ────────────────────────────────────────────────

async def push_items(
    client:            httpx.AsyncClient,
    access_token:      str,
    items_yaml:        list[dict],
    groups:            dict[str, dict],
    category_id_map:   dict[str, str],
    modifier_id_map:   dict[str, str],
    loyverse_store_id: str,
) -> dict[str, dict[str, Any]]:
    """POST one item per yaml item; size variants become Loyverse variants.

    Returns {yaml_id: {"id": loyverse_item_id, "variants": {sku: variant_id}}}.
    Existing items (matched by `handle` = yaml id) are skipped. Each
    new item POST waits `_ITEM_POST_SLEEP_S` before the next so a 24-
    item menu finishes in ~3s while staying well under the 300/5min cap.
    (handle 기반 dedupe, 10 req/sec 안정 cap)
    """
    listing = await _get(client, access_token, "items", {"limit": "200"})
    by_handle = {i["handle"]: i for i in (listing.get("items") or [])}

    size_group = groups.get("size") or {}
    size_options = size_group.get("options") or []

    out: dict[str, dict[str, Any]] = {}
    for item in items_yaml:
        yaml_id = item["id"]
        if yaml_id in by_handle:
            existing = by_handle[yaml_id]
            out[yaml_id] = {
                "id":       existing["id"],
                "variants": {v["sku"]: v["variant_id"] for v in existing.get("variants", [])},
            }
            continue

        name = item["en"]
        cat_id = category_id_map.get(item.get("category") or "")
        base_price = float(item.get("base_price") or 0.0)
        mod_codes = _item_modifier_codes(item, groups)
        mod_ids = [modifier_id_map[c] for c in mod_codes if c in modifier_id_map]
        has_size = "size" in [c for c, g in groups.items()
                              if not g.get("applies_to_categories")
                              or item.get("category") in g.get("applies_to_categories", [])]

        # Build variants array — size variants when applicable, else single.
        # (size 적용 시 사이즈별 variant, 그 외 단일 variant)
        variants_body: list[dict[str, Any]] = []
        if has_size and size_options:
            for opt in size_options:
                vp = base_price + float(opt.get("price_delta", 0.0))
                variants_body.append({
                    "variant_name":         opt["en"],
                    "sku":                  f"{yaml_id}_{opt['id']}",
                    "option1_value":        opt["en"],
                    "default_pricing_type": "FIXED",
                    "default_price":        round(vp, 2),
                    "stores": [{
                        "store_id":           loyverse_store_id,
                        "pricing_type":       "FIXED",
                        "price":              round(vp, 2),
                        "available_for_sale": True,
                    }],
                })
        else:
            variants_body.append({
                "variant_name":         "",
                "sku":                  yaml_id,
                "default_pricing_type": "FIXED",
                "default_price":        round(base_price, 2),
                "stores": [{
                    "store_id":           loyverse_store_id,
                    "pricing_type":       "FIXED",
                    "price":              round(base_price, 2),
                    "available_for_sale": True,
                }],
            })

        body: dict[str, Any] = {
            "item_name":      name,
            "handle":         yaml_id,
            "category_id":    cat_id,
            "modifier_ids":   mod_ids,
            "description":    item.get("notes_en"),
            "track_stock":    False,
            "sold_by_weight": False,
            "is_composite":   False,
            "use_production": False,
            "variants":       variants_body,
        }
        if has_size:
            body["option1_name"] = "Size"

        resp = await _post(client, access_token, "items", body)
        out[yaml_id] = {
            "id":       resp["id"],
            "variants": {v["sku"]: v["variant_id"] for v in (resp.get("variants") or [])},
        }
        await asyncio.sleep(_ITEM_POST_SLEEP_S)
    return out


# ── Orchestrator ────────────────────────────────────────────────────────────

async def _ping_loyverse(access_token: str) -> tuple[bool, str]:
    """Read-only Loyverse connectivity check. Returns (ok, message).

    GET /merchant is the cheapest authenticated call — confirms the
    access_token is valid and the API is reachable, without listing
    any store data. Used by the dry-run path.
    (Loyverse read-only ping — token + 연결 확인)
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{_LOYVERSE_API}/merchant",
                headers=_headers(access_token),
            )
            if resp.status_code == 200:
                merchant = (resp.json() or {}).get("name") or "unknown"
                return (True, f"loyverse reachable (merchant: {merchant!r})")
            return (False, f"loyverse responded {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        return (False, f"loyverse ping failed: {type(exc).__name__}: {exc}")


def _dry_run_push_counts(
    menu_yaml:            dict,
    modifier_groups_yaml: dict,
) -> dict[str, int]:
    """Counts a real push would produce, without hitting Loyverse.

    Categories = unique non-empty `category` across items. Modifiers
    counts non-`size` groups (size becomes a Loyverse variant, not a
    modifier). Items is items_yaml length.
    (dry-run counts — 실제 push와 동일 logic)
    """
    items = menu_yaml.get("items") or []
    groups = (modifier_groups_yaml or {}).get("groups") or {}
    unique_cats = {it.get("category") for it in items if it.get("category")}
    non_size_groups = sum(1 for code in groups if code != "size")
    return {
        "categories": len(unique_cats),
        "modifiers":  non_size_groups,
        "items":      len(items),
    }


async def push_menu_to_loyverse(
    *,
    access_token:         str,
    loyverse_store_id:    str,
    menu_yaml:            dict,
    modifier_groups_yaml: dict,
    dry_run:              bool = False,
) -> dict[str, Any]:
    """Run the three-wave push end-to-end. Returns counts + id maps.

    Caller is expected to fetch loyverse_store_id via
    `LoyversePOSAdapter.fetch_loyverse_store_id()` once at /finalize
    time and pass it in. Wave failures raise LoyversePushError without
    cleanup — Loyverse doesn't expose bulk DELETE and operators want
    to retry from the failed wave anyway (avoid losing successful work).
    (실패 시 cleanup 안 함 — 부분 push 유지, 재시도 가능)
    """
    if dry_run:
        ok, ping_msg = await _ping_loyverse(access_token)
        return {
            "dry_run":       True,
            "counts":        _dry_run_push_counts(menu_yaml, modifier_groups_yaml),
            "loyverse_ping": {"ok": ok, "message": ping_msg},
        }

    items_yaml = menu_yaml.get("items") or []
    groups     = (modifier_groups_yaml or {}).get("groups") or {}

    async with httpx.AsyncClient(timeout=30) as client:
        cat_map = await push_categories(client, access_token, items_yaml)
        mod_map = await push_modifiers(client, access_token, groups, loyverse_store_id)
        item_map = await push_items(
            client, access_token, items_yaml, groups,
            cat_map, mod_map, loyverse_store_id,
        )

    return {
        "counts": {
            "categories": len(cat_map),
            "modifiers":  len(mod_map),
            "items":      len(item_map),
        },
        "category_id_map": cat_map,
        "modifier_id_map": mod_map,
        "item_id_map":     item_map,
    }
