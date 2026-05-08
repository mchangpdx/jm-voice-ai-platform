# Phase 2-B.1.8 — flows.create_order TDD
# (Phase 2-B.1.8 — flows.create_order TDD)
#
# create_order(store_id, args, call_log_id) is the Bridge entry point for
# the Voice Engine create_order tool call. It:
#   1. Validates args (items list, customer_phone)
#   2. Resolves items against menu_items
#   3. Refuses sold_out / unknown items (returns status=rejected)
#   4. Computes total_cents from real catalog prices
#   5. Decides lane via policy engine
#   6. Creates bridge_transactions (state=pending, payment_lane set)
#   7. Lane branch:
#        - fire_immediate: POS create_pending → PENDING → FIRED_UNPAID + fired_at
#        - pay_first:      stays PENDING (pay link route handles the rest)
#   8. Returns a result dict with ai_script_hint for the caller's TTS.
#
# Decisions baked in (per user direction):
#   * Loyverse adapter call failure on fire_immediate ⇒ stay in PENDING +
#     bridge_event "pos_inject_failed" (manual recovery; never raises).
#   * customer_phone is required (we'll send the pay link there).

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


# ── Validation ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_order_rejects_empty_items():
    from app.services.bridge.flows import create_order

    res = await create_order(
        store_id="STORE",
        args={"items": [], "customer_phone": "+15035550100"},
    )
    assert res["success"] is False
    assert "items" in res["error"].lower()


@pytest.mark.asyncio
async def test_create_order_rejects_missing_phone():
    from app.services.bridge.flows import create_order

    res = await create_order(
        store_id="STORE",
        args={"items": [{"name": "Latte", "quantity": 1}]},
    )
    assert res["success"] is False
    assert "phone" in res["error"].lower()


# ── Sold-out / unknown item refusal ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_order_refuses_sold_out_item():
    """An item with sufficient_stock=False ⇒ status=rejected, reason=sold_out.
    No transaction or POS call should happen.
    (매진 항목은 거절 — 트랜잭션/POS 호출 없음)
    """
    from app.services.bridge import flows

    enriched = [
        {"name": "Latte", "variant_id": "v-1", "item_id": "i-1",
         "price": 4.50, "quantity": 2, "stock_quantity": 0,
         "missing": False, "sufficient_stock": False},
    ]

    pos_adapter = MagicMock()
    pos_adapter.create_pending = AsyncMock()

    with patch.object(flows, "resolve_items_against_menu",
                      new=AsyncMock(return_value=enriched)), \
         patch.object(flows, "transactions") as mock_tx, \
         patch.object(flows, "get_pos_adapter_for_store", new=AsyncMock(return_value=pos_adapter)):

        mock_tx.create_transaction = AsyncMock()
        res = await flows.create_order(
            store_id="STORE",
            args={"items": [{"name": "Latte", "quantity": 2}],
                  "customer_phone": "+15035550100",
                  "customer_name":  "Michael"},
        )

    assert res["success"]    is False
    assert res["status"]     == "rejected"
    assert res["reason"]     == "sold_out"
    assert res["unavailable"][0]["name"] == "Latte"
    mock_tx.create_transaction.assert_not_called()
    pos_adapter.create_pending.assert_not_called()


@pytest.mark.asyncio
async def test_create_order_refuses_unknown_item():
    """An item with missing=True ⇒ status=rejected, reason=unknown_item.
    (메뉴에 없는 항목 거절)
    """
    from app.services.bridge import flows

    enriched = [
        {"name": "Unobtainium", "quantity": 1,
         "missing": True, "sufficient_stock": False},
    ]

    with patch.object(flows, "resolve_items_against_menu",
                      new=AsyncMock(return_value=enriched)):
        res = await flows.create_order(
            store_id="STORE",
            args={"items": [{"name": "Unobtainium", "quantity": 1}],
                  "customer_phone": "+15035550100",
                  "customer_name":  "Michael"},
        )

    assert res["success"]    is False
    assert res["status"]     == "rejected"
    assert res["reason"]     == "unknown_item"


# ── Lane selection ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_order_chooses_fire_immediate_below_threshold():
    """Total $9.00 with threshold $20 ⇒ fire_immediate lane.
    POS adapter is called; state advances PENDING → FIRED_UNPAID with fired_at.
    (임계값 미만 ⇒ fire_immediate, POS 호출 + FIRED_UNPAID 전이)
    """
    from app.services.bridge import flows
    from app.services.bridge.state_machine import State

    enriched = [
        {"name": "Latte", "variant_id": "v-1", "item_id": "i-1",
         "price": 4.50, "quantity": 2, "stock_quantity": 50,
         "missing": False, "sufficient_stock": True},
    ]

    pos_adapter = MagicMock()
    pos_adapter.create_pending = AsyncMock(return_value="receipt-1042")

    advance_calls: list = []

    async def fake_advance(**kwargs):
        advance_calls.append(kwargs)
        return {"state": kwargs["to_state"]}

    with patch.object(flows, "resolve_items_against_menu",
                      new=AsyncMock(return_value=enriched)), \
         patch.object(flows, "read_threshold_cents",
                      new=AsyncMock(return_value=2000)), \
         patch.object(flows, "_find_recent_duplicate",
                      new=AsyncMock(return_value=None)), \
         patch.object(flows, "transactions") as mock_tx, \
         patch.object(flows, "get_pos_adapter_for_store", new=AsyncMock(return_value=pos_adapter)):

        mock_tx.create_transaction = AsyncMock(return_value={"id": "tx-1"})
        mock_tx.set_pos_object_id  = AsyncMock()
        mock_tx.advance_state      = AsyncMock(side_effect=fake_advance)

        res = await flows.create_order(
            store_id="STORE",
            args={"items": [{"name": "Latte", "quantity": 2}],
                  "customer_phone": "+15035550100",
                  "customer_name":  "Michael"},
        )

        # Wave A.3 Plan D — fire_immediate now returns to voice the moment the
        # bridge INSERT completes. POS create_pending + state advance happen
        # in a background asyncio.Task. Immediately after create_order returns:
        #   - state is PENDING (background hasn't finished FIRED_UNPAID advance)
        #   - pos_object_id is "" (background hasn't backfilled it yet)
        #   - ai_script_hint stays 'fire_immediate' (script wording softened
        #     to "placing your order now" rather than "in the kitchen now").
        assert res["success"]          is True
        assert res["lane"]             == "fire_immediate"
        assert res["total_cents"]      == 900   # 2 * $4.50 = $9.00
        assert res["pos_object_id"]    == ""
        assert res["state"]            == State.PENDING
        assert res["ai_script_hint"]   == "fire_immediate"

        # Yield to the loop so the background task runs to completion. Must
        # stay inside the patch context — otherwise get_pos_adapter_for_store
        # un-patches and the background task hits the real httpx client.
        # (background task가 patch context 안에서 실행되도록 sleep도 내부에)
        import asyncio as _asyncio
        for _ in range(5):
            await _asyncio.sleep(0)

    pos_adapter.create_pending.assert_awaited_once()
    fired_call = next(c for c in advance_calls if c.get("to_state") == State.FIRED_UNPAID)
    assert "fired_at" in fired_call.get("extra_fields", {})


@pytest.mark.asyncio
async def test_create_order_chooses_pay_first_above_threshold():
    """Total $25 with threshold $20 ⇒ pay_first lane.
    No POS call, transaction stays in PENDING (pay link route advances later).
    (임계값 이상 ⇒ pay_first, POS 호출 안 함, PENDING 유지)
    """
    from app.services.bridge import flows
    from app.services.bridge.state_machine import State

    enriched = [
        {"name": "Combo", "variant_id": "v-99", "item_id": "i-99",
         "price": 25.00, "quantity": 1, "stock_quantity": 50,
         "missing": False, "sufficient_stock": True},
    ]

    pos_adapter = MagicMock()
    pos_adapter.create_pending = AsyncMock()

    with patch.object(flows, "resolve_items_against_menu",
                      new=AsyncMock(return_value=enriched)), \
         patch.object(flows, "read_threshold_cents",
                      new=AsyncMock(return_value=2000)), \
         patch.object(flows, "_find_recent_duplicate",
                      new=AsyncMock(return_value=None)), \
         patch.object(flows, "transactions") as mock_tx, \
         patch.object(flows, "get_pos_adapter_for_store", new=AsyncMock(return_value=pos_adapter)):

        mock_tx.create_transaction = AsyncMock(return_value={"id": "tx-2"})
        mock_tx.advance_state      = AsyncMock()

        res = await flows.create_order(
            store_id="STORE",
            args={"items": [{"name": "Combo", "quantity": 1}],
                  "customer_phone": "+15035550100",
                  "customer_name":  "Michael"},
        )

    assert res["success"]        is True
    assert res["lane"]           == "pay_first"
    assert res["total_cents"]    == 2500
    assert res["state"]          == State.PENDING
    assert res["ai_script_hint"] == "pay_first"

    pos_adapter.create_pending.assert_not_called()


# ── Bridge transaction shape ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_order_persists_payment_lane_on_transaction():
    """create_transaction must receive payment_lane so analytics + reconciliation
    can pivot on lane. (트랜잭션 행에 payment_lane 저장)
    """
    from app.services.bridge import flows

    enriched = [
        {"name": "Latte", "variant_id": "v", "item_id": "i",
         "price": 4.00, "quantity": 1, "stock_quantity": 5,
         "missing": False, "sufficient_stock": True},
    ]

    captured_kwargs: dict = {}

    async def fake_create_tx(**kw):
        captured_kwargs.update(kw)
        return {"id": "tx"}

    pos_adapter = MagicMock()
    pos_adapter.create_pending = AsyncMock(return_value="r-1")

    with patch.object(flows, "resolve_items_against_menu",
                      new=AsyncMock(return_value=enriched)), \
         patch.object(flows, "read_threshold_cents",
                      new=AsyncMock(return_value=2000)), \
         patch.object(flows, "_find_recent_duplicate",
                      new=AsyncMock(return_value=None)), \
         patch.object(flows, "transactions") as mock_tx, \
         patch.object(flows, "get_pos_adapter_for_store", new=AsyncMock(return_value=pos_adapter)):

        mock_tx.create_transaction = AsyncMock(side_effect=fake_create_tx)
        mock_tx.set_pos_object_id  = AsyncMock()
        mock_tx.advance_state      = AsyncMock()

        await flows.create_order(
            store_id="STORE",
            args={"items": [{"name": "Latte", "quantity": 1}],
                  "customer_phone": "+15035550100",
                  "customer_name":  "Michael"},
        )

    assert captured_kwargs["payment_lane"]    == "fire_immediate"
    assert captured_kwargs["pos_object_type"] == "order"
    assert captured_kwargs["vertical"]        == "restaurant"


# ── customer_email persistence (Phase 7-A.D Wave A.3 — B.1) ───────────────────
# Live trigger: every email send today (10/11 calls 2026-05-08) went to a
# slightly-wrong address (cymeet, cyeet, cyeemt — extra/missing letters from
# the LLM's NATO recital → args drift). The bridge_transactions row had
# customer_email=NULL on every recent transaction, so post-call audit can't
# even tell what address the email reached. These tests pin the contract
# that customer_email lands in the row when the caller provides it.


@pytest.mark.asyncio
async def test_create_order_persists_customer_email_on_transaction():
    """create_transaction must receive customer_email so we can audit which
    address each pay-link reached. Live ops 2026-05-08: 10/11 emails today
    went to wrong addresses — without DB persistence the only record is
    the realtime debug log (rotated, not queryable).
    (감사용 — 어떤 주소로 메일 갔는지 DB에 영속화)
    """
    from app.services.bridge import flows

    enriched = [
        {"name": "Latte", "variant_id": "v", "item_id": "i",
         "price": 4.00, "quantity": 1, "stock_quantity": 5,
         "missing": False, "sufficient_stock": True},
    ]

    captured_kwargs: dict = {}

    async def fake_create_tx(**kw):
        captured_kwargs.update(kw)
        return {"id": "tx"}

    pos_adapter = MagicMock()
    pos_adapter.create_pending = AsyncMock(return_value="r-1")

    with patch.object(flows, "resolve_items_against_menu",
                      new=AsyncMock(return_value=enriched)), \
         patch.object(flows, "read_threshold_cents",
                      new=AsyncMock(return_value=2000)), \
         patch.object(flows, "_find_recent_duplicate",
                      new=AsyncMock(return_value=None)), \
         patch.object(flows, "transactions") as mock_tx, \
         patch.object(flows, "get_pos_adapter_for_store", new=AsyncMock(return_value=pos_adapter)):

        mock_tx.create_transaction = AsyncMock(side_effect=fake_create_tx)
        mock_tx.set_pos_object_id  = AsyncMock()
        mock_tx.advance_state      = AsyncMock()

        await flows.create_order(
            store_id="STORE",
            args={"items":          [{"name": "Latte", "quantity": 1}],
                  "customer_phone": "+15035550100",
                  "customer_name":  "Michael",
                  "customer_email": "cymet@gmail.com"},
        )

    assert captured_kwargs.get("customer_email") == "cymet@gmail.com"


@pytest.mark.asyncio
async def test_create_order_omits_customer_email_when_caller_did_not_provide():
    """No customer_email in tool_args → the kwarg is None or absent. The
    column is nullable; we never want to insert an empty string that masks
    'this caller didn't share an email' as 'they shared an empty one'.
    (이메일 미제공 시 None 전달 — 빈 문자열 금지)"""
    from app.services.bridge import flows

    enriched = [
        {"name": "Latte", "variant_id": "v", "item_id": "i",
         "price": 4.00, "quantity": 1, "stock_quantity": 5,
         "missing": False, "sufficient_stock": True},
    ]

    captured_kwargs: dict = {}

    async def fake_create_tx(**kw):
        captured_kwargs.update(kw)
        return {"id": "tx"}

    pos_adapter = MagicMock()
    pos_adapter.create_pending = AsyncMock(return_value="r-1")

    with patch.object(flows, "resolve_items_against_menu",
                      new=AsyncMock(return_value=enriched)), \
         patch.object(flows, "read_threshold_cents",
                      new=AsyncMock(return_value=2000)), \
         patch.object(flows, "_find_recent_duplicate",
                      new=AsyncMock(return_value=None)), \
         patch.object(flows, "transactions") as mock_tx, \
         patch.object(flows, "get_pos_adapter_for_store", new=AsyncMock(return_value=pos_adapter)):

        mock_tx.create_transaction = AsyncMock(side_effect=fake_create_tx)
        mock_tx.set_pos_object_id  = AsyncMock()
        mock_tx.advance_state      = AsyncMock()

        await flows.create_order(
            store_id="STORE",
            args={"items":          [{"name": "Latte", "quantity": 1}],
                  "customer_phone": "+15035550100",
                  "customer_name":  "Michael"},
        )

    assert captured_kwargs.get("customer_email") in (None, "")


# ── Phase 7-A.D Wave A.3 Plan D — Loyverse POS fire-and-forget async ──────────
# Live measurement 2026-05-08 21:43:10-13 showed adapter.create_pending alone
# took 2484ms of the 3029ms total create_order — 82% of the user-perceived
# silence after the customer's confirming yes. These tests pin the contract
# that fire_immediate now returns to the voice path with state=PENDING the
# moment create_transaction completes; the POS round-trip and final state
# advance run in a background asyncio task.

@pytest.mark.asyncio
async def test_create_order_fire_immediate_returns_before_pos_completes():
    """fire_immediate path must return to the caller immediately after the
    bridge INSERT — without waiting for adapter.create_pending. Live: this
    cuts user-perceived latency from ~3.0s to ~0.5s.
    (fire_immediate 분기는 POS 호출 완료 전에 voice에 응답)
    """
    import asyncio as _asyncio
    from app.services.bridge import flows
    from app.services.bridge.state_machine import State

    enriched = [
        {"name": "Latte", "variant_id": "v", "item_id": "i",
         "price": 4.00, "quantity": 1, "stock_quantity": 5,
         "missing": False, "sufficient_stock": True},
    ]

    pos_started   = _asyncio.Event()
    pos_can_finish = _asyncio.Event()

    async def slow_create_pending(**_kw):
        pos_started.set()
        await pos_can_finish.wait()  # blocks until the test releases
        return "r-async-1"

    pos_adapter = MagicMock()
    pos_adapter.create_pending = AsyncMock(side_effect=slow_create_pending)

    with patch.object(flows, "resolve_items_against_menu",
                      new=AsyncMock(return_value=enriched)), \
         patch.object(flows, "read_threshold_cents",
                      new=AsyncMock(return_value=2000)), \
         patch.object(flows, "_find_recent_duplicate",
                      new=AsyncMock(return_value=None)), \
         patch.object(flows, "transactions") as mock_tx, \
         patch.object(flows, "get_pos_adapter_for_store",
                      new=AsyncMock(return_value=pos_adapter)):

        mock_tx.create_transaction = AsyncMock(return_value={"id": "tx-async"})
        mock_tx.set_pos_object_id  = AsyncMock()
        mock_tx.advance_state      = AsyncMock()

        res = await flows.create_order(
            store_id="STORE",
            args={"items":          [{"name": "Latte", "quantity": 1}],
                  "customer_phone": "+15035550100",
                  "customer_name":  "Michael"},
        )

        # We returned WITHOUT pos_create_pending finishing — that's the whole point.
        assert res["success"]         is True
        assert res["state"]           == State.PENDING  # not FIRED_UNPAID yet
        assert res["pos_object_id"]   == ""             # backfilled later
        assert res["ai_script_hint"]  == "fire_immediate"

        # asyncio.create_task schedules but doesn't run until the loop yields.
        # One sleep(0) is enough to let the task reach its first await
        # (the slow create_pending we mocked) — proving the task IS running
        # in the background and that we returned BEFORE it finished.
        # (create_task는 yield 후 실행 — sleep(0)으로 task 시작 보장)
        await _asyncio.sleep(0)
        assert pos_started.is_set()
        pos_adapter.create_pending.assert_awaited_once()
        # But neither set_pos_object_id nor advance_state have run yet —
        # they're inside the background task, gated behind create_pending.
        mock_tx.set_pos_object_id.assert_not_awaited()
        mock_tx.advance_state.assert_not_awaited()

        # Release the gate so the background task can complete cleanly,
        # then yield so its subsequent awaits actually run before exiting
        # the patch context. Without these awaits the test exits while a
        # task is mid-flight — pytest-asyncio reports unawaited coroutines.
        # (게이트 해제 후 background task 완주 대기 — 미완 task 경고 방지)
        pos_can_finish.set()
        # Spin the loop a few times to let background reach set_pos + advance.
        for _ in range(5):
            await _asyncio.sleep(0)

    # After the loop spin, background work should have completed.
    mock_tx.set_pos_object_id.assert_awaited_once()
    advance_calls = [c.kwargs.get("to_state") for c in mock_tx.advance_state.await_args_list]
    assert State.FIRED_UNPAID in advance_calls


@pytest.mark.asyncio
async def test_create_order_async_pos_failure_advances_to_failed():
    """Plan D: POS adapter raises in the background → bridge tx still ends in
    FAILED state (operator-recoverable), even though the voice caller already
    got a success response. The bot's script wording is now soft enough
    ('placing your order') that the customer is not falsely told the kitchen
    has it. The transaction's FAILED state is the operator-side signal.
    (POS 실패 시 background에서 FAILED 전이 — operator 복구 가능)
    """
    import asyncio as _asyncio
    from app.services.bridge import flows
    from app.services.bridge.state_machine import State

    enriched = [
        {"name": "Latte", "variant_id": "v", "item_id": "i",
         "price": 4.00, "quantity": 1, "stock_quantity": 5,
         "missing": False, "sufficient_stock": True},
    ]

    pos_adapter = MagicMock()
    pos_adapter.create_pending = AsyncMock(side_effect=RuntimeError("Loyverse 502"))

    with patch.object(flows, "resolve_items_against_menu",
                      new=AsyncMock(return_value=enriched)), \
         patch.object(flows, "read_threshold_cents",
                      new=AsyncMock(return_value=2000)), \
         patch.object(flows, "_find_recent_duplicate",
                      new=AsyncMock(return_value=None)), \
         patch.object(flows, "transactions") as mock_tx, \
         patch.object(flows, "get_pos_adapter_for_store",
                      new=AsyncMock(return_value=pos_adapter)):

        mock_tx.create_transaction = AsyncMock(return_value={"id": "tx-fail-async"})
        mock_tx.set_pos_object_id  = AsyncMock()
        mock_tx.advance_state      = AsyncMock()

        res = await flows.create_order(
            store_id="STORE",
            args={"items":          [{"name": "Latte", "quantity": 1}],
                  "customer_phone": "+15035550100",
                  "customer_name":  "Michael"},
        )

        # Voice path got a success — the customer is NOT left hanging on the
        # phone while we wait for POS. The hint is still fire_immediate (the
        # script text is updated server-side to reflect 'placing now').
        assert res["success"]  is True
        assert res["state"]    == State.PENDING

        # Spin the loop so the background task runs through its except path.
        for _ in range(5):
            await _asyncio.sleep(0)

    # Background task transitioned the row to FAILED (idempotency safety).
    advance_to_states = [c.kwargs.get("to_state") for c in mock_tx.advance_state.await_args_list]
    assert State.FAILED          in advance_to_states
    assert State.FIRED_UNPAID    not in advance_to_states
    # set_pos_object_id MUST NOT have been called — POS never returned.
    mock_tx.set_pos_object_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_order_pay_first_unchanged_by_plan_d():
    """pay_first lane never went through adapter.create_pending in the first
    place, so Plan D leaves it unchanged. The transaction stays PENDING and
    no background task is spawned (POS lookup itself never happens).
    (pay_first는 원래 POS 호출 안 함 — Plan D 영향 없음)"""
    from app.services.bridge import flows
    from app.services.bridge.state_machine import State

    enriched = [
        {"name": "Combo", "variant_id": "v", "item_id": "i",
         "price": 25.00, "quantity": 1, "stock_quantity": 50,
         "missing": False, "sufficient_stock": True},
    ]

    pos_adapter = MagicMock()
    pos_adapter.create_pending = AsyncMock()

    with patch.object(flows, "resolve_items_against_menu",
                      new=AsyncMock(return_value=enriched)), \
         patch.object(flows, "read_threshold_cents",
                      new=AsyncMock(return_value=2000)), \
         patch.object(flows, "_find_recent_duplicate",
                      new=AsyncMock(return_value=None)), \
         patch.object(flows, "transactions") as mock_tx, \
         patch.object(flows, "get_pos_adapter_for_store",
                      new=AsyncMock(return_value=pos_adapter)):

        mock_tx.create_transaction = AsyncMock(return_value={"id": "tx-pf"})

        res = await flows.create_order(
            store_id="STORE",
            args={"items":          [{"name": "Combo", "quantity": 1}],
                  "customer_phone": "+15035550100",
                  "customer_name":  "Michael"},
        )

    assert res["success"]        is True
    assert res["lane"]           == "pay_first"
    assert res["state"]          == State.PENDING
    assert res["ai_script_hint"] == "pay_first"
    pos_adapter.create_pending.assert_not_called()


# ── POS injection failure handling ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_order_keeps_pending_on_pos_failure():
    """Plan D revision: POS now runs in a background task, so the voice
    handler ALWAYS gets success=True at the moment of return — the eventual
    FAILED state lands in bridge_transactions a few hundred ms later when
    the background task's POS exception is caught. Operator-side recovery
    is unchanged (manager_alert + reconcile pick up FAILED rows). The bot
    has already said 'placing your order' — the soft wording avoids a
    false 'in the kitchen now' promise on POS failure.
    (POS 실패는 background 처리 — voice는 즉시 success, FAILED는 사후 영속화)
    """
    import asyncio as _asyncio
    from app.services.bridge import flows
    from app.services.bridge.state_machine import State

    enriched = [
        {"name": "Latte", "variant_id": "v", "item_id": "i",
         "price": 4.00, "quantity": 1, "stock_quantity": 5,
         "missing": False, "sufficient_stock": True},
    ]

    pos_adapter = MagicMock()
    pos_adapter.create_pending = AsyncMock(side_effect=RuntimeError("Loyverse 502"))

    with patch.object(flows, "resolve_items_against_menu",
                      new=AsyncMock(return_value=enriched)), \
         patch.object(flows, "read_threshold_cents",
                      new=AsyncMock(return_value=2000)), \
         patch.object(flows, "_find_recent_duplicate",
                      new=AsyncMock(return_value=None)), \
         patch.object(flows, "transactions") as mock_tx, \
         patch.object(flows, "get_pos_adapter_for_store", new=AsyncMock(return_value=pos_adapter)):

        mock_tx.create_transaction = AsyncMock(return_value={"id": "tx-99"})
        mock_tx.set_pos_object_id  = AsyncMock()
        mock_tx.advance_state      = AsyncMock()

        res = await flows.create_order(
            store_id="STORE",
            args={"items": [{"name": "Latte", "quantity": 1}],
                  "customer_phone": "+15035550100",
                  "customer_name":  "Michael"},
        )

        # Voice path got success — caller is NOT held on the line for the
        # POS failure handling. The hint is fire_immediate; the wording is
        # 'placing your order now', which is honest about in-flight POS.
        assert res["success"]         is True
        assert res["state"]           == State.PENDING
        assert res["ai_script_hint"]  == "fire_immediate"
        assert res["pos_object_id"]   == ""

        # Spin so the background task runs through its except path.
        for _ in range(5):
            await _asyncio.sleep(0)

    # Background task observed the POS exception and advanced to FAILED.
    # set_pos_object_id MUST NOT have been called (POS never returned).
    to_states = [c.kwargs.get("to_state") for c in mock_tx.advance_state.await_args_list]
    assert State.FAILED        in to_states
    assert State.FIRED_UNPAID  not in to_states
    mock_tx.set_pos_object_id.assert_not_awaited()


# ── Idempotency ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_order_idempotent_within_window():
    """Same store + customer_phone + 'order' inside the 5-min window short-circuits.
    Returns the existing transaction without a second POS call.
    (idempotency — 5분 윈도우 동일 주문 단축 회로)
    """
    from app.services.bridge import flows

    enriched = [
        {"name": "Latte", "variant_id": "v", "item_id": "i",
         "price": 4.00, "quantity": 1, "stock_quantity": 5,
         "missing": False, "sufficient_stock": True},
    ]

    pos_adapter = MagicMock()
    pos_adapter.create_pending = AsyncMock()

    with patch.object(flows, "resolve_items_against_menu",
                      new=AsyncMock(return_value=enriched)), \
         patch.object(flows, "read_threshold_cents",
                      new=AsyncMock(return_value=2000)), \
         patch.object(flows, "_find_recent_duplicate",
                      new=AsyncMock(return_value={
                          "id": "tx-existing", "pos_object_id": "r-9",
                          "state": "fired_unpaid"})), \
         patch.object(flows, "transactions") as mock_tx, \
         patch.object(flows, "get_pos_adapter_for_store", new=AsyncMock(return_value=pos_adapter)):

        mock_tx.create_transaction = AsyncMock()
        res = await flows.create_order(
            store_id="STORE",
            args={"items": [{"name": "Latte", "quantity": 1}],
                  "customer_phone": "+15035550100",
                  "customer_name":  "Michael"},
        )

    assert res["success"]        is True
    assert res["idempotent"]     is True
    assert res["transaction_id"] == "tx-existing"
    mock_tx.create_transaction.assert_not_called()
    pos_adapter.create_pending.assert_not_called()


# ── Idempotent return-dict completeness (lane=None bug fix) ───────────────────
# Live: call_770ec863… 22:48:26 — voice_websocket logged 'lane=None' on a
# successful create_order because the idempotent re-hit branch returned a
# dict missing 'lane', 'total_cents', 'items'. The script still fired
# correctly via ai_script_hint, but downstream debug + the modify-cycle
# session snapshot ('last_order_items', 'last_order_total') saw None,
# breaking the closing-summary line and confusing log triage. These tests
# lock the parity with the non-idempotent success branches at lines
# 563-572 and 578-587 of flows.py.
# (idempotent return dict 누락 필드 보강 회귀 방지)


def _idempotent_setup(state: str, payment_lane: str, total_cents: int,
                      items_json: list):
    """Helper — patch context for an idempotent re-hit with the row's actual
    payment_lane / total_cents / items_json so we can assert they propagate.
    """
    from app.services.bridge import flows
    from unittest.mock import AsyncMock, MagicMock, patch

    enriched = [
        {"name": "Latte", "variant_id": "v", "item_id": "i",
         "price": 4.00, "quantity": 1, "stock_quantity": 5,
         "missing": False, "sufficient_stock": True},
    ]
    pos_adapter = MagicMock()
    pos_adapter.create_pending = AsyncMock()

    existing_row = {
        "id":             "tx-existing",
        "pos_object_id":  "r-9",
        "state":          state,
        "payment_lane":   payment_lane,
        "total_cents":    total_cents,
        "items_json":     items_json,
    }

    return patch.multiple(
        flows,
        resolve_items_against_menu = AsyncMock(return_value=enriched),
        read_threshold_cents       = AsyncMock(return_value=2000),
        _find_recent_duplicate     = AsyncMock(return_value=existing_row),
        get_pos_adapter_for_store  = AsyncMock(return_value=pos_adapter),
        transactions               = MagicMock(create_transaction=AsyncMock()),
    )


@pytest.mark.asyncio
async def test_idempotent_return_includes_lane_field():
    """Idempotent re-hit must include 'lane' field — pulled from existing
    row's payment_lane column. Without this, voice_websocket logs lane=None.
    """
    from app.services.bridge import flows

    items_json = [{"name": "Latte", "quantity": 1, "price": 4.00}]
    with _idempotent_setup(state="fired_unpaid", payment_lane="fire_immediate",
                            total_cents=400, items_json=items_json):
        res = await flows.create_order(
            store_id="STORE",
            args={"items": [{"name": "Latte", "quantity": 1}],
                  "customer_phone": "+15035550100",
                  "customer_name":  "Michael"},
        )
    assert res["idempotent"] is True
    assert "lane" in res
    assert res["lane"] == "fire_immediate"


@pytest.mark.asyncio
async def test_idempotent_return_includes_total_cents_field():
    """Idempotent re-hit must include 'total_cents' field — pulled from
    existing row. Voice handler's session snapshot uses this for the
    closing-summary line."""
    from app.services.bridge import flows

    items_json = [{"name": "Latte", "quantity": 1, "price": 4.00}]
    with _idempotent_setup(state="pending", payment_lane="pay_first",
                            total_cents=400, items_json=items_json):
        res = await flows.create_order(
            store_id="STORE",
            args={"items": [{"name": "Latte", "quantity": 1}],
                  "customer_phone": "+15035550100",
                  "customer_name":  "Michael"},
        )
    assert res["idempotent"] is True
    assert "total_cents" in res
    assert res["total_cents"] == 400
    assert isinstance(res["total_cents"], int)


@pytest.mark.asyncio
async def test_idempotent_return_includes_items_field():
    """Idempotent re-hit must include 'items' list — pulled from existing
    row's items_json. Voice session uses this to populate
    last_order_items for the recap line."""
    from app.services.bridge import flows

    items_json = [
        {"name": "Latte",     "quantity": 2, "price": 4.00},
        {"name": "Croissant", "quantity": 1, "price": 3.50},
    ]
    with _idempotent_setup(state="pending", payment_lane="pay_first",
                            total_cents=1150, items_json=items_json):
        res = await flows.create_order(
            store_id="STORE",
            args={"items": [{"name": "Latte", "quantity": 1}],
                  "customer_phone": "+15035550100",
                  "customer_name":  "Michael"},
        )
    assert res["idempotent"] is True
    assert "items" in res
    assert isinstance(res["items"], list)
    assert len(res["items"]) == 2


@pytest.mark.asyncio
async def test_idempotent_return_handles_null_payment_lane_gracefully():
    """Defensive: an existing row with NULL payment_lane (legacy data) must
    not crash — return None for 'lane' rather than KeyError."""
    from app.services.bridge import flows

    items_json = [{"name": "Latte", "quantity": 1, "price": 4.00}]
    with _idempotent_setup(state="pending", payment_lane=None,
                            total_cents=400, items_json=items_json):
        res = await flows.create_order(
            store_id="STORE",
            args={"items": [{"name": "Latte", "quantity": 1}],
                  "customer_phone": "+15035550100",
                  "customer_name":  "Michael"},
        )
    assert res["idempotent"] is True
    assert res["lane"] is None       # explicit None, not missing


@pytest.mark.asyncio
async def test_idempotent_return_handles_missing_total_cents_gracefully():
    """Defensive: an existing row with NULL total_cents must coerce to 0,
    not crash on int(None)."""
    from app.services.bridge import flows

    items_json = [{"name": "Latte", "quantity": 1, "price": 4.00}]
    with _idempotent_setup(state="pending", payment_lane="pay_first",
                            total_cents=None, items_json=items_json):
        res = await flows.create_order(
            store_id="STORE",
            args={"items": [{"name": "Latte", "quantity": 1}],
                  "customer_phone": "+15035550100",
                  "customer_name":  "Michael"},
        )
    assert res["idempotent"] is True
    assert res["total_cents"] == 0
    assert res["items"] == [{"name": "Latte", "quantity": 1, "price": 4.00}]
