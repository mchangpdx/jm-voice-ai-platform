# B6 — `recall_order` Voice Tool (Phase 2-C.B6)

**Status**: Draft → RED tests → Implementation
**Date**: 2026-05-05
**Trigger**: live call `call_7d7ef130ad839e9a2c3c68816a7` T25–26 — bot answered *"I don't see an active order"* even though session held `1× Cheese Pizza @ $10.99 (lane=pay_first, pending payment)`.

---

## 1. Problem

When a customer asks **"what's my order?"** / **"did you send it?"** / **"my order info"** **mid-call** (i.e. after a successful `create_order` and/or `modify_order`, before payment lands), the LLM has **no tool to query in-flight order state** and falls back to hallucinating *"no active order"*. Backend session already holds the snapshot (`session["last_order_items"]`, `session["last_order_total"]`) but it is not exposed to the model.

`_find_recent_duplicate` in `flows.py` already matches `pending,payment_sent,fired_unpaid,paid,fulfilled` — the **bug surface is the LLM tool inventory, not the data layer**.

## 2. Goal

Add a new read-only voice tool `recall_order` that returns the latest committed in-call order snapshot to the model, so the assistant can truthfully recap the order to the customer.

## 3. Non-Goals (Explicitly Preserved)

- `create_order` flow / `lane=pay_first` routing — UNCHANGED
- `modify_order` flow & total recompute — UNCHANGED
- `cancel_order` flow — UNCHANGED
- `allergen_lookup` (B5) and Tier 3 EpiPen handoff — UNCHANGED
- AUTO-FIRE gate, RECITAL/MSG DEDUP, modify cooldown — UNCHANGED
- closing-summary line (Proposal I), modify_count cap — UNCHANGED
- Loyverse adapter, pay link SMS/Email, no-show sweep — UNCHANGED

## 4. Tool Schema

```json
{
  "name": "recall_order",
  "description": "Recap the customer's current in-flight order.",
  "parameters": { "type": "object", "properties": {} }
}
```

No parameters. The handler reads from session snapshot.

## 5. Handler Behaviour

Inputs (from session, set by existing create/modify logic):
- `last_order_items`: `list[{name, quantity}]`
- `last_order_total`: `int` (cents)

Outputs (returned to LLM as `function_response.message`):

| Case | Condition | Verbatim message (read aloud) |
|---|---|---|
| `recall_present` | items non-empty AND total > 0 | `"You have <items> for $<total>. The payment link is on its way — tap it and your order goes straight to the kitchen."` |
| `recall_empty` | items empty OR total ≤ 0 | `"I don't have an order placed for you yet. Would you like to start one?"` |

`<items>` rendering follows the existing closing-summary format: `"1 Cheese Pizza, 2 Americanos"`.

## 6. System Prompt Rule (Append rule 13)

> **13. ORDER RECALL (`recall_order`)**: When the customer asks about the current order state mid-call ("my order", "what did I order", "did you send it", "order info", "is it confirmed", "how much", "the total"), call `recall_order` with no arguments. NEVER answer from your own memory or claim there is no order — the tool is the only source of truth. Read the tool's `message` field VERBATIM. Do not call this tool reflexively after `create_order` / `modify_order` success — those have their own confirmation copy.

## 7. Test Matrix (`tests/unit/adapters/test_recall_order.py`)

| # | Scenario | Expected |
|---|---|---|
| R1 | Session has 1×Cheese Pizza, total=1099 → invoke handler | `success=True`, message contains `"1 Cheese Pizza"` and `"$10.99"`, reason=`recall_present` |
| R2 | Session empty (`last_order_items=[]`, total=0) → invoke handler | `success=True`, message starts with `"I don't have an order"`, reason=`recall_empty` |
| R3 | Session has 1×Pizza + 2×Americano, total=2497 → invoke handler | message contains both items + `"$24.97"` |

## 8. Implementation Order (TDD)

1. Write `B6_recall_order.md` (this file). ✅
2. Write `tests/unit/adapters/test_recall_order.py` (RED — 3 tests).
3. Add `RECALL_ORDER_TOOL_DEF` + `_render_recall_message` to `app/skills/order/order.py`.
4. Add dispatcher branch `elif tool_name == "recall_order":` in `voice_websocket.py` immediately before the `else: unsupported` block.
5. Append `RECALL_ORDER_TOOL_DEF` to the `tools=[…]` list (line ~1152).
6. Append rule 13 to `build_system_prompt`.
7. Run `pytest backend/tests/unit/` — expect 393+3 = 396 passing.
8. Live call verification → archive PDF.

## 9. Risk Assessment

- **Scope**: 2 files (`skills/order/order.py`, `api/voice_websocket.py`); additions only, no edits to existing branches.
- **Cache invalidation**: System prompt grows by ~3 lines → minor; existing prompt already ~3KB.
- **LLM behaviour**: New tool may be over-called; mitigated by rule 13 explicit "do NOT call reflexively after create/modify success".
- **Dedup interaction**: `recall_order` returns the same `message` only if customer asks twice in a row; the existing 8s `MSG DEDUP` will silently suppress the duplicate — acceptable.

## 10. Rollback

Single revert (one commit): tool def, dispatcher branch, prompt rule 13, tests — all in one commit. No DB migrations, no external service changes.
