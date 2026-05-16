"""Public test-script viewer — /scripts/{slug} serves HTML test-call scripts
straight from docs/onboarding-validation/. Companion to /menu/{slug}.

New scripts are added by appending one line to _SCRIPT_MAP; the folder
naming convention (YYYY-MM-DD-name) is invisible to the URL. PDFs sit
next to the HTML on disk for direct download via a separate route.
(공개 테스트 스크립트 뷰어 — 짧은 URL로 통화 스크립트 HTML 공유)
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response

router = APIRouter(tags=["public-scripts"])

# Resolve repo root deterministically — three parents up from this file gives
# backend/app/api/public → backend/app/api → backend/app → backend → repo.
# (repo root 절대경로 확정 — 작업 디렉터리 의존 제거)
_REPO_ROOT = Path(__file__).resolve().parents[4]
_BASE = _REPO_ROOT / "docs" / "onboarding-validation"

# slug → relative html file (under _BASE). PDF is assumed to sit alongside
# the html under the same stem. Add an entry when a new script ships.
# (slug → html 파일 매핑. 새 스크립트는 한 줄만 추가)
_SCRIPT_MAP: dict[str, str] = {
    "jm-cafe-multilingual":  "2026-05-15-jm-cafe-multilingual/cafe-test-call-scripts.html",
    "jm-taco-mexican":       "2026-05-15-mexican-validation/test-call-scripts.html",
    "jm-taco-full-flow":     "2026-05-16-jm-taco-full-flow/full-flow-test-call.html",
}


def _resolve(slug: str, ext: str) -> Path:
    rel = _SCRIPT_MAP.get(slug)
    if not rel:
        raise HTTPException(status_code=404, detail=f"no script with slug {slug!r}")
    path = _BASE / rel
    if ext != "html":
        path = path.with_suffix(f".{ext}")
    # Defensive — never serve anything outside _BASE
    try:
        path.resolve().relative_to(_BASE.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="bad path")
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{slug}.{ext} not found on disk")
    return path


@router.get("/scripts", response_class=HTMLResponse, include_in_schema=False)
async def scripts_index() -> HTMLResponse:
    """Tiny index — list all available scripts so the URL is discoverable."""
    rows = "".join(
        f'<li><a href="/scripts/{slug}">{slug}</a> '
        f'(<a href="/scripts/{slug}.pdf">PDF</a>)</li>'
        for slug in sorted(_SCRIPT_MAP)
    )
    html = (
        "<!doctype html><meta charset='utf-8'>"
        "<title>JM Tech One — Test Scripts</title>"
        "<style>body{font-family:-apple-system,sans-serif;max-width:600px;"
        "margin:40px auto;padding:0 20px;color:#0f172a;}"
        "h1{color:#1e40af;font-size:22px;margin:0 0 12px;}"
        "li{margin:8px 0;font-size:15px;}"
        "a{color:#1e40af;text-decoration:none;border-bottom:1px solid #cbd5e1;}"
        "a:hover{border-bottom-color:#1e40af;}</style>"
        "<h1>Test call scripts</h1>"
        f"<ul>{rows}</ul>"
    )
    return HTMLResponse(content=html, status_code=200)


# PDF route MUST be declared before the catch-all html route so FastAPI
# matches `/scripts/foo.pdf` to this handler instead of binding ".pdf"
# into the slug param of the html route.
# (PDF 라우트 우선 — html catch-all 매칭 회피)
@router.get("/scripts/{slug}.pdf", include_in_schema=False)
async def script_pdf(slug: str) -> Response:
    path = _resolve(slug, "pdf")
    return Response(content=path.read_bytes(), media_type="application/pdf")


@router.get("/scripts/{slug}", response_class=HTMLResponse, include_in_schema=False)
async def script_html(slug: str) -> HTMLResponse:
    # Strip the .pdf extension if the catch-all caught it (defensive — the
    # explicit .pdf route above should normally win)
    if slug.endswith(".pdf"):
        return await script_pdf(slug[:-4])  # type: ignore[return-value]
    path = _resolve(slug, "html")
    return HTMLResponse(content=path.read_text(encoding="utf-8"), status_code=200)
