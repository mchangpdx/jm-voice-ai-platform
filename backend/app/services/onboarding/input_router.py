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
        return await extract_from_loyverse(payload["api_key"])
    if source_type == "url":
        return await extract_from_url(payload["url"])
    if source_type in ("pdf", "image"):
        return await extract_from_images(payload["image_paths"])
    if source_type == "csv":
        return await extract_from_csv(payload["file_path"])
    if source_type == "manual":
        return await extract_from_manual(payload["items"])
    raise ValueError(f"unknown source_type: {source_type!r}")
