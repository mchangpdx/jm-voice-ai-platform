"""Audit log helper — fire-and-forget writes for admin mutations.
(감사 로그 헬퍼 — admin mutation용 fire-and-forget 기록)

Design rules:
- Audit writes MUST NOT break the user request — catch and log only.
- Writes go to the `audit_logs` table via PostgREST + service_role.
- `before` / `after` should hold only the changed subset (not full rows) to
  keep payloads small and PII-aware.
- audit_logs is append-only at the DB level (UPDATE/DELETE triggers reject).
  Retention purges go through the purge_old_audit_logs() SECURITY DEFINER
  function — see migrate_audit_logs_immutability.sql.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from fastapi import Header, Request
from jose import JWTError, jwt

from app.core.config import settings

_log = logging.getLogger("app.audit")

# Default retention — keep 90 days of admin history.
# (보관 기간 기본값 — admin 변경 이력 90일 유지)
AUDIT_RETENTION_DAYS = 90
# Run retention purge once a day.
AUDIT_PURGE_INTERVAL_SECONDS = 24 * 60 * 60

_HEADERS = {
    "apikey": settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}
_REST = f"{settings.supabase_url}/rest/v1"


async def audit_log(
    *,
    actor_user_id: str,
    actor_email: str | None = None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Write a single audit row. Never raises.
    (단일 감사 row 기록 — 절대 예외 던지지 않음)
    """
    payload: dict[str, Any] = {
        "actor_user_id": actor_user_id,
        "actor_email":   actor_email,
        "action":        action,
        "target_type":   target_type,
        "target_id":     target_id,
        "before":        before,
        "after":         after,
        "ip_address":    ip_address,
        "user_agent":    user_agent,
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.post(f"{_REST}/audit_logs", headers=_HEADERS, json=payload)
            if r.status_code >= 300:
                _log.warning(
                    "audit_log non-2xx: status=%s action=%s body=%s",
                    r.status_code, action, r.text[:200],
                )
    except Exception:
        _log.exception("audit_log write failed: action=%s", action)


# ── Retention purge ──────────────────────────────────────────────────────────


async def purge_old_audit_logs(retention_days: int = AUDIT_RETENTION_DAYS) -> int:
    """Call the SECURITY DEFINER function to drop rows older than retention.
    Returns the number of rows purged (0 if function missing / error).
    (보관 기간 초과 row를 SECURITY DEFINER 함수로 삭제, 삭제 수 반환)
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(
                f"{_REST}/rpc/purge_old_audit_logs",
                headers=_HEADERS,
                json={"retention_days": retention_days},
            )
            if r.status_code >= 300:
                _log.warning(
                    "audit retention purge non-2xx: %s %s",
                    r.status_code, r.text[:200],
                )
                return 0
            # RPC returns the integer count directly
            data = r.json()
            return int(data) if isinstance(data, int) else 0
    except Exception:
        _log.exception("audit retention purge failed")
        return 0


async def get_actor(
    request: Request,
    authorization: str | None = Header(None),
) -> dict[str, str | None]:
    """FastAPI dependency — extract actor context from JWT for audit_log calls.
    Returns {user_id, email, ip_address, user_agent}. All fields may be None.
    Never raises (audit must not break the request). JWT signature is NOT
    re-validated here (the calling endpoint's own auth dep already did that).
    (감사용 actor 추출 — JWT payload만 가볍게 디코드, 서명 재검증 X)
    """
    user_id: str | None = None
    email: str | None = None
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            try:
                payload = jwt.get_unverified_claims(parts[1])
                user_id = payload.get("sub")
                email = (payload.get("email") or "").lower() or None
            except JWTError:
                pass
    return {
        "user_id":    user_id,
        "email":      email,
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }


async def run_retention_loop() -> None:
    """Background loop — purge once on startup then every 24h.
    Cancelled on app shutdown via lifespan teardown.
    (시작 시 1회 + 매 24시간마다 보관 기간 초과 row 정리)
    """
    while True:
        try:
            deleted = await purge_old_audit_logs()
            if deleted > 0:
                _log.info(
                    "audit retention purged %d rows (>%d days)",
                    deleted, AUDIT_RETENTION_DAYS,
                )
        except Exception:
            _log.exception("retention loop iteration failed")
        await asyncio.sleep(AUDIT_PURGE_INTERVAL_SECONDS)
