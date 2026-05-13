"""Image-based source adapter — OpenAI gpt-4o-mini vision extraction.

The caller hands us a list of image paths (JPEG/PNG). PDF inputs are
expected to be pre-rasterized one page per image; that keeps this
module free of poppler/pymupdf system dependencies and matches the
plan's scenario A/D shape ("caller pre-rasterizes pages"). Phase 6's
accuracy harness will benchmark this against the JM Pizza menu_cache
ground truth.
(사진/PDF-rasterized → OpenAI gpt-4o-mini vision → RawMenuItem 리스트)

Plan: docs/strategic-research/2026-05-11_menu-onboarding-automation/
section 3 scenarios A + D.
"""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
from pathlib import Path

from openai import AsyncOpenAI

from app.core.config import settings
from app.services.onboarding.schema import RawMenuExtraction, RawMenuItem

log = logging.getLogger(__name__)


# Vision model — gpt-4o-mini is the cheapest current vision-capable
# OpenAI model and handles menu OCR + structuring in one call. Swap to
# gpt-4o for higher-fidelity menus (handwriting, low-contrast scans).
# (gpt-4o-mini — 가장 저렴한 vision 모델, 메뉴 OCR 충분)
_VISION_MODEL = "gpt-4o-mini"

# Per-image extraction prompt. Asks for confidence so the wizard can flag
# uncertain rows for operator review (the plan's Step 2 — "⚠ Meat Lover
# confidence 78%"). We deliberately do NOT ask the model to infer
# allergens here — that's a Phase 2 ai_helper concern, kept separate
# so the prompt stays focused and short.
# (이미지별 prompt — confidence 요구, allergen은 별도 module에서)
_EXTRACTION_PROMPT = (
    "You are extracting menu items from a restaurant menu photo. "
    "Return strictly valid JSON with this shape:\n"
    '{\n'
    '  "items": [\n'
    '    {\n'
    '      "name": "Big Joe",\n'
    '      "price": 26.00,\n'
    '      "size_hint": "14 inch" | null,\n'
    '      "category": "Signature Pies" | null,\n'
    '      "description": "..." | null,\n'
    '      "confidence": 0.95\n'
    '    }\n'
    '  ],\n'
    '  "detected_modifiers": ["size", "crust", ...]\n'
    '}\n\n'
    "Rules:\n"
    "- One JSON object per row in the menu — split size variants into "
    "separate items (Big Joe 14\" $26 AND Big Joe 18\" $34 = 2 items).\n"
    "- price is a number, not a string. No currency symbols.\n"
    "- Use null (not empty string) when a field is absent.\n"
    "- confidence is 0.0-1.0; 0.95+ for clearly legible items, "
    "0.7-0.9 for partial-occlusion or smudged prices, <0.7 only when "
    "guessing. Never invent items not visible in the photo.\n"
    "- detected_modifiers is the list of add-on dimensions the menu "
    "advertises (e.g. \"size\", \"crust\", \"toppings\", \"milk\", "
    "\"syrup\"). Empty array if none.\n"
    "- Return ONLY the JSON object, no prose, no markdown fence."
)


def _encode_image(path: str) -> tuple[str, str]:
    """Read an image file and return (mime_type, base64_data).

    Falls back to image/jpeg if the OS can't guess from the extension
    (rare for menu photos). The data URL must include a real mime type
    or the OpenAI image_url upload rejects the payload.
    (mime type 자동 추론, 실패 시 jpeg fallback)
    """
    mime, _ = mimetypes.guess_type(path)
    if not mime or not mime.startswith("image/"):
        mime = "image/jpeg"
    data = Path(path).read_bytes()
    return mime, base64.b64encode(data).decode("ascii")


def _normalize_item(raw: dict, source_path: str) -> RawMenuItem | None:
    """Coerce one extracted dict into RawMenuItem; drop unusable rows.

    The model occasionally returns `price` as a string ("$12") or
    `confidence` as a percent (95). We coerce both rather than reject —
    operators can still review-and-fix in the wizard. Rows missing a
    name or with a non-numeric price after coercion are dropped with a
    log line so the warnings list stays operator-actionable.
    (모델이 가끔 string price나 percent confidence 반환 — 변환 시도)
    """
    name = (raw.get("name") or "").strip()
    if not name:
        return None
    raw_price = raw.get("price")
    if isinstance(raw_price, str):
        raw_price = raw_price.strip().lstrip("$").replace(",", "")
    try:
        price = float(raw_price)
    except (TypeError, ValueError):
        log.info("vision drop name=%r price=%r src=%s", name, raw.get("price"), source_path)
        return None
    confidence = raw.get("confidence")
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.5
    if confidence > 1.5:  # model handed us a percent
        confidence = confidence / 100.0
    return {
        "name":        name,
        "price":       price,
        "category":    raw.get("category"),
        "description": raw.get("description"),
        "size_hint":   raw.get("size_hint"),
        "confidence":  max(0.0, min(1.0, confidence)),
    }


async def _extract_one_image(
    client:     AsyncOpenAI,
    image_path: str,
) -> tuple[list[RawMenuItem], list[str], str | None]:
    """Vision call for one image. Returns (items, modifier_hints, warning).

    A failed call or unparseable JSON surfaces as a warning string the
    router accumulates — the rest of the pipeline still gets the items
    we did extract. Keeps onboarding robust to one bad page in a deck.
    (1장 실패가 전체 실패가 되지 않도록 — warning은 누적, items는 보존)
    """
    try:
        mime, b64 = _encode_image(image_path)
        resp = await client.chat.completions.create(
            model=_VISION_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": _EXTRACTION_PROMPT},
                    {"type": "image_url", "image_url": {
                        "url": f"data:{mime};base64,{b64}",
                    }},
                ],
            }],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        body = resp.choices[0].message.content or ""
        parsed = json.loads(body)
    except FileNotFoundError:
        return ([], [], f"image not found: {image_path}")
    except json.JSONDecodeError as exc:
        return ([], [], f"vision returned non-JSON ({image_path}): {exc}")
    except Exception as exc:  # network / OpenAI errors
        return ([], [], f"vision call failed ({image_path}): {exc!r}")

    raw_items = parsed.get("items") or []
    items: list[RawMenuItem] = []
    for entry in raw_items:
        if not isinstance(entry, dict):
            continue
        normalized = _normalize_item(entry, image_path)
        if normalized is not None:
            items.append(normalized)
    modifiers = [m for m in (parsed.get("detected_modifiers") or []) if isinstance(m, str)]
    return (items, modifiers, None)


def _dedupe_across_pages(items: list[RawMenuItem]) -> list[RawMenuItem]:
    """Drop duplicate (name, price, size_hint) entries.

    Multi-page menus (4-fold PDFs especially) frequently show the same
    item twice for visual emphasis — Big Joe in a hero panel and again
    in the size grid. Keys on (name, price, size_hint) so genuinely
    different variants survive. Keeps the first occurrence (highest
    confidence wins when the model is consistent across pages).
    (다중 페이지 메뉴 — 같은 아이템 중복 노출 dedupe, 첫 occurrence 유지)
    """
    seen: set[tuple[str, float, str | None]] = set()
    out: list[RawMenuItem] = []
    for it in items:
        key = (it["name"], it["price"], it.get("size_hint"))
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


async def extract_from_images(image_paths: list[str]) -> RawMenuExtraction:
    """Extract a menu from one or more pre-rasterized images.

    Empty input is a valid call that returns an empty extraction — the
    wizard treats it as "no items found" rather than an error. A missing
    API key fails loudly because the rest of the call would silently
    return zero items and the operator wouldn't know why.
    (빈 input → 빈 extraction (OK), API key 없으면 RuntimeError)
    """
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY missing — vision extraction needs it")

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    all_items: list[RawMenuItem] = []
    all_modifiers: list[str] = []
    warnings: list[str] = []

    for path in image_paths:
        items, modifiers, warning = await _extract_one_image(client, path)
        all_items.extend(items)
        all_modifiers.extend(modifiers)
        if warning:
            warnings.append(warning)

    deduped = _dedupe_across_pages(all_items)
    if len(deduped) < len(all_items):
        warnings.append(
            f"deduped {len(all_items) - len(deduped)} duplicate row(s) across pages"
        )

    # detected_modifiers: dedupe while preserving first-seen order.
    seen_mods: set[str] = set()
    unique_modifiers: list[str] = []
    for m in all_modifiers:
        if m not in seen_mods:
            seen_mods.add(m)
            unique_modifiers.append(m)

    return {
        "source":             "image",
        "items":              deduped,
        "detected_modifiers": unique_modifiers,
        "vertical_guess":     None,  # router fills via detect_vertical
        "warnings":           warnings,
    }
