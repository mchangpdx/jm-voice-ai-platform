# B1 — flows.modify_order TDD
# (B1 — flows.modify_order 테스트 우선 작성)
#
# Per spec backend/docs/specs/B1_modify_order.md.
#
# modify_order(store_id, args, caller_phone_e164, call_log_id) replaces
# the items on a single in-flight transaction (state ∈ {PENDING,
# PAYMENT_SENT}) for the same caller phone, recomputes total_cents,
# writes one audit row, and returns a result dict for the Voice Engine.
#
# Tests written BEFORE the implementation — all should fail until
# flows.modify_order lands.

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


CALLER = "+15035551234"
STORE  = "STORE_UUID"


def _tx(state="pending", lane="pay_first", items=None, total=599):
    """Helper — one in-flight bridge_transactions row in the shape the
    bridge probe returns."""
    return {
        "id":             "tx-1",
        "store_id":       STORE,
        "vertical":       "restaurant",
        "pos_object_type":"order",
        "pos_object_id":  "",
        "customer_phone": CALLER,
        "customer_name":  "Aaron Chang",
        "state":          state,
        "payment_lane":   lane,
        "total_cents":    total,
        "items_json":     items or [{"name":"Cafe Latte","quantity":1,"price":5.99}],
    }


# Catalog rows resolve_items_against_menu would return. Match.py shape:
# {name, quantity, variant_id, item_id, price, stock_quantity, missing,
#  sufficient_stock}.
def _resolved(name="Cafe Latte", qty=1, price=5.99, missing=False, ok_stock=True):
    return {
        "name":             name,
        "quantity":         qty,
        "variant_id":       f"vr-{name.lower().replace(' ','-')}",
        "item_id":          f"it-{name.lower().replace(' ','-')}",
        "price":            price,
        "stock_quantity":   None,
        "missing":          missing,
        "sufficient_stock": ok_stock,
    }


# ── T6: empty items list ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_modify_order_rejects_empty_items():
    from app.services.bridge.flows import modify_order

    res = await modify_order(
        store_id=STORE,
        args={"items": []},
        caller_phone_e164=CALLER,
        call_log_id=None,
    )
    assert res["success"] is False
    assert res["reason"] == "validation_failed"
    assert res["ai_script_hint"] == "validation_failed"


# ── T2: no in-flight target ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_modify_order_rejects_when_no_target():
    """Probe returns nothing → reason=no_order_to_modify, no DB writes."""
    from app.services.bridge import flows

    with patch.object(flows, "_find_modifiable_order",
                      new=AsyncMock(return_value=None)) as probe, \
         patch.object(flows, "transactions") as txns_mod:
        res = await flows.modify_order(
            store_id=STORE,
            args={"items": [{"name":"Cafe Latte","quantity":1}]},
            caller_phone_e164=CALLER,
            call_log_id=None,
        )

    assert res["success"] is False
    assert res["reason"] == "no_order_to_modify"
    assert res["ai_script_hint"] == "modify_no_target"
    probe.assert_awaited_once()
    txns_mod.update_items_and_total.assert_not_called()
    txns_mod.append_audit.assert_not_called()


# ── T3: tx exists but already fired / paid / fulfilled ───────────────────────

@pytest.mark.parametrize("late_state", ["fired_unpaid", "paid", "fulfilled"])
@pytest.mark.asyncio
async def test_modify_order_refuses_after_kitchen_fired(late_state):
    """An order that already left PENDING/PAYMENT_SENT can't be modified."""
    from app.services.bridge import flows

    with patch.object(flows, "_find_modifiable_order",
                      new=AsyncMock(return_value=_tx(state=late_state))), \
         patch.object(flows, "transactions") as txns_mod:
        res = await flows.modify_order(
            store_id=STORE,
            args={"items": [{"name":"Cafe Latte","quantity":1}]},
            caller_phone_e164=CALLER,
            call_log_id=None,
        )

    assert res["success"] is False
    assert res["reason"] == "order_too_late"
    assert res["ai_script_hint"] == "modify_too_late"
    txns_mod.update_items_and_total.assert_not_called()
    txns_mod.append_audit.assert_not_called()


# ── T4: unknown menu item ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_modify_order_refuses_unknown_item():
    """resolve_items_against_menu marks an item missing → reason=unknown_item."""
    from app.services.bridge import flows

    with patch.object(flows, "_find_modifiable_order",
                      new=AsyncMock(return_value=_tx())), \
         patch.object(flows, "resolve_items_against_menu",
                      new=AsyncMock(return_value=[
                          _resolved("unicorn pie", missing=True),
                      ])), \
         patch.object(flows, "transactions") as txns_mod:
        res = await flows.modify_order(
            store_id=STORE,
            args={"items": [{"name":"unicorn pie","quantity":1}]},
            caller_phone_e164=CALLER,
            call_log_id=None,
        )

    assert res["success"] is False
    assert res["reason"] == "unknown_item"
    assert res["ai_script_hint"] == "rejected"
    assert res["unavailable"][0]["name"] == "unicorn pie"
    txns_mod.update_items_and_total.assert_not_called()


# ── T5: sold-out item ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_modify_order_refuses_sold_out_item():
    from app.services.bridge import flows

    with patch.object(flows, "_find_modifiable_order",
                      new=AsyncMock(return_value=_tx())), \
         patch.object(flows, "resolve_items_against_menu",
                      new=AsyncMock(return_value=[
                          _resolved("Cafe Latte", ok_stock=False),
                      ])), \
         patch.object(flows, "transactions") as txns_mod:
        res = await flows.modify_order(
            store_id=STORE,
            args={"items": [{"name":"Cafe Latte","quantity":99}]},
            caller_phone_e164=CALLER,
            call_log_id=None,
        )

    assert res["success"] is False
    assert res["reason"] == "sold_out"
    assert res["ai_script_hint"] == "rejected"
    txns_mod.update_items_and_total.assert_not_called()


# ── T1: happy path — items + total updated, audit row appended ───────────────

@pytest.mark.asyncio
async def test_modify_order_happy_path_updates_items_and_audit():
    """The flagship case: PENDING tx, two new items resolve cleanly,
    bridge updates items_json + total_cents and writes one audit row."""
    from app.services.bridge import flows

    target = _tx()
    new_resolved = [
        _resolved("Cafe Latte", qty=2, price=5.99),  # 1198
        _resolved("Croissant",  qty=1, price=5.99),  #  599
    ]

    with patch.object(flows, "_find_modifiable_order",
                      new=AsyncMock(return_value=target)), \
         patch.object(flows, "resolve_items_against_menu",
                      new=AsyncMock(return_value=new_resolved)), \
         patch.object(flows, "transactions") as txns_mod:
        txns_mod.update_items_and_total = AsyncMock()
        txns_mod.append_audit            = AsyncMock()

        res = await flows.modify_order(
            store_id=STORE,
            args={"items": [
                {"name":"Cafe Latte","quantity":2},
                {"name":"Croissant","quantity":1},
            ]},
            caller_phone_e164=CALLER,
            call_log_id="call_X",
        )

    assert res["success"] is True
    assert res["transaction_id"] == "tx-1"
    assert res["lane"]           == "pay_first"
    assert res["state"]          == "pending"
    assert res["total_cents"]    == 1797       # (5.99 * 2 + 5.99) → cents
    assert res["ai_script_hint"] == "modify_success"

    # bridge persisted the new items + total exactly once
    txns_mod.update_items_and_total.assert_awaited_once()
    update_kwargs = txns_mod.update_items_and_total.await_args.kwargs
    assert update_kwargs["transaction_id"] == "tx-1"
    assert update_kwargs["items"] == new_resolved
    assert update_kwargs["total_cents"] == 1797

    # audit row carries old + new for forensic traceability
    txns_mod.append_audit.assert_awaited_once()
    audit_kwargs = txns_mod.append_audit.await_args.kwargs
    assert audit_kwargs["event_type"] == "items_modified"
    assert audit_kwargs["actor"]      == "tool_call:modify_order"
    assert audit_kwargs["source"]     == "voice"
    payload = audit_kwargs["payload"]
    assert payload["old_total"]    == 599
    assert payload["new_total"]    == 1797
    assert payload["new_items"]    == new_resolved


# ── T7: no-op short-circuit — same items list ───────────────────────────────

@pytest.mark.asyncio
async def test_modify_order_noop_when_items_unchanged_skips_db_writes():
    """Replaying modify with identical items short-circuits to
    ai_script_hint='modify_noop' WITHOUT writing UPDATE / audit rows.
    Without this defense the voice agent gets stuck in an infinite
    recital loop on benign acks — verified live in call_feede2b9..."""
    from app.services.bridge import flows

    same_items = [_resolved("Cafe Latte", qty=1, price=5.99)]
    target = _tx(items=same_items, total=599)

    with patch.object(flows, "_find_modifiable_order",
                      new=AsyncMock(return_value=target)), \
         patch.object(flows, "resolve_items_against_menu",
                      new=AsyncMock(return_value=same_items)), \
         patch.object(flows, "transactions") as txns_mod:
        txns_mod.update_items_and_total = AsyncMock()
        txns_mod.append_audit            = AsyncMock()

        res = await flows.modify_order(
            store_id=STORE,
            args={"items":[{"name":"Cafe Latte","quantity":1}]},
            caller_phone_e164=CALLER,
            call_log_id=None,
        )

    assert res["success"] is True
    assert res["ai_script_hint"] == "modify_noop"
    assert res["total_cents"]    == 599
    # No-op path explicitly skips persistence so reflexive AUTO-fire
    # loops can't pile up redundant audit rows.
    txns_mod.update_items_and_total.assert_not_called()
    txns_mod.append_audit.assert_not_called()


# ── T8: real change still writes UPDATE + audit ──────────────────────────────

@pytest.mark.asyncio
async def test_modify_order_writes_when_items_actually_change():
    """Sanity inverse of T7: a different quantity is a real change and
    must hit the DB."""
    from app.services.bridge import flows

    target = _tx(items=[_resolved("Cafe Latte", qty=1, price=5.99)], total=599)
    new_items = [_resolved("Cafe Latte", qty=2, price=5.99)]   # qty ↑

    with patch.object(flows, "_find_modifiable_order",
                      new=AsyncMock(return_value=target)), \
         patch.object(flows, "resolve_items_against_menu",
                      new=AsyncMock(return_value=new_items)), \
         patch.object(flows, "transactions") as txns_mod:
        txns_mod.update_items_and_total = AsyncMock()
        txns_mod.append_audit            = AsyncMock()

        res = await flows.modify_order(
            store_id=STORE,
            args={"items":[{"name":"Cafe Latte","quantity":2}]},
            caller_phone_e164=CALLER,
            call_log_id=None,
        )

    assert res["success"] is True
    assert res["ai_script_hint"] == "modify_success"
    assert res["total_cents"]    == 1198
    txns_mod.update_items_and_total.assert_awaited_once()
    txns_mod.append_audit.assert_awaited_once()
