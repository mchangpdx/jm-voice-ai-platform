"""TEMPORARY validation-only endpoint — serves a static Mexican menu HTML
for the 2026-05-15 onboarding-automation cross-source validation. Reads
from docs/onboarding-validation/2026-05-15-mexican-validation/sources/
menu.html. Also serves per-item food images from sources/images/.
Remove after validation is complete.
(검증용 임시 endpoint — HTML 메뉴 + 음식 이미지 serve, ngrok URL crawler 및 사용자 검증용)
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response

router = APIRouter(tags=["validation-mock"])

_SOURCES_DIR = (
    Path(__file__).resolve().parents[3].parent
    / "docs"
    / "onboarding-validation"
    / "2026-05-15-mexican-validation"
    / "sources"
)
_MENU_HTML_PATH = _SOURCES_DIR / "menu.html"
_MENU_V2_HTML_PATH = _SOURCES_DIR / "menu_v2.html"  # image-rich version
_IMAGES_DIR = _SOURCES_DIR / "images"


@router.get("/mock-mexican-menu", response_class=HTMLResponse, include_in_schema=False)
async def mock_mexican_menu() -> HTMLResponse:
    """v1 menu HTML — table-only (no images)."""
    if not _MENU_HTML_PATH.exists():
        raise HTTPException(status_code=404, detail=f"menu.html not found at {_MENU_HTML_PATH}")
    html = _MENU_HTML_PATH.read_text(encoding="utf-8")
    return HTMLResponse(content=html, status_code=200)


@router.get("/mock-mexican-menu-v2", response_class=HTMLResponse, include_in_schema=False)
async def mock_mexican_menu_v2() -> HTMLResponse:
    """v2 menu HTML — with per-item food images (used for PDF Vision validation)."""
    if not _MENU_V2_HTML_PATH.exists():
        raise HTTPException(status_code=404, detail=f"menu_v2.html not found at {_MENU_V2_HTML_PATH}")
    html = _MENU_V2_HTML_PATH.read_text(encoding="utf-8")
    return HTMLResponse(content=html, status_code=200)


@router.get("/mock-mexican-menu/images/{image_name}", include_in_schema=False)
async def mock_mexican_menu_image(image_name: str) -> Response:
    """Per-item food image. Restrict to .jpg / .png inside the images dir."""
    if not image_name or "/" in image_name or "\\" in image_name or ".." in image_name:
        raise HTTPException(status_code=400, detail="invalid image name")
    if not image_name.lower().endswith((".jpg", ".jpeg", ".png")):
        raise HTTPException(status_code=400, detail="only .jpg / .png allowed")
    img_path = _IMAGES_DIR / image_name
    if not img_path.is_file():
        raise HTTPException(status_code=404, detail=f"{image_name} not found")
    mime, _ = mimetypes.guess_type(str(img_path))
    return Response(content=img_path.read_bytes(), media_type=mime or "image/jpeg")
