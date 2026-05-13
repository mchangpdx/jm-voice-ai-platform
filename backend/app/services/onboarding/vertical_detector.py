"""Vertical inference — picks pizza/cafe/kbbq/sushi/mexican from menu keywords.

Every source adapter feeds a flat item list; this module decides which
vertical template the wizard should pre-load (`backend/app/templates/`).
The check is intentionally keyword-based and runs offline: a fast guess
is cheaper than another model call, and the operator confirms the
verdict in the wizard's Step 2 review. If the top score is tied or
below a confidence floor the result is "general" and the wizard
prompts the operator to pick manually.
(메뉴 keyword 기반 vertical 추론 — 빠른 offline 결정, 사용자 확인 단계 있음)

Plan: docs/strategic-research/2026-05-11_menu-onboarding-automation/
section 4 Phase 2.
"""
from __future__ import annotations

from typing import Iterable

from app.services.onboarding.schema import RawMenuItem


# Signature keywords per vertical. Lowercase, matched as substrings against
# item names. Curated to avoid cross-vertical collisions (e.g. "cheese" is
# not pizza-only — it appears on cafe sandwiches and kbbq corn cheese too).
# When extending, prefer category-defining tokens over ingredient nouns.
# (vertical별 signature keyword — 카테고리 정의 토큰만, ingredient noun 회피)
_VERTICAL_KEYWORDS: dict[str, frozenset[str]] = {
    "pizza": frozenset({
        "pizza", "pie", "slice", "pepperoni", "calzone",
        "garlic knot", "breadstick", "marinara",
    }),
    "cafe": frozenset({
        "latte", "espresso", "cappuccino", "americano", "macchiato",
        "cold brew", "matcha", "mocha", "drip coffee", "cortado",
        "frappe", "affogato",
    }),
    "kbbq": frozenset({
        "galbi", "bulgogi", "kimchi", "ssam", "banchan", "japchae",
        "samgyeopsal", "bibimbap", "tteokbokki", "soju",
    }),
    "sushi": frozenset({
        "sushi", "sashimi", "nigiri", "maki", "uni", "tempura",
        "miso soup", "edamame", "tobiko", "unagi",
    }),
    "mexican": frozenset({
        "taco", "burrito", "quesadilla", "fajita", "enchilada",
        "salsa", "carnitas", "al pastor", "horchata", "elote",
    }),
}

# Minimum signal share before we trust the top guess. Below this, the
# wizard falls back to "general" and prompts manual choice. Calibrated
# so a 24-item menu needs roughly 4+ matches to lock in a vertical.
# (top vertical이 전체 item의 15% 미만이면 confident하지 않음)
_CONFIDENCE_FLOOR = 0.15


def _count_matches(item_name: str, keywords: frozenset[str]) -> int:
    """Number of keywords present as substrings in the (lowercased) name."""
    name = item_name.lower()
    return sum(1 for kw in keywords if kw in name)


def detect_vertical(items: Iterable[RawMenuItem]) -> tuple[str, float]:
    """Pick the best vertical for this menu plus a 0.0-1.0 confidence.

    Returns ("general", 0.0) for empty input and for menus where the top
    vertical's match share falls below the confidence floor — both cases
    should route to the wizard's manual-pick UI. The confidence is the
    share of items that matched the chosen vertical's keywords, which is
    the signal an operator intuitively reads ("most of these are pizza").
    (top vertical의 매칭 share를 confidence로 — operator 직관과 일치)
    """
    items_list = list(items)
    total = len(items_list)
    if total == 0:
        return ("general", 0.0)

    scores: dict[str, int] = {v: 0 for v in _VERTICAL_KEYWORDS}
    for it in items_list:
        name = it.get("name") or ""
        if not name:
            continue
        for vertical, kws in _VERTICAL_KEYWORDS.items():
            if _count_matches(name, kws) > 0:
                scores[vertical] += 1

    best_vertical = max(scores, key=lambda v: scores[v])
    best_score = scores[best_vertical]
    confidence = best_score / total
    if confidence < _CONFIDENCE_FLOOR:
        return ("general", confidence)
    return (best_vertical, confidence)
