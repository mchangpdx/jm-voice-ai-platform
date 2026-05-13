"""Tests for the CSV source adapter.

Covers the heuristic column matcher (different header conventions
from Square / Toast / generic Excel), price coercion (string $,
commas), and the graceful-degradation paths (missing file, no
header row, missing name/price columns).
(헤더 컨벤션 다양성 + price coercion + degrade path)
"""
from __future__ import annotations

import pytest

from app.services.onboarding.sources.csv_excel import (
    _coerce_price,
    _pick_column,
    extract_from_csv,
)


def test_pick_column_prefers_specific_hints() -> None:
    # "item_name" is more specific than "name" — must win even though
    # "name" would also match (substring of "item_name").
    assert _pick_column(["item_name", "name"], ("item_name", "name")) == "item_name"


def test_pick_column_substring_match() -> None:
    assert _pick_column(["Item Price (USD)"], ("price",)) == "Item Price (USD)"


def test_pick_column_returns_none_when_no_match() -> None:
    assert _pick_column(["foo", "bar"], ("name", "item")) is None


@pytest.mark.parametrize("raw,expected", [
    ("$12.50",   12.50),
    ("12.50",    12.50),
    (" 12 ",     12.0),
    ("1,250.00", 1250.0),
    (5,          5.0),
    (5.5,        5.5),
])
def test_coerce_price_recoverable_cases(raw, expected) -> None:
    assert _coerce_price(raw) == expected


@pytest.mark.parametrize("raw", ["", "TBD", "ask", None, "  "])
def test_coerce_price_unrecoverable_returns_none(raw) -> None:
    assert _coerce_price(raw) is None


@pytest.mark.asyncio
async def test_extract_missing_file_returns_warning(tmp_path) -> None:
    result = await extract_from_csv(str(tmp_path / "nope.csv"))
    assert result["source"] == "csv"
    assert result["items"] == []
    assert any("not found" in w for w in result["warnings"])


@pytest.mark.asyncio
async def test_extract_square_style_export(tmp_path) -> None:
    """Square POS export — headers Item Name / Price / Category."""
    csv_path = tmp_path / "square.csv"
    csv_path.write_text(
        "Item Name,Price,Category,Description\n"
        "Cheese Pizza,$18.00,Classic Pies,Mozzarella + tomato\n"
        "Big Joe,26.00,Signature Pies,Meatballs + ricotta\n"
        "Soda,$2.50,Drinks,12oz can\n"
    )
    result = await extract_from_csv(str(csv_path))
    names = [it["name"] for it in result["items"]]
    assert names == ["Cheese Pizza", "Big Joe", "Soda"]
    pizza = result["items"][0]
    assert pizza["price"] == 18.0
    assert pizza["category"] == "Classic Pies"
    assert pizza["description"].startswith("Mozzarella")


@pytest.mark.asyncio
async def test_extract_handles_thousands_separator_when_quoted(tmp_path) -> None:
    # Comma-thousands must be quoted in CSV (otherwise the comma is the
    # column separator). This matches what Square/Toast actually emit.
    # (CSV에서 콤마-thousands는 quote 필수 — 실제 export 형식)
    csv_path = tmp_path / "expensive.csv"
    csv_path.write_text(
        'name,price\n'
        'Truffle Pasta,"$1,250.00"\n'
    )
    result = await extract_from_csv(str(csv_path))
    assert result["items"][0]["price"] == 1250.0


@pytest.mark.asyncio
async def test_extract_skips_rows_with_bad_price(tmp_path) -> None:
    csv_path = tmp_path / "messy.csv"
    csv_path.write_text(
        "name,price\n"
        "Latte,5.50\n"
        "Mystery,TBD\n"
        "Cookie,$3.00\n"
    )
    result = await extract_from_csv(str(csv_path))
    assert [it["name"] for it in result["items"]] == ["Latte", "Cookie"]
    assert any("Mystery" in w and "TBD" in w for w in result["warnings"])


@pytest.mark.asyncio
async def test_extract_missing_name_column_emits_actionable_warning(tmp_path) -> None:
    csv_path = tmp_path / "noname.csv"
    csv_path.write_text("Price,Category\n18.00,Pies\n")
    result = await extract_from_csv(str(csv_path))
    assert result["items"] == []
    # warning must hint at the fix
    assert any("rename" in w and "name" in w for w in result["warnings"])


@pytest.mark.asyncio
async def test_extract_empty_file_returns_warning(tmp_path) -> None:
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("")
    result = await extract_from_csv(str(csv_path))
    assert result["items"] == []
    assert any("no header" in w for w in result["warnings"])


@pytest.mark.asyncio
async def test_extract_latin1_fallback(tmp_path) -> None:
    """Legacy Excel exports sometimes ship latin-1 instead of UTF-8."""
    csv_path = tmp_path / "legacy.csv"
    # Café written in latin-1 — UTF-8 would encode é as 2 bytes.
    csv_path.write_bytes("name,price\nCaf\xe9 Latte,5.50\n".encode("latin-1"))
    result = await extract_from_csv(str(csv_path))
    assert result["items"][0]["name"] == "Café Latte"
