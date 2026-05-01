# TDD tests for modify clarification script — Wave 1 P0-2
# (modify intent + noop 시 명확한 clarification — off-menu 항목 거절 fix)
#
# Background: live call call_9b67f4ec… T17/T18 user said 'Can I remove
# one garlic bread?' (off-menu). Gemini fired modify_order with the
# CURRENT items list (since it can't find garlic bread in menu_cache),
# bridge correctly returned modify_noop, voice yielded the standard
# "Your order is unchanged — the total is still $15.97. Tap the
# payment link whenever you're ready." line. The customer kept hearing
# the same line and never got told the item wasn't on the menu.
#
# Helper contract:
#   _build_modify_clarification(items: list[dict], total_cents: int) -> str
#
#   - Returns a customer-facing line that names the current order and
#     asks for the exact menu item.
#   - Uses singular/plural ('1 Latte' vs '2 Lattes') correctly.
#   - Formats total as USD with 2 decimals.
#   - Defensive: skips malformed items (missing name) silently.
#   - Empty items → fallback phrase 'your order'.
#
# This is only invoked when user_has_modify_intent is True. The intent=False
# path keeps the standard MODIFY_ORDER_SCRIPT_BY_HINT["modify_noop"] line,
# so happy-path acks ('okay', 'thank you') don't get the clarification nag.

from app.api.voice_websocket import _build_modify_clarification


# ── T1: typical case (multi-item) ─────────────────────────────────────────────
def test_multi_item_clarification():
    """2 Cafe Lattes + 1 Croissant @ $15.97 — both pluralization paths."""
    items = [
        {"name": "Cafe Latte", "quantity": 2},
        {"name": "Croissant",  "quantity": 1},
    ]
    line = _build_modify_clarification(items=items, total_cents=1597)
    assert "Hmm, I didn't catch the change" in line
    assert "2 Cafe Lattes" in line
    assert "1 Croissant" in line
    assert "$15.97" in line
    assert "exact item from our menu" in line


# ── T2: single-item singular form ─────────────────────────────────────────────
def test_single_item_singular():
    """1 Latte should NOT pluralize."""
    items = [{"name": "Cafe Latte", "quantity": 1}]
    line = _build_modify_clarification(items=items, total_cents=499)
    assert "1 Cafe Latte " in line     # space after — guards against '1 Cafe Lattes' bug
    assert "$4.99" in line


# ── T3: empty items → 'your order' fallback ───────────────────────────────────
def test_empty_items_fallback_phrase():
    """Defensive: empty items list still produces a coherent line."""
    line = _build_modify_clarification(items=[], total_cents=0)
    assert "your order" in line
    assert "$0.00" in line


# ── T4: malformed item (missing name) silently skipped ───────────────────────
def test_malformed_item_skipped():
    """Item without 'name' key is dropped, not crashed on."""
    items = [
        {"quantity": 2},                                    # no name → skip
        {"name": "Croissant", "quantity": 1},
    ]
    line = _build_modify_clarification(items=items, total_cents=399)
    assert "1 Croissant" in line
    # The malformed entry contributes nothing — line should not contain '2 ' adjacent to a missing name
    assert "2 ," not in line
    assert "  " not in line.replace("  ", " ")              # no double spaces


# ── T5: zero total formats as $0.00 ──────────────────────────────────────────
def test_zero_total_formatting():
    line = _build_modify_clarification(items=[], total_cents=0)
    assert "$0.00" in line


# ── T6: large total ($123.45) formats correctly ──────────────────────────────
def test_large_total_formatting():
    items = [{"name": "Big Combo", "quantity": 3}]
    line = _build_modify_clarification(items=items, total_cents=12345)
    assert "$123.45" in line
    assert "3 Big Combos" in line


# ── T7: non-dict item entry doesn't crash ─────────────────────────────────────
def test_non_dict_entry_skipped():
    """Defensive: a string or None in items list is skipped, not crashed on."""
    items = ["garlic bread", None, {"name": "Latte", "quantity": 1}]
    line = _build_modify_clarification(items=items, total_cents=499)
    assert "1 Latte" in line


# ── T8: returned line is non-empty and ends with a question mark ─────────────
def test_line_invites_response():
    """Clarification must end with a question that prompts customer to specify."""
    items = [{"name": "Latte", "quantity": 1}]
    line = _build_modify_clarification(items=items, total_cents=499)
    assert line.strip().endswith("?")
