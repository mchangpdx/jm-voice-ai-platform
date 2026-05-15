"""NormalizedMenuItem → menu.yaml dict (the shape setup_jm_pizza.py reads).

Bridges the new onboarding pipeline to the existing seeder pattern.
The returned dict mirrors `backend/app/templates/<vertical>/menu.yaml`:
`vertical`, `default_lang`, `supported_langs`, `categories`, `items[]`.
Each item carries `id` (slug), `en` (display name), `category`,
`base_price`, `base_allergens`, optional `notes_en`. Multi-size variants
collapse to the smallest variant's price as `base_price`; the larger
sizes ride into the size modifier group during seeding.
(Phase 2 결과 → 기존 yaml shape — seeder pattern 재사용)

Plan: docs/strategic-research/2026-05-11_menu-onboarding-automation/
section 4 Phase 4 db_seeder prep.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from app.services.onboarding.ai_helper import infer_dietary_tags
from app.services.onboarding.schema import NormalizedMenuItem


# Per-vertical language defaults (matches feedback_multilingual_policy.md
# memo, 2026-05-07). Operators can override in the wizard; this is just
# the starting suggestion the export emits.
# (vertical별 default 언어 — 메모 정책 반영)
_LANG_DEFAULTS: dict[str, tuple[str, list[str]]] = {
    "pizza":   ("en", ["en", "es"]),
    "cafe":    ("en", ["en", "es", "ko", "ja", "zh"]),
    "kbbq":    ("en", ["en", "ko"]),
    "sushi":   ("en", ["en", "ja"]),
    "mexican": ("en", ["en", "es"]),
    "general": ("en", ["en"]),
}


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    """ASCII slug suitable for the menu.yaml `id` field.

    The seeder uses this id as the SKU and as the dict key when wiring
    item↔modifier mappings, so collisions across the same menu would
    silently overwrite rows. Callers are expected to pass through
    `_ensure_unique_slugs` when emitting the final yaml.
    (slug — collision 위험은 호출자 책임)
    """
    slug = _SLUG_RE.sub("_", name.strip().lower()).strip("_")
    return slug or "item"


def _ensure_unique_slugs(slugs: Iterable[str]) -> list[str]:
    """Append _2, _3 ... when two items collapse to the same slug.

    Happens when an operator's menu has "Spicy Pizza" and "Spicy! Pizza":
    both slugify to `spicy_pizza`. The seeder's NOT NULL UNIQUE
    constraint on (store_id, sku) would crash on duplicates, so we
    disambiguate here.
    (slug 충돌 시 suffix — seeder unique 제약 회피)
    """
    seen: dict[str, int] = {}
    out: list[str] = []
    for s in slugs:
        if s not in seen:
            seen[s] = 1
            out.append(s)
        else:
            seen[s] += 1
            out.append(f"{s}_{seen[s]}")
    return out


def _category_id(category: str | None) -> str:
    """Category field → snake_case id. Empty/None falls back to 'main'.

    menu.yaml's `categories[].id` is a slug; here we slugify the source
    category string verbatim. Phase 3's wizard later maps these to the
    vertical template's canonical category set (signature_pie, etc).
    (category 문자열 → snake_case id, default 'main')
    """
    if not category:
        return "main"
    return _slugify(category)


def export_menu_yaml(
    items:    list[NormalizedMenuItem],
    vertical: str = "general",
) -> dict[str, Any]:
    """Build a menu.yaml-shaped dict from normalized items.

    Items collapse multi-size variants onto the smallest variant's price
    (the size modifier group carries the deltas). Category dict is
    derived by deduping the items' categories — the wizard's Step 4
    lets the operator rename and re-order them before final seeding.
    `notes_en` carries the description when present so the voice agent
    has the same merchandising copy the menu board does.
    (variants 중 최저가 → base_price, 나머지 size는 modifier로 처리)
    """
    default_lang, supported = _LANG_DEFAULTS.get(vertical, _LANG_DEFAULTS["general"])

    slugs = _ensure_unique_slugs(_slugify(it.get("name") or "") for it in items)
    items_out: list[dict[str, Any]] = []
    seen_categories: dict[str, str] = {}
    for slug, it in zip(slugs, items):
        variants = it.get("variants") or []
        # Smallest variant's price is the base; size modifier covers the rest.
        # `min` with default 0.0 handles the (shouldn't happen) empty variants.
        base_price = min(
            (v.get("price") or 0.0 for v in variants),
            default=0.0,
        )
        cat_id = _category_id(it.get("category"))
        if cat_id not in seen_categories:
            seen_categories[cat_id] = it.get("category") or "Main"

        base_allergens = it.get("detected_allergens") or []
        item_dict: dict[str, Any] = {
            "id":             slug,
            "en":             it.get("name") or "",
            "category":       cat_id,
            "base_price":     float(base_price),
            "base_allergens": base_allergens,
            "base_dietary":   infer_dietary_tags(
                name        = it.get("name") or "",
                description = it.get("description"),
                allergens   = base_allergens,
                vertical    = vertical,
            ),
        }
        description = it.get("description")
        if description:
            item_dict["notes_en"] = description
        # Preserve variants verbatim so the seeder / modifier-group wirer
        # can read sizes back without re-deriving them from prices.
        # (size 변환 정보 보존 — 다음 단계 modifier wiring용)
        if len(variants) > 1:
            item_dict["variants"] = [
                {"size_hint": v.get("size_hint"), "price": float(v.get("price") or 0.0)}
                for v in variants
            ]
        items_out.append(item_dict)

    categories_out = [
        {"id": cid, "en": label}
        for cid, label in seen_categories.items()
    ]

    return {
        "vertical":        vertical,
        "default_lang":    default_lang,
        "supported_langs": supported,
        "categories":      categories_out,
        "items":           items_out,
    }
