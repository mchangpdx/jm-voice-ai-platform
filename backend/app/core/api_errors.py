"""In-memory ring buffer for recent 4xx/5xx API responses.
(최근 4xx/5xx API 응답을 보관하는 in-memory ring buffer)

Mounted as a FastAPI middleware in main.py. The buffer survives uvicorn's
worker process but is reset on restart. Multi-worker production would need
a shared store (Redis); out of scope for V0.

Used by /api/admin/health/api-errors (Phase 2-C).
"""
from __future__ import annotations

import time
from collections import deque
from typing import Any, Deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Keep the last N error entries (~6h at 30 errors/hr, configurable).
# (최근 N건 에러 보관 — 시간보다 개수 기반이 단순)
_MAX_ENTRIES = 1000
_buffer: Deque[dict[str, Any]] = deque(maxlen=_MAX_ENTRIES)


def get_recent_errors(
    *,
    limit: int = 200,
    since_seconds: int | None = None,
    min_status: int = 400,
) -> list[dict[str, Any]]:
    """Return recent errors, optionally filtered by age + min status.
    (최근 에러 목록 — 시간/상태 필터 옵션)
    """
    cutoff = time.time() - since_seconds if since_seconds else 0
    out = []
    # deque iteration is oldest → newest; reverse for newest-first output
    for entry in reversed(_buffer):
        if entry["status"] < min_status:
            continue
        if entry["ts"] < cutoff:
            break
        out.append(entry)
        if len(out) >= limit:
            break
    return out


def summarize_errors(window_seconds: int = 60 * 60) -> dict[str, Any]:
    """Aggregate counts grouped by status class and top endpoints.
    (윈도우 내 에러 집계 — 상태별 카운트 + 상위 endpoint)
    """
    cutoff = time.time() - window_seconds
    by_status: dict[int, int] = {}
    by_path: dict[str, int] = {}
    count_4xx = 0
    count_5xx = 0
    for e in _buffer:
        if e["ts"] < cutoff:
            continue
        s = e["status"]
        by_status[s] = by_status.get(s, 0) + 1
        path_key = f"{e['method']} {e['path']}"
        by_path[path_key] = by_path.get(path_key, 0) + 1
        if 400 <= s < 500:
            count_4xx += 1
        elif s >= 500:
            count_5xx += 1
    top_paths = sorted(by_path.items(), key=lambda x: x[1], reverse=True)[:10]
    return {
        "window_seconds": window_seconds,
        "total_4xx":      count_4xx,
        "total_5xx":      count_5xx,
        "by_status":      by_status,
        "top_endpoints":  [{"endpoint": p, "count": c} for p, c in top_paths],
    }


class ApiErrorTracker(BaseHTTPMiddleware):
    """Record every 4xx/5xx response into the ring buffer.
    (모든 4xx/5xx 응답을 ring buffer에 기록)
    """
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        status = response.status_code
        if status >= 400:
            _buffer.append({
                "ts":     time.time(),
                "method": request.method,
                "path":   request.url.path,
                "status": status,
                "client": request.client.host if request.client else None,
            })
        return response
