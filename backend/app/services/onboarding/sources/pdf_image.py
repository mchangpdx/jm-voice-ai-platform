"""Image/PDF source adapter — Claude vision extraction (scenario A/D).

PDFs are split page-by-page via pdf2image (one Claude call per page), then
duplicate items across pages are merged. Both single images and PDFs end
up on the same call path. Phase 1: skeleton. Phase 2 wires the actual
Anthropic call and adds the dedupe pass.
(사진/PDF → Claude vision — Phase 2에서 구현)

Plan: docs/strategic-research/2026-05-11_menu-onboarding-automation/
section 3 scenarios A + D.
"""
from __future__ import annotations

from app.services.onboarding.schema import RawMenuExtraction


async def extract_from_images(image_paths: list[str]) -> RawMenuExtraction:
    """TODO Phase 2 — Claude Sonnet vision extraction.

    Expected wiring:
      1. For each image path, base64-encode and call Anthropic messages
         API with a structured-output prompt (name, price, description,
         category, detected_allergens).
      2. Across-image dedupe by (name, price) — same item photographed
         on two pages must not double-count.
      3. Confidence = the per-item confidence the prompt elicits;
         clamp to [0.0, 1.0].
    (Phase 2 구현 예정 — Claude vision + 이미지 간 dedupe)
    """
    raise NotImplementedError("pdf_image source adapter — implement in Phase 2")
