"""Public menu viewer — /menu/{slug} renders a store's live menu as HTML.

slug is a kebab-case form of stores.name (e.g. "JM Cafe" → "jm-cafe"). The
endpoint reads the same Supabase tables the voice agent reads (menu_items
+ modifier_groups + applies_to wires), so the page is always in sync with
what callers hear on the phone. No marketing-site work needed — every
onboarded store gets a shareable URL the moment finalize completes.
(공개 메뉴 뷰어 — onboarding 완료 즉시 모든 매장이 /menu/<name> URL 보유)
"""
from __future__ import annotations

import re
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from app.core.config import settings
from app.services.menu.modifiers import fetch_modifier_groups

router = APIRouter(tags=["public-menu"])

_SUPABASE_HEADERS = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
}
_REST = f"{settings.supabase_url}/rest/v1"


def _slugify(name: str) -> str:
    """'JM Cafe' → 'jm-cafe'. ASCII-safe kebab-case."""
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


# ── Data loaders ────────────────────────────────────────────────────────────

async def _find_store(slug: str) -> dict[str, Any] | None:
    """Single REST round-trip — fetch all active stores then match slug
    in Python. Cheap (<20 stores per agency) and avoids a stored-function
    dependency. Returns None when no match.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"{_REST}/stores",
            headers=_SUPABASE_HEADERS,
            params={
                "select":    "id,name,industry,phone,address,business_hours",
                "is_active": "eq.true",
            },
        )
        if r.status_code != 200:
            return None
        for row in r.json() or []:
            if _slugify(row.get("name") or "") == slug:
                return row
    return None


async def _fetch_items(store_id: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"{_REST}/menu_items",
            headers=_SUPABASE_HEADERS,
            params={
                "store_id":     f"eq.{store_id}",
                "is_available": "eq.true",
                "select":       "name,category,description,price,allergens,dietary_tags",
                "order":        "category.asc,price.asc",
            },
        )
        return r.json() if r.status_code == 200 else []


# ── Route ───────────────────────────────────────────────────────────────────

@router.get("/menu/{slug}", response_class=HTMLResponse, include_in_schema=False)
async def public_menu(slug: str) -> HTMLResponse:
    slug = _slugify(slug)
    store = await _find_store(slug)
    if not store:
        raise HTTPException(status_code=404, detail=f"no active store with slug {slug!r}")
    items  = await _fetch_items(store["id"])
    groups = await fetch_modifier_groups(store["id"])
    html   = _render(store, items, groups)
    return HTMLResponse(content=html, status_code=200)


# ── HTML renderer ───────────────────────────────────────────────────────────

# Category display order: known categories first in a sensible reading
# order, then anything else alphabetically. Add a category here when a new
# vertical introduces one (kbbq → 'Banchan', etc).
# (카테고리 정렬 순서 — known 카테고리 우선, 나머지 알파벳)
_CAT_ORDER = [
    # cafe
    "Espresso", "Non-Espresso", "Drinks", "Beverages",
    "Pastry", "Bakery", "Dessert", "Desserts",
    "Breakfast", "Lunch", "Food", "Lunch & Dinner", "Sandwiches", "Salads",
    # pizza
    "Appetizers", "Antojitos", "Starters",
    "Pizza", "Pizzas", "Specialty Pizzas",
    "Pasta", "Calzones", "Sides",
    # mexican
    "Tacos", "Burritos", "Enchiladas", "Specialty Mains",
    "Postres",
    # kbbq / sushi
    "Banchan", "BBQ", "Stews", "Soups", "Sushi", "Rolls", "Sashimi",
    # generic
    "Mains", "Combos", "Kids",
]

# Pretty case for slug-style categories (e.g. "specialty_mains" → "Specialty Mains")
def _pretty_category(c: str | None) -> str:
    if not c:
        return "Other"
    if "_" in c:
        return " ".join(w.capitalize() for w in c.split("_"))
    return c


def _allergen_badges(allergens: list[str] | None) -> str:
    if not allergens:
        return ""
    spans = "".join(
        f'<span class="allergen">{a}</span>'
        for a in sorted({a.lower() for a in allergens})
    )
    return f'<div class="allergens">{spans}</div>'


def _modifier_section(groups: list[dict[str, Any]]) -> str:
    if not groups:
        return ""
    parts: list[str] = ['<section class="modifiers">',
                        '<h2>Customization options</h2>']
    for g in groups:
        required = bool(g.get("is_required"))
        display  = (g.get("display_name") or g.get("code") or "").strip()
        max_sel  = g.get("max_select") or 1
        applies  = g.get("applies_to_categories") or []
        meta_bits = []
        meta_bits.append("Required" if required else "Optional")
        if max_sel and max_sel > 1:
            meta_bits.append(f"up to {max_sel}")
        if applies:
            pretty = ", ".join(_pretty_category(a) for a in applies)
            meta_bits.append(f"applies to {pretty}")
        meta = " · ".join(meta_bits)
        opts = []
        for o in (g.get("options") or []):
            if o.get("is_available") is False:
                continue
            name = (o.get("display_name") or o.get("code") or "?").strip()
            delta = o.get("price_delta") or 0
            try:
                delta = float(delta)
            except (TypeError, ValueError):
                delta = 0.0
            if delta and delta != 0:
                sign = "+" if delta > 0 else "-"
                opts.append(f'<li>{name} <span class="delta">{sign}${abs(delta):.2f}</span></li>')
            else:
                opts.append(f"<li>{name}</li>")
        opts_html = "<ul>" + "".join(opts) + "</ul>" if opts else ""
        parts.append(
            f'<div class="mod-group">'
            f'  <div class="mod-head"><strong>{display}</strong><span class="mod-meta">{meta}</span></div>'
            f'  {opts_html}'
            f'</div>'
        )
    parts.append('</section>')
    return "".join(parts)


def _format_phone_e164_to_us(phone: str | None) -> str:
    """+15039941265 → (503) 994-1265 — friendly display only."""
    if not phone:
        return ""
    m = re.match(r"^\+1?(\d{3})(\d{3})(\d{4})$", phone)
    if m:
        return f"({m.group(1)}) {m.group(2)}-{m.group(3)}"
    return phone


def _render(store: dict[str, Any], items: list[dict[str, Any]],
            groups: list[dict[str, Any]]) -> str:
    # group items by display category
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        by_cat.setdefault(_pretty_category(it.get("category")), []).append(it)

    # sort: known categories first, then the rest alphabetically
    known_idx = {c: i for i, c in enumerate(_CAT_ORDER)}
    cats = sorted(by_cat.keys(), key=lambda c: (known_idx.get(c, 9999), c))

    cat_sections: list[str] = []
    for c in cats:
        item_cards: list[str] = []
        for it in by_cat[c]:
            price = it.get("price") or 0
            try:
                price = float(price)
            except (TypeError, ValueError):
                price = 0.0
            desc = (it.get("description") or "").strip()
            name = (it.get("name") or "").strip()
            badges = _allergen_badges(it.get("allergens"))
            item_cards.append(
                f'<article class="item">'
                f'  <div class="item-head">'
                f'    <h3>{name}</h3>'
                f'    <span class="price">${price:.2f}</span>'
                f'  </div>'
                f'  {f"<p class=\"desc\">{desc}</p>" if desc else ""}'
                f'  {badges}'
                f'</article>'
            )
        cat_sections.append(
            f'<section class="category">'
            f'  <h2>{c}</h2>'
            f'  <div class="items">{"".join(item_cards)}</div>'
            f'</section>'
        )

    phone_display = _format_phone_e164_to_us(store.get("phone"))
    phone_tel     = (store.get("phone") or "").replace(" ", "")
    address       = store.get("address") or ""
    hours         = store.get("business_hours") or ""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{store.get("name", "Menu")} — Menu</title>
<style>
:root {{
  --ink: #0f172a;
  --muted: #64748b;
  --line: #e5e7eb;
  --bg: #fafbfc;
  --accent: #1e40af;
  --warn-bg: #fff7ed;
  --warn-ink: #b45309;
}}
* {{ box-sizing: border-box; }}
html {{ -webkit-text-size-adjust: 100%; }}
body {{
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo",
               "Inter", "Pretendard", "Noto Sans KR", sans-serif;
  color: var(--ink);
  background: var(--bg);
  line-height: 1.5;
}}
header.hero {{
  background: linear-gradient(135deg, #1e40af 0%, #312e81 100%);
  color: #fff;
  padding: 36px 22px 28px;
}}
.hero-inner {{ max-width: 760px; margin: 0 auto; }}
h1 {{
  margin: 0 0 6px;
  font-size: 26px;
  letter-spacing: -0.01em;
}}
.hero-meta {{
  font-size: 13px;
  opacity: 0.86;
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
}}
.hero-meta a {{ color: #fff; text-decoration: none; border-bottom: 1px dotted rgba(255,255,255,0.55); }}
.call-btn {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: 14px;
  background: #fff;
  color: var(--accent);
  border-radius: 999px;
  padding: 9px 18px;
  font-weight: 700;
  font-size: 13px;
  text-decoration: none;
}}
main {{
  max-width: 760px;
  margin: 0 auto;
  padding: 22px;
}}
section.category {{
  margin-bottom: 26px;
}}
section.category > h2 {{
  margin: 6px 0 12px;
  padding-bottom: 6px;
  font-size: 18px;
  border-bottom: 2px solid var(--accent);
  display: inline-block;
}}
.items {{
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
}}
.item {{
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 12px 14px;
}}
.item-head {{
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 10px;
}}
.item-head h3 {{
  margin: 0;
  font-size: 15px;
  font-weight: 700;
}}
.price {{
  color: var(--accent);
  font-weight: 700;
  font-size: 14px;
  white-space: nowrap;
}}
.desc {{
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 13px;
}}
.allergens {{
  margin-top: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}}
.allergen {{
  background: var(--warn-bg);
  color: var(--warn-ink);
  font-size: 10.5px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid #fed7aa;
}}
section.modifiers {{
  margin-top: 14px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 16px 18px;
}}
section.modifiers > h2 {{
  margin: 0 0 8px;
  font-size: 16px;
  color: var(--ink);
}}
.mod-group {{
  padding: 8px 0;
  border-top: 1px solid var(--line);
}}
.mod-group:first-of-type {{ border-top: none; }}
.mod-head {{
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}}
.mod-meta {{
  color: var(--muted);
  font-size: 12px;
}}
.mod-group ul {{
  margin: 6px 0 4px;
  padding-left: 18px;
  font-size: 13px;
  color: var(--ink);
}}
.mod-group .delta {{
  color: var(--accent);
  font-weight: 600;
  font-size: 12px;
  margin-left: 4px;
}}
footer {{
  text-align: center;
  padding: 26px 18px 38px;
  color: var(--muted);
  font-size: 11.5px;
}}
@media (min-width: 620px) {{
  .items {{ grid-template-columns: 1fr 1fr; }}
}}
</style>
</head>
<body>
  <header class="hero">
    <div class="hero-inner">
      <h1>{store.get("name", "Menu")}</h1>
      <div class="hero-meta">
        {f'<span>📍 {address}</span>' if address else ''}
        {f'<span>🕒 {hours}</span>' if hours else ''}
      </div>
      {f'<a class="call-btn" href="tel:{phone_tel}">📞 Call {phone_display or "now"}</a>' if phone_tel else ''}
    </div>
  </header>
  <main>
    {''.join(cat_sections) if cat_sections else '<p style="color:#64748b">No menu items available right now.</p>'}
    {_modifier_section(groups)}
  </main>
  <footer>
    Powered by JM Tech One AI Voice · live menu mirrored from POS
  </footer>
</body>
</html>
"""
