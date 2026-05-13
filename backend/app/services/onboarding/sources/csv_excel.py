"""CSV/Excel source adapter (scenario D-alt).

Phase 1: skeleton. Phase 2 wires pandas read + column-name heuristics
(name|item|product, price|cost|amount, category|section).
(CSV 업로드 — Phase 2 구현)
"""
from __future__ import annotations

from app.services.onboarding.schema import RawMenuExtraction


async def extract_from_csv(file_path: str) -> RawMenuExtraction:
    """TODO Phase 2 — pandas + column-name heuristics."""
    raise NotImplementedError("csv source adapter — implement in Phase 2")
