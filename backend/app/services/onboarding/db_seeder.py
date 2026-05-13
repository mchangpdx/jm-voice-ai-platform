"""DB seeder — turns a menu.yaml + modifier_groups.yaml dict into rows.

Generalizes the pattern in `scripts/setup_jm_pizza.py` (which was a
single-store, single-vertical seeder). The wizard's `/finalize` calls
`finalize_store()` after the operator approves the yaml in Step 5; we
write through the supabase REST API exactly like `setup_jm_pizza.py`
did, so this stays consistent with the rest of the backend's data
access pattern.

Items↔modifier_groups wiring is auto-derived from
`modifier_groups.applies_to_categories` so the caller doesn't need to
pre-compute it. The wizard step that lets the operator pick which
group applies where (Step 4 in the UI) edits `applies_to_categories`
inline — the seeder reads it verbatim.
(seeder — menu.yaml + modifier_groups.yaml dict → DB rows. category 기반 wire)

Plan: docs/strategic-research/2026-05-11_menu-onboarding-automation/
section 4 Phase 4 + 5.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)


_REST = f"{settings.supabase_url}/rest/v1"
_H = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type":  "application/json",
}


# ── REST helpers ────────────────────────────────────────────────────────────

async def _post(
    client:    httpx.AsyncClient,
    path:      str,
    payload:   list[dict] | dict,
    conflict:  Optional[str] = None,
) -> list[dict]:
    """Supabase REST POST with optional on_conflict merge.

    Returns the response rows. Raises RuntimeError on non-2xx so the
    caller (orchestrator) can rollback gracefully. We deliberately do
    NOT swallow errors here — finalize is a multi-step write that
    needs to know exactly which step failed.
    (REST POST — 실패 시 예외 throw, orchestrator가 rollback)
    """
    headers = {**_H, "Prefer": "return=representation"}
    if conflict:
        headers["Prefer"] = "resolution=merge-duplicates,return=representation"
    params = {"on_conflict": conflict} if conflict else None
    resp = await client.post(f"{_REST}/{path}", headers=headers, json=payload, params=params)
    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"supabase POST /{path} failed: {resp.status_code} {resp.text[:300]}"
        )
    return resp.json() if resp.content else []


async def _patch(
    client:  httpx.AsyncClient,
    path:    str,
    params:  dict,
    payload: dict,
) -> None:
    """Supabase REST PATCH (used for stores.menu_cache rebuild)."""
    resp = await client.patch(f"{_REST}/{path}", headers=_H, params=params, json=payload)
    if resp.status_code not in (200, 204):
        raise RuntimeError(
            f"supabase PATCH /{path} failed: {resp.status_code} {resp.text[:300]}"
        )


async def _get(
    client: httpx.AsyncClient,
    path:   str,
    params: Optional[dict] = None,
) -> list[dict]:
    resp = await client.get(f"{_REST}/{path}", headers=_H, params=params or {})
    if resp.status_code != 200:
        raise RuntimeError(
            f"supabase GET /{path} failed: {resp.status_code} {resp.text[:300]}"
        )
    return resp.json()


# ── Seeders ─────────────────────────────────────────────────────────────────

async def seed_store(
    client:  httpx.AsyncClient,
    payload: dict[str, Any],
) -> str:
    """Insert a new stores row. Returns the generated store_id (uuid4)."""
    rows = await _post(client, "stores", payload)
    if not rows:
        raise RuntimeError("stores INSERT returned no rows")
    return rows[0]["id"]


async def seed_menu_items(
    client:        httpx.AsyncClient,
    store_id:      str,
    items_yaml:    list[dict[str, Any]],
) -> dict[str, str]:
    """Insert menu_items. Returns {yaml_id: db_row_id} for the wire step.

    Items inherit a placeholder UUID for variant_id / pos_item_id when
    the source didn't supply real POS ids — the Loyverse webhook will
    overwrite these on first sync, same pattern setup_jm_pizza.py uses.
    Stock defaults to 9999 (sentinel for "untracked"), matching the
    Loyverse `track_stock=false` workaround that ships with the
    bridge adapter.
    (placeholder UUID — webhook이 덮어쓸 예정. stock=9999 sentinel)
    """
    rows = []
    for item in items_yaml:
        rows.append({
            "store_id":       store_id,
            "name":           item["en"],
            "price":          float(item.get("base_price") or 0.0),
            "category":       item.get("category"),
            "allergens":      item.get("base_allergens", []),
            "dietary_tags":   item.get("base_dietary", []),
            "is_available":   True,
            "stock_quantity": 9999,
            "variant_id":     str(uuid.uuid4()),
            "pos_item_id":    str(uuid.uuid4()),
            "sku":            item["id"],
            "description":    item.get("notes_en"),
            "raw":            {"yaml_id": item["id"], "placeholder_ids": True},
        })
    inserted = await _post(client, "menu_items", rows)
    return {r["sku"]: r["id"] for r in inserted}


async def seed_modifier_groups(
    client:    httpx.AsyncClient,
    store_id:  str,
    groups:    dict[str, dict[str, Any]],
) -> dict[str, str]:
    """Upsert modifier_groups. Returns {group_code: db_row_id}."""
    if not groups:
        return {}
    payload = []
    for sort_idx, (code, g) in enumerate(groups.items(), start=1):
        payload.append({
            "store_id":     store_id,
            "code":         code,
            "display_name": code.replace("_", " ").title(),
            "is_required":  bool(g.get("required", False)),
            "min_select":   g.get("min", 0),
            "max_select":   g.get("max", 1),
            "sort_order":   sort_idx,
        })
    rows = await _post(client, "modifier_groups", payload, conflict="store_id,code")
    return {r["code"]: r["id"] for r in rows}


async def seed_modifier_options(
    client:     httpx.AsyncClient,
    group_ids:  dict[str, str],
    groups:     dict[str, dict[str, Any]],
) -> int:
    """Upsert modifier_options for every group, returns inserted count."""
    if not group_ids:
        return 0
    payload = []
    for code, g in groups.items():
        gid = group_ids.get(code)
        if not gid:
            continue
        for sort_idx, opt in enumerate(g.get("options") or [], start=1):
            payload.append({
                "group_id":        gid,
                "code":            opt["id"],
                "display_name":    opt["en"],
                "price_delta":     float(opt.get("price_delta", 0.0)),
                "allergen_add":    opt.get("allergen_add", []),
                "allergen_remove": opt.get("allergen_remove", []),
                "sort_order":      sort_idx,
                "is_default":      bool(opt.get("default", False)),
                "is_available":    True,
            })
    if not payload:
        return 0
    inserted = await _post(client, "modifier_options", payload, conflict="group_id,code")
    return len(inserted)


async def wire_items_to_modifier_groups(
    client:     httpx.AsyncClient,
    item_ids:   dict[str, str],
    group_ids:  dict[str, str],
    items_yaml: list[dict[str, Any]],
    groups:     dict[str, dict[str, Any]],
) -> int:
    """Auto-wire items↔groups using `applies_to_categories`.

    Setup_jm_pizza.py read an explicit `modifier_groups` list on each
    item; here we derive it from `applies_to_categories` so the wizard
    operator only edits one place (the modifier group's category list)
    and the wiring follows. Items with no category match no groups —
    standalone items (Soda, Brownie) get zero modifier rows, exactly
    what we want.
    (applies_to_categories → menu_item_modifier_groups wire)
    """
    payload = []
    for item in items_yaml:
        db_id = item_ids.get(item["id"])
        if not db_id:
            continue
        item_cat = item.get("category")
        if not item_cat:
            continue
        for sort_idx, (group_code, g) in enumerate(groups.items(), start=1):
            applies = g.get("applies_to_categories")
            # No applies_to_categories means the group is universal.
            if applies and item_cat not in applies:
                continue
            gid = group_ids.get(group_code)
            if not gid:
                continue
            payload.append({
                "menu_item_id": db_id,
                "group_id":     gid,
                "sort_order":   sort_idx,
            })
    if not payload:
        return 0
    inserted = await _post(
        client,
        "menu_item_modifier_groups",
        payload,
        conflict="menu_item_id,group_id",
    )
    return len(inserted)


async def rebuild_menu_cache(
    client:   httpx.AsyncClient,
    store_id: str,
) -> str:
    """Build the formatted text cache the voice agent reads at call-start.

    Same layout as setup_jm_pizza.py's update_menu_cache — grouped by
    category, "Cheese Pizza ($18, $26)" lines when an item has size
    variants in modifier_options. For now we just re-emit a flat
    list; the voice agent's existing menu_cache parser handles either.
    (menu_cache 재구성 — 단순 flat list로 시작)
    """
    items = await _get(client, "menu_items", {
        "store_id":     f"eq.{store_id}",
        "is_available": "eq.true",
        "select":       "name,price,category",
        "order":        "category.asc,name.asc",
    })
    lines: list[str] = []
    last_cat: Optional[str] = None
    for it in items:
        cat = it.get("category") or "other"
        if cat != last_cat:
            lines.append(f"\n## {cat.replace('_', ' ').title()}")
            last_cat = cat
        lines.append(f"- {it['name']}  ${float(it['price']):.2f}")
    cache_text = "\n".join(lines).strip()
    await _patch(
        client,
        "stores",
        {"id": f"eq.{store_id}"},
        {"menu_cache": cache_text},
    )
    return cache_text


# ── Orchestrator ────────────────────────────────────────────────────────────

async def _ping_supabase() -> tuple[bool, str]:
    """Read-only Supabase connectivity check. Returns (ok, message).

    Used by the dry-run path so the wizard can show "Supabase OK" or
    "Supabase unreachable — fix env before retrying without dry-run"
    instead of pretending success. The query is intentionally trivial
    (HEAD-equivalent — no row data returned) so a misconfigured
    service-role token surfaces as 401 immediately.
    (read-only ping — dry-run에서 사용자 안내)
    """
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                f"{_REST}/stores",
                headers=_H,
                params={"select": "id", "limit": "1"},
            )
            if resp.status_code == 200:
                return (True, f"supabase reachable (returned {len(resp.json())} row)")
            return (False, f"supabase responded {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        return (False, f"supabase ping failed: {type(exc).__name__}: {exc}")


def _dry_run_finalize(
    store_name:           str,
    phone_number:         str,
    manager_phone:        str,
    vertical:             str,
    menu_yaml:            dict[str, Any],
    modifier_groups_yaml: dict[str, Any],
    pos_provider:         Optional[str],
    pos_api_key:          Optional[str],
) -> dict[str, Any]:
    """Build the payload counts that real finalize_store would produce —
    without touching Supabase. Lets the wizard preview wire counts +
    operator instructions before committing to a real write.

    Wire count is computed the same way wire_items_to_modifier_groups
    does it (category match against applies_to_categories) so the
    operator sees the actual number Loyverse will create.
    (dry-run — payload shape + 카운트만, DB write 없음)
    """
    items = menu_yaml.get("items") or []
    groups = (modifier_groups_yaml or {}).get("groups") or {}
    wire_count = 0
    for item in items:
        item_cat = item.get("category")
        if not item_cat:
            continue
        for code, g in groups.items():
            applies = g.get("applies_to_categories")
            if applies and item_cat not in applies:
                continue
            wire_count += 1
    options_count = sum(
        len(g.get("options") or []) for g in groups.values()
    )
    return {
        "store_id":  "DRY-RUN-NO-DB-WRITE",
        "dry_run":   True,
        "counts": {
            "menu_items":        len(items),
            "modifier_groups":   len(groups),
            "modifier_options":  options_count,
            "item_group_wires":  wire_count,
            "menu_cache_chars":  0,  # rebuild_menu_cache reads DB — N/A in dry-run
        },
        "next_steps": [
            f"DRY-RUN: no DB rows created. Re-run with dry_run=false to actually onboard "
            f"\"{store_name}\" at {phone_number}.",
            f"In Twilio Console, set the voice webhook for {phone_number} → "
            f"https://jmtechone.ngrok.app/twilio/voice/inbound",
            f"Manager escalation phone: {manager_phone}",
            "Verification call recommended after real finalize completes.",
        ],
    }


async def finalize_store(
    *,
    store_name:           str,
    phone_number:         str,
    manager_phone:        str,
    vertical:             str,
    menu_yaml:            dict[str, Any],
    modifier_groups_yaml: dict[str, Any],
    owner_id:             Optional[str] = None,
    agency_id:            Optional[str] = None,
    pos_provider:         Optional[str] = None,
    pos_api_key:          Optional[str] = None,
    system_prompt:        Optional[str] = None,
    dry_run:              bool = False,
) -> dict[str, Any]:
    """Run all seeders end-to-end. Returns {store_id, counts, next_steps}.

    dry_run=True returns the same shape but skips every DB write and
    adds a `supabase_ping` field so the operator knows whether a
    real run would even reach Supabase. Safe for in-flight / airport
    sanity checks where touching prod isn't acceptable.
    (dry_run — DB write 없이 payload + supabase ping)

    The Loyverse webhook re-sync is left to the operator (the existing
    `freeze` mechanism in services/sync/freeze.py is the gate). PHONE_TO_STORE
    is intentionally NOT modified here — the user's session memory
    forbids in-code routing changes; the response surfaces the
    one-line edit the operator needs to make instead.
    (PHONE_TO_STORE 직접 수정 안 함 — response.next_steps에 안내)
    """
    if dry_run:
        ok, ping_message = await _ping_supabase()
        out = _dry_run_finalize(
            store_name           = store_name,
            phone_number         = phone_number,
            manager_phone        = manager_phone,
            vertical             = vertical,
            menu_yaml            = menu_yaml,
            modifier_groups_yaml = modifier_groups_yaml,
            pos_provider         = pos_provider,
            pos_api_key          = pos_api_key,
        )
        out["supabase_ping"] = {"ok": ok, "message": ping_message}
        return out

    items_yaml = menu_yaml.get("items") or []
    groups     = (modifier_groups_yaml or {}).get("groups") or {}

    store_payload: dict[str, Any] = {
        "name":             store_name,
        "industry":         vertical,
        "business_type":    vertical,
        "phone":            phone_number,
        "is_active":        True,
    }
    if owner_id:
        store_payload["owner_id"] = owner_id
    if agency_id:
        store_payload["agency_id"] = agency_id
    if pos_provider:
        store_payload["pos_provider"] = pos_provider
    if pos_api_key:
        store_payload["pos_api_key"] = pos_api_key
    if system_prompt:
        store_payload["system_prompt"] = system_prompt

    async with httpx.AsyncClient(timeout=30) as client:
        store_id    = await seed_store(client, store_payload)
        item_ids    = await seed_menu_items(client, store_id, items_yaml)
        group_ids   = await seed_modifier_groups(client, store_id, groups)
        opt_count   = await seed_modifier_options(client, group_ids, groups)
        wire_count  = await wire_items_to_modifier_groups(
            client, item_ids, group_ids, items_yaml, groups,
        )
        cache_chars = len(await rebuild_menu_cache(client, store_id))

    return {
        "store_id":           store_id,
        "counts": {
            "menu_items":        len(item_ids),
            "modifier_groups":   len(group_ids),
            "modifier_options":  opt_count,
            "item_group_wires":  wire_count,
            "menu_cache_chars":  cache_chars,
        },
        # Phone routing is now handled by realtime_voice._resolve_store_id
        # via stores.phone DB lookup (5-min cache) — the operator no longer
        # has to edit code to activate a new store. Twilio webhook URL
        # is the one remaining manual step until a Twilio API client lands.
        # (routing 자동화 — Twilio webhook URL만 manual)
        "next_steps": [
            f"In Twilio Console, set the voice webhook for {phone_number} → "
            f"https://jmtechone.ngrok.app/twilio/voice/inbound",
            f"Manager escalation phone: {manager_phone} "
            f"(adjust if different per store)",
            f"Place a verification call to {phone_number} from a Google Voice US number "
            "to confirm the greeting + menu_cache. The store is reachable immediately — "
            "no uvicorn restart needed.",
        ],
    }
