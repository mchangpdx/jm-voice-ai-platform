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

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from jose import JWTError, jwt
from pydantic import BaseModel, Field

from app.core.auth import get_tenant_id
from app.core.config import settings
from app.services.onboarding.ai_helper import (
    apply_allergen_inference_to_normalized,
)
from app.services.onboarding.db_seeder import finalize_store
from app.services.onboarding.input_router import extract as run_extract
from app.services.onboarding.loyverse_pusher import (
    LoyversePushError,
    push_menu_to_loyverse,
)
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


async def _maybe_tenant_id(authorization: Optional[str] = Header(None)) -> Optional[str]:
    """Resolve tenant_id from the JWT if present; return None for unauth calls.

    Unlike `get_tenant_id`, this never raises — onboarding/finalize is
    invoked by both the wizard (JWT in localStorage) and dev curl/scripts
    (no auth header during prod-prep). We force-override owner_id when a
    valid JWT exists; otherwise we let the caller's req.owner_id stand.
    (JWT 있으면 force override, 없으면 req 그대로 — wizard + dev 양립)
    """
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    try:
        return await get_tenant_id(authorization)
    except HTTPException:
        return None


async def _resolve_agency_id_for_owner(owner_id: str) -> Optional[str]:
    """Return the agency.id this owner manages, or None for single-tenant users.

    Matches the lookup pattern in `app/api/agency.py:_resolve_agency` —
    agencies.owner_id is the join key. We swallow misses silently because
    a brand-new operator that hasn't been provisioned into an agency yet
    is still allowed to onboard a store (single-tenant pilot).
    (agency 없는 owner도 등록 허용 — single-tenant pilot은 NULL agency_id)
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{settings.supabase_url}/rest/v1/agencies",
                headers={
                    "apikey":        settings.supabase_service_role_key,
                    "Authorization": f"Bearer {settings.supabase_service_role_key}",
                },
                params={"owner_id": f"eq.{owner_id}", "select": "id"},
            )
            if resp.status_code != 200:
                return None
            rows = resp.json() if isinstance(resp.json(), list) else []
            return rows[0]["id"] if rows else None
    except (httpx.HTTPError, JWTError):
        return None


class FinalizeRequest(BaseModel):
    """Wizard Step 5 → Step 6 transition. Last operator-controlled write
    before the voice agent is reachable on a phone number.

    Identity fields (owner_id, agency_id) are optional — single-tenant
    pilots leave them null. POS fields persist the Loyverse token so
    the bridge adapter can re-sync without re-prompting the operator.
    `system_prompt` lets the wizard inject a vertical-tailored prompt
    in Step 4 (or fall back to the template default at call time).
    (Step 5→6 — 매장 최종 DB write, optional identity/POS/prompt)
    """
    store_name:           str
    phone_number:         str
    manager_phone:        str = "+15037079566"
    vertical:             str
    menu_yaml:            dict[str, Any]
    modifier_groups_yaml: dict[str, Any] = Field(default_factory=dict)
    owner_id:             Optional[str] = None
    agency_id:            Optional[str] = None
    pos_provider:         Optional[str] = None
    pos_api_key:          Optional[str] = None
    system_prompt:        Optional[str] = None
    business_hours:       Optional[str] = None
    push_to_loyverse:     bool = False
    loyverse_store_id:    Optional[str] = None  # required if push_to_loyverse
    dry_run:              bool = False           # payload preview only — no DB / Loyverse writes


@router.post("/finalize", response_model=None)
async def post_finalize(
    req: FinalizeRequest,
    tenant_id: Optional[str] = Depends(_maybe_tenant_id),
) -> dict[str, Any]:
    """Stage 5 — write the approved yaml into Supabase + return next steps.

    Identity resolution: when a valid JWT is present (wizard UI always
    sends one), `tenant_id` is `JWT.sub` and force-overrides any value
    `req.owner_id` carried — this prevents a caller from registering a
    store as another user. The matching `agency_id` is looked up from
    `agencies.owner_id` so the new store lands in the right tenant's
    sidebar without manual SQL (the JM Taco 2026-05-16 fix).

    Calls db_seeder.finalize_store which runs the 5-step write
    (stores → menu_items → modifier_groups → modifier_options →
    item↔group wire → menu_cache). On any failure the supabase call
    raises RuntimeError; we surface that as 500.
    (JWT.sub → owner_id force, agency 자동 룩업 — 사이드바 즉시 노출)
    """
    owner_id  = tenant_id or req.owner_id
    agency_id = req.agency_id
    if tenant_id:
        resolved = await _resolve_agency_id_for_owner(tenant_id)
        if resolved:
            agency_id = resolved

    try:
        result = await finalize_store(
            store_name           = req.store_name,
            phone_number         = req.phone_number,
            manager_phone        = req.manager_phone,
            vertical             = req.vertical,
            menu_yaml            = req.menu_yaml,
            modifier_groups_yaml = req.modifier_groups_yaml,
            owner_id             = owner_id,
            agency_id            = agency_id,
            pos_provider         = req.pos_provider,
            pos_api_key          = req.pos_api_key,
            system_prompt        = req.system_prompt,
            business_hours       = req.business_hours,
            dry_run              = req.dry_run,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # Optional Wave 6 — push the approved menu to the operator's
    # Loyverse account. DB write already succeeded; Loyverse failure
    # surfaces as a 422 warning but doesn't roll back the store.
    # (Loyverse push 실패는 422로 별도 안내 — DB는 유지)
    if req.push_to_loyverse:
        if not (req.pos_api_key and req.loyverse_store_id):
            raise HTTPException(
                status_code=400,
                detail="push_to_loyverse=true requires both pos_api_key and loyverse_store_id",
            )
        try:
            loyverse_result = await push_menu_to_loyverse(
                access_token         = req.pos_api_key,
                loyverse_store_id    = req.loyverse_store_id,
                menu_yaml            = req.menu_yaml,
                modifier_groups_yaml = req.modifier_groups_yaml,
                dry_run              = req.dry_run,
            )
            result["loyverse_push"] = loyverse_result
        except LoyversePushError as exc:
            result["loyverse_push"] = {"error": str(exc), "path": exc.path, "status": exc.status}
            result["next_steps"].insert(0, (
                f"Loyverse push failed at {exc.path} (HTTP {exc.status}). "
                "Store DB row was saved; retry the push from the wizard or "
                "fall back to CSV import in Loyverse Back Office."
            ))

    return result


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
