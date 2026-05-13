"""CSV source adapter — operator-exported menu from another system.

Stdlib `csv` only — pandas would be a fat dependency for one read pass
and the matchers here are simple enough that DataFrame indexing doesn't
buy us anything. Heuristic column matching keeps the format flexible:
operators export from Square / Toast / Excel templates with wildly
different header conventions, and we don't want to make them rename
columns before upload.
(stdlib csv — pandas 불필요. 컬럼 이름은 heuristic match로 유연성 확보)

Plan: docs/strategic-research/2026-05-11_menu-onboarding-automation/
section 3 scenario D-alt.
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Iterable, Optional

from app.services.onboarding.schema import RawMenuExtraction, RawMenuItem

log = logging.getLogger(__name__)


# Column name candidates, lowercase. First match per row wins. Substring
# match (not exact) so "menu_item_name" hits "name" and "Item Price (USD)"
# hits "price". Listed roughly in order of how specific each token is
# (specific first) to avoid e.g. "category" eating "category_id" rows.
# (column 매칭 — substring case-insensitive, specific token 우선)
_NAME_HINTS:        tuple[str, ...] = ("item_name", "menu_item", "product", "name", "item", "title", "menu")
_PRICE_HINTS:       tuple[str, ...] = ("base_price", "item_price", "price", "cost", "amount")
_CATEGORY_HINTS:    tuple[str, ...] = ("menu_category", "category", "section", "group", "type")
_DESCRIPTION_HINTS: tuple[str, ...] = ("description", "notes", "details", "info", "desc")
_SIZE_HINTS:        tuple[str, ...] = ("size_hint", "size", "variant", "portion")
_SKU_HINTS:         tuple[str, ...] = ("sku", "code", "id", "item_id")


def _pick_column(
    headers:  Iterable[str],
    hints:    tuple[str, ...],
) -> Optional[str]:
    """Find the first header that contains any hint as a substring.

    Returns the original header (preserving case) so the row lookup
    stays correct, since csv.DictReader keys headers verbatim.
    Hints are tried in order; ties broken by header order.
    (헤더 우선순위 — hint 먼저 매칭된 컬럼이 winner)
    """
    lower_to_orig = {h.lower(): h for h in headers if isinstance(h, str)}
    for hint in hints:
        for low, orig in lower_to_orig.items():
            if hint in low:
                return orig
    return None


def _coerce_price(raw: object) -> Optional[float]:
    """Turn "$12.50", "12.50", " 12 ", "1,250.00" into 12.50 / 1250.0.

    Returns None for unrecoverable strings (empty, "TBD", letters).
    `1,250.00` is the European-thousands form; we strip commas. The
    European-decimal `1,25` form would lose info, but US menus use `.`
    for decimals so this stays safe for the pilot footprint.
    (가격 string coercion — $/콤마/공백 제거, 실패 시 None)
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().lstrip("$").replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


async def extract_from_csv(file_path: str) -> RawMenuExtraction:
    """Read a CSV file and emit a RawMenuExtraction.

    Empty / unreadable files return an empty extraction with one
    warning so the wizard's preview shows "no items found" rather
    than crashing. UTF-8 is the default encoding; we fall back to
    latin-1 once on UnicodeDecodeError because legacy Excel exports
    sometimes ship that encoding (especially from Square/Toast on
    older Windows installs).
    (UTF-8 → latin-1 fallback. 빈/깨진 파일은 warning 1개, 빈 items)
    """
    path = Path(file_path)
    if not path.is_file():
        return {
            "source":             "csv",
            "items":              [],
            "detected_modifiers": [],
            "vertical_guess":     None,
            "warnings":           [f"file not found: {file_path}"],
        }

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="latin-1")

    reader = csv.DictReader(text.splitlines())
    headers = reader.fieldnames or []
    if not headers:
        return {
            "source":             "csv",
            "items":              [],
            "detected_modifiers": [],
            "vertical_guess":     None,
            "warnings":           ["csv has no header row"],
        }

    col_name = _pick_column(headers, _NAME_HINTS)
    col_price = _pick_column(headers, _PRICE_HINTS)
    col_category = _pick_column(headers, _CATEGORY_HINTS)
    col_description = _pick_column(headers, _DESCRIPTION_HINTS)
    col_size = _pick_column(headers, _SIZE_HINTS)
    col_sku = _pick_column(headers, _SKU_HINTS)

    warnings: list[str] = []
    if not col_name:
        warnings.append(
            f"no name-like column found in headers {headers!r} — "
            "rename one column to include 'name' or 'item'"
        )
    if not col_price:
        warnings.append(
            f"no price-like column found in headers {headers!r} — "
            "rename one column to include 'price' or 'cost'"
        )

    items: list[RawMenuItem] = []
    if col_name and col_price:
        for row_idx, row in enumerate(reader, start=2):  # row 2 = first data row
            name = (row.get(col_name) or "").strip()
            price = _coerce_price(row.get(col_price))
            if not name:
                warnings.append(f"row {row_idx}: missing name — skipped")
                continue
            if price is None:
                warnings.append(f"row {row_idx} ({name}): bad price {row.get(col_price)!r} — skipped")
                continue
            items.append({
                "name":        name,
                "price":       price,
                "category":    (row.get(col_category) or "").strip() or None if col_category else None,
                "description": (row.get(col_description) or "").strip() or None if col_description else None,
                "size_hint":   (row.get(col_size) or "").strip() or None if col_size else None,
                "sku":         (row.get(col_sku) or "").strip() or None if col_sku else None,
                "confidence":  1.0,
            })

    return {
        "source":             "csv",
        "items":              items,
        "detected_modifiers": [],
        "vertical_guess":     None,  # router fills via detect_vertical
        "warnings":           warnings,
    }
