"""Stage 1 dispatcher — picks a source adapter and returns RawMenuExtraction.

The wizard knows what kind of input the operator gave (file type, URL,
token, manual rows) and passes that as `source_type`. The router exists
so callers (admin API, CLI scripts, tests) don't import each source
module individually. Phase 2 normalizer reads RawMenuExtraction without
caring which adapter produced it.
(Stage 1 dispatcher — source 종류로 분기, 통일된 raw output)
"""
from __future__ import annotations

from app.services.onboarding.schema import RawMenuExtraction, SourceType
from app.services.onboarding.sources.csv_excel import extract_from_csv
from app.services.onboarding.sources.loyverse import extract_from_loyverse
from app.services.onboarding.sources.manual import extract_from_manual
from app.services.onboarding.sources.pdf_image import extract_from_images
from app.services.onboarding.sources.url_crawler import extract_from_url
from app.services.onboarding.vertical_detector import detect_vertical


async def extract(source_type: SourceType, payload: dict) -> RawMenuExtraction:
    """Dispatch to the source adapter and return its RawMenuExtraction.

    Payload keys per source:
      - loyverse:  {"api_key": str}
      - url:       {"url": str}
      - pdf:       {"image_paths": list[str]} (caller pre-rasterizes pages)
      - image:     {"image_paths": list[str]}
      - csv:       {"file_path": str}
      - manual:    {"items": list[dict]}
    (source별 payload 키 — caller가 미리 PDF는 image 변환)
    """
    if source_type == "loyverse":
        result = await extract_from_loyverse(payload["api_key"])
    elif source_type == "url":
        result = await extract_from_url(payload["url"])
    elif source_type in ("pdf", "image"):
        result = await extract_from_images(payload["image_paths"])
    elif source_type == "csv":
        result = await extract_from_csv(payload["file_path"])
    elif source_type == "manual":
        result = await extract_from_manual(payload["items"])
    else:
        raise ValueError(f"unknown source_type: {source_type!r}")

    # Auto-fill vertical_guess unless the adapter already set one (vision
    # adapters can infer vertical from menu layout/photos directly).
    # (vision adapter가 더 강한 vertical 신호 가지면 우선, 아니면 keyword 추론)
    if not result.get("vertical_guess"):
        vertical, _confidence = detect_vertical(result.get("items", []))
        result["vertical_guess"] = vertical
    return result
