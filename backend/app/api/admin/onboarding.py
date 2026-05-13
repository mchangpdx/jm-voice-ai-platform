"""Admin Wizard endpoints — drives the 6-step onboarding UI.

Three endpoints expose the pure-pipeline stages so the wizard can
render incrementally (operator can re-extract / re-normalize without
restarting the flow). `finalize` (DB seed + Loyverse push + Twilio
hook) is intentionally deferred to a follow-up commit because it
touches Supabase + Loyverse and needs the freeze handshake.

Auth: matches sibling `sync_control` (minimal in dev — uvicorn binds
to 127.0.0.1, ngrok handles ingress). Production rollout should add a
service-role JWT dependency before these are exposed publicly.
(Admin Wizard API — pure pipeline, finalize는 후속 commit)

Frontend contract: docs/handoff-frontend-onboarding-wizard.md §2
"""
from __future__ import annotations

import logging
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.onboarding.ai_helper import (
    apply_allergen_inference_to_normalized,
)
from app.services.onboarding.input_router import extract as run_extract
from app.services.onboarding.menu_yaml_exporter import export_menu_yaml
from app.services.onboarding.modifier_groups_extractor import (
    export_modifier_groups_yaml,
)
from app.services.onboarding.normalizer import normalize_items
from app.services.onboarding.schema import (
    NormalizedMenuItem,
    RawMenuExtraction,
    RawMenuItem,
    SourceType,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/onboarding", tags=["Admin Onboarding"])


# ── Request models ──────────────────────────────────────────────────────────

class ExtractRequest(BaseModel):
    """Wizard Step 1 → Step 2 transition.

    Only the payload key for the chosen source_type is required —
    others are ignored. Validated at runtime by the source adapter,
    not here, so adapters can evolve their accepted shapes without a
    cross-cutting schema rewrite.
    (Step 1→2 — source 종류만 골라 보내면 adapter가 payload 검증)
    """
    source_type: SourceType = Field(..., description="loyverse|url|pdf|image|csv|manual")
    payload:     dict[str, Any] = Field(default_factory=dict)


class NormalizeRequest(BaseModel):
    """Wizard Step 2 → Step 3 transition. Takes the operator-reviewed
    raw items (possibly edited inline) and re-runs the normalizer.
    Vertical drives allergen inference; defaults to 'general' (no-op).
    (Step 2→3 — operator review 통과한 raw items로 재정규화, vertical로 algy 추론)
    """
    items:    list[dict[str, Any]] = Field(default_factory=list)
    vertical: str = "general"


class PreviewYamlRequest(BaseModel):
    """Wizard Step 4 → Step 5 transition. Caller passes the normalized
    items the operator approved plus the chosen vertical (defaults to
    `general` if the wizard couldn't decide).
    (Step 4→5 — operator 승인된 normalized items + vertical → yaml dict)
    """
    items:    list[dict[str, Any]] = Field(default_factory=list)
    vertical: str = "general"


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/extract", response_model=None)
async def post_extract(req: ExtractRequest) -> RawMenuExtraction:
    """Stage 1 — run the source adapter for source_type.

    Wraps the adapter's exceptions into HTTP errors so the wizard can
    show a friendly message. ValueError is the "unknown source_type"
    case; everything else (RuntimeError for missing OPENAI key, network
    failures) goes through as 500 with the message text.
    (adapter 호출 — 알려진 오류는 400, 그 외는 500)
    """
    try:
        return await run_extract(req.source_type, req.payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/normalize", response_model=None)
async def post_normalize(req: NormalizeRequest) -> list[NormalizedMenuItem]:
    """Stage 2 — group rows + auto-fill allergens from the vertical template.

    Allergens come from the vertical's `allergen_rules.yaml`; items the
    upstream adapter already tagged are preserved verbatim. The wizard
    can override the inferred set in Step 3 inline edit.
    (group + vertical 규칙 기반 algy 추론, adapter가 채운 건 유지)
    """
    raw_items: list[RawMenuItem] = [it for it in req.items]  # type: ignore[assignment]
    normalized = normalize_items(raw_items)
    return apply_allergen_inference_to_normalized(normalized, vertical=req.vertical)


@router.post("/preview-yaml", response_model=None)
async def post_preview_yaml(req: PreviewYamlRequest) -> dict[str, Any]:
    """Stage 3 — emit menu.yaml + modifier_groups.yaml dicts for review.

    The wizard renders these two dicts side-by-side in Step 5 before
    handing them to `finalize` for actual DB/POS writes. Returning
    plain dicts (not yaml strings) keeps the frontend free to render
    however it wants — tree view, raw JSON, syntax-highlighted yaml.
    (Step 5 review용 — yaml string 아닌 dict로 반환)
    """
    items: list[NormalizedMenuItem] = [it for it in req.items]  # type: ignore[assignment]
    return {
        "menu_yaml":            export_menu_yaml(items, vertical=req.vertical),
        "modifier_groups_yaml": export_modifier_groups_yaml(items),
    }


# ── Dev helper — chained pipeline for smoke testing ─────────────────────────

class PipelineRequest(BaseModel):
    """One-shot smoke test — runs extract→normalize→preview-yaml end-to-end."""
    source_type: SourceType
    payload:     dict[str, Any] = Field(default_factory=dict)
    vertical:    Optional[str] = None


@router.post("/pipeline", response_model=None, include_in_schema=False)
async def post_pipeline(req: PipelineRequest) -> dict[str, Any]:
    """Convenience — extract + normalize + export in one call.

    Not part of the wizard contract; exists so an operator (or this
    file's author from the laptop) can curl one URL to verify the
    whole pipeline is healthy after a code change. Hidden from the
    public OpenAPI schema.
    (운영 sanity check용 — wizard contract 아님, schema에서 hidden)
    """
    try:
        raw = await run_extract(req.source_type, req.payload)
    except (ValueError, NotImplementedError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    vertical = req.vertical or raw.get("vertical_guess") or "general"
    items    = apply_allergen_inference_to_normalized(
        normalize_items(raw["items"]),
        vertical=vertical,
    )
    return {
        "raw_extraction":      raw,
        "normalized_items":    items,
        "menu_yaml":           export_menu_yaml(items, vertical=vertical),
        "modifier_groups_yaml": export_modifier_groups_yaml(items),
    }
