"""Retry POS injection for transactions stuck in PAID without pos_object_id.
Runs the same code path the pay_link route uses on success, but only for
already-PAID rows whose first POS attempt failed (typically Loyverse 400).
After the truncate-bridge_tx_id fix, those rows can complete cleanly.
(결제 성공했지만 POS injection 실패한 tx 복구 — pay_link route와 동일 경로)

Usage:
    .venv/bin/python scripts/retry_pos_injection.py            # all eligible
    .venv/bin/python scripts/retry_pos_injection.py <tx_id>    # one tx only
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

from app.core.config import settings
from app.services.bridge import transactions
from app.services.bridge.pay_link import fetch_order_items_for_tx
from app.services.bridge.pos.factory import get_pos_adapter_for_store
from app.services.bridge.state_machine import State

H = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
}
BASE = f"{settings.supabase_url}/rest/v1"


async def fetch_paid_no_pos(only_tx: str | None = None) -> list[dict]:
    params = {
        "select":        "id,store_id,state,pos_object_id,vertical,customer_name,customer_phone,total_cents,created_at",
        "state":         "eq.paid",
        "pos_object_id": "is.null",
        "order":         "created_at.asc",
    }
    if only_tx:
        params["id"] = f"eq.{only_tx}"
        params.pop("state", None)
        params.pop("pos_object_id", None)
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{BASE}/bridge_transactions", headers=H, params=params)
    if r.status_code != 200:
        print(f"fetch error {r.status_code}: {r.text[:200]}")
        return []
    rows = r.json()
    if only_tx and rows and rows[0].get("pos_object_id"):
        print(f"Tx {only_tx} already has pos_object_id={rows[0]['pos_object_id']!r} — nothing to do")
        return []
    return rows


async def retry_one(txn: dict) -> None:
    tx_id    = txn["id"]
    store_id = txn["store_id"]
    print(f"\n--- retry tx={tx_id} store={store_id} ---")

    items = await fetch_order_items_for_tx(tx_id)
    if not items:
        print("  (no items_json found — skipping)")
        return

    adapter = await get_pos_adapter_for_store(store_id)
    try:
        pos_object_id = await adapter.create_pending(
            vertical=txn.get("vertical", "restaurant"),
            store_id=store_id,
            payload={
                "pos_object_type": "order",
                "items":           items,
                "customer_name":   txn.get("customer_name") or "",
                "customer_phone":  txn.get("customer_phone") or "",
                "bridge_tx_id":    tx_id,
            },
        )
    except Exception as exc:
        print(f"  POS create_pending FAILED: {exc!r}")
        return

    print(f"  POS create_pending OK pos_object_id={pos_object_id!r}")
    await transactions.set_pos_object_id(tx_id, pos_object_id)

    try:
        await adapter.mark_paid(
            vertical=txn.get("vertical", "restaurant"),
            object_id=pos_object_id,
        )
        print("  mark_paid OK")
    except Exception as exc:
        print(f"  mark_paid skipped: {exc!r}")

    await transactions.advance_state(
        transaction_id = tx_id,
        to_state       = State.FULFILLED,
        source         = "script",
        actor          = "retry_pos_injection",
    )
    print("  advanced PAID -> FULFILLED")


async def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    rows = await fetch_paid_no_pos(only)
    if not rows:
        print("No eligible transactions.")
        return
    print(f"Found {len(rows)} eligible tx(s):")
    for t in rows:
        print(f"  {t['id']}  ${t['total_cents']/100:.2f}  {t['customer_name']!r}")
    for t in rows:
        await retry_one(t)


if __name__ == "__main__":
    asyncio.run(main())
