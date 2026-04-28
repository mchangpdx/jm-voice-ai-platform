# Bridge Server — transactions repository TDD tests
# (Bridge Server — 트랜잭션 레포지토리 TDD 테스트)
#
# Repository layer wraps Supabase REST calls for bridge_transactions + bridge_events.
# All state mutations MUST go through advance_state(), which:
#   1. Validates via state_machine.transition() (raises InvalidTransition on bad edge)
#   2. PATCHes the row
#   3. APPENDS a row to bridge_events with the audit dict
#
# Direct UPDATE on state column is forbidden by convention (and a future RLS policy).

import pytest
from unittest.mock import AsyncMock, patch


STORE_ID    = "7c425fcb-91c7-4eb7-982a-591c094ba9c9"
TXN_UUID    = "11111111-2222-3333-4444-555555555555"
CALL_LOG_ID = "call_test_abc"


# ── create_transaction ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_transaction_inserts_with_pending_state():
    from app.services.bridge import transactions as t

    fake_resp = AsyncMock()
    fake_resp.status_code = 201
    fake_resp.json = lambda: [{"id": TXN_UUID, "state": "pending"}]

    with patch("app.services.bridge.transactions.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.post = AsyncMock(return_value=fake_resp)

        txn = await t.create_transaction(
            store_id        = STORE_ID,
            vertical        = "restaurant",
            pos_object_type = "reservation",
            pos_object_id   = "RES-100",
            customer_phone  = "+15037079566",
            customer_name   = "Michael Chang",
            total_cents     = 0,
            call_log_id     = CALL_LOG_ID,
        )

    assert txn["id"] == TXN_UUID
    assert txn["state"] == "pending"

    # First POST call is the bridge_transactions INSERT (second is bridge_events)
    sent = instance.post.call_args_list[0].kwargs["json"]
    assert sent["store_id"]        == STORE_ID
    assert sent["vertical"]        == "restaurant"
    assert sent["pos_object_type"] == "reservation"
    assert sent["pos_object_id"]   == "RES-100"
    assert sent["customer_phone"]  == "+15037079566"
    assert sent["total_cents"]     == 0
    assert sent["state"]           == "pending"
    assert sent["call_log_id"]     == CALL_LOG_ID


@pytest.mark.asyncio
async def test_create_transaction_validates_vertical():
    """Reject unknown verticals at the application layer (DB has CHECK too)."""
    from app.services.bridge import transactions as t

    with pytest.raises(ValueError, match="vertical"):
        await t.create_transaction(
            store_id="x", vertical="banking",
            pos_object_type="x", pos_object_id="x",
            customer_phone="+1503", customer_name="x",
            total_cents=0,
        )


@pytest.mark.asyncio
async def test_create_transaction_writes_creation_event():
    """A 'transaction_created' row in bridge_events must be written alongside."""
    from app.services.bridge import transactions as t

    fake_txn_resp = AsyncMock()
    fake_txn_resp.status_code = 201
    fake_txn_resp.json = lambda: [{"id": TXN_UUID, "state": "pending"}]

    fake_evt_resp = AsyncMock()
    fake_evt_resp.status_code = 201
    fake_evt_resp.json = lambda: [{"id": 1}]

    with patch("app.services.bridge.transactions.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.post = AsyncMock(side_effect=[fake_txn_resp, fake_evt_resp])

        await t.create_transaction(
            store_id=STORE_ID, vertical="restaurant",
            pos_object_type="reservation", pos_object_id="R1",
            customer_phone="+1503", customer_name="X",
            total_cents=0,
        )

    # Two POSTs: transactions then events
    assert instance.post.call_count == 2
    evt_payload = instance.post.call_args_list[1].kwargs["json"]
    assert evt_payload["event_type"] == "transaction_created"
    assert evt_payload["transaction_id"] == TXN_UUID
    assert evt_payload["to_state"] == "pending"
    assert evt_payload["source"] in ("voice", "admin", "cron")


# ── advance_state ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_advance_state_valid_transition_patches_and_audits():
    from app.services.bridge import transactions as t

    fake_get = AsyncMock(); fake_get.status_code = 200
    fake_get.json = lambda: [{"id": TXN_UUID, "state": "pending"}]

    fake_patch = AsyncMock(); fake_patch.status_code = 200
    fake_patch.json = lambda: [{"id": TXN_UUID, "state": "payment_sent"}]

    fake_evt = AsyncMock(); fake_evt.status_code = 201
    fake_evt.json = lambda: [{"id": 99}]

    with patch("app.services.bridge.transactions.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get   = AsyncMock(return_value=fake_get)
        instance.patch = AsyncMock(return_value=fake_patch)
        instance.post  = AsyncMock(return_value=fake_evt)

        result = await t.advance_state(
            transaction_id = TXN_UUID,
            to_state       = "payment_sent",
            source         = "voice",
            actor          = "tool_call:create_reservation",
        )

    assert result["state"] == "payment_sent"

    # PATCH must hit the right id
    patch_kwargs = instance.patch.call_args.kwargs
    assert patch_kwargs["json"]["state"] == "payment_sent"

    # Event row written
    evt_payload = instance.post.call_args.kwargs["json"]
    assert evt_payload["event_type"] == "state_transition"
    assert evt_payload["from_state"] == "pending"
    assert evt_payload["to_state"]   == "payment_sent"
    assert evt_payload["transaction_id"] == TXN_UUID


@pytest.mark.asyncio
async def test_advance_state_rejects_invalid_transition_with_no_db_change():
    """Invalid edge (canceled → paid) → InvalidTransition; no PATCH, no event."""
    from app.services.bridge import transactions as t
    from app.services.bridge.state_machine import InvalidTransition

    fake_get = AsyncMock(); fake_get.status_code = 200
    fake_get.json = lambda: [{"id": TXN_UUID, "state": "canceled"}]

    with patch("app.services.bridge.transactions.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get   = AsyncMock(return_value=fake_get)
        instance.patch = AsyncMock()
        instance.post  = AsyncMock()

        with pytest.raises(InvalidTransition):
            await t.advance_state(
                transaction_id=TXN_UUID,
                to_state="paid",
                source="webhook",
                actor="maverick",
            )

        instance.patch.assert_not_called()
        instance.post.assert_not_called()


@pytest.mark.asyncio
async def test_advance_state_idempotent_self_transition_writes_noop_event():
    """paid → paid is allowed (replay-safe) and writes noop=true event but skips PATCH."""
    from app.services.bridge import transactions as t

    fake_get = AsyncMock(); fake_get.status_code = 200
    fake_get.json = lambda: [{"id": TXN_UUID, "state": "paid"}]

    fake_evt = AsyncMock(); fake_evt.status_code = 201
    fake_evt.json = lambda: [{"id": 1}]

    with patch("app.services.bridge.transactions.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get   = AsyncMock(return_value=fake_get)
        instance.patch = AsyncMock()
        instance.post  = AsyncMock(return_value=fake_evt)

        await t.advance_state(
            transaction_id=TXN_UUID,
            to_state="paid",
            source="webhook",
            actor="maverick_replay",
        )

        # No PATCH for self-transition
        instance.patch.assert_not_called()
        # But event WAS written with noop flag
        evt_payload = instance.post.call_args.kwargs["json"]
        assert evt_payload["payload_json"].get("noop") is True


@pytest.mark.asyncio
async def test_advance_state_raises_when_transaction_not_found():
    from app.services.bridge import transactions as t

    fake_get = AsyncMock(); fake_get.status_code = 200
    fake_get.json = lambda: []  # empty result

    with patch("app.services.bridge.transactions.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_get)

        with pytest.raises(LookupError, match="not found"):
            await t.advance_state(
                transaction_id="MISSING",
                to_state="paid",
                source="webhook",
                actor="x",
            )


# ── get_transaction ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_transaction_returns_row():
    from app.services.bridge import transactions as t

    fake_get = AsyncMock(); fake_get.status_code = 200
    fake_get.json = lambda: [{"id": TXN_UUID, "state": "paid", "store_id": STORE_ID}]

    with patch("app.services.bridge.transactions.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_get)

        row = await t.get_transaction(TXN_UUID)
        assert row["id"]    == TXN_UUID
        assert row["state"] == "paid"


@pytest.mark.asyncio
async def test_get_transaction_returns_none_when_missing():
    from app.services.bridge import transactions as t

    fake_get = AsyncMock(); fake_get.status_code = 200
    fake_get.json = lambda: []

    with patch("app.services.bridge.transactions.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_get)

        assert await t.get_transaction("nope") is None
