"""
Phase 2-E — One-time: set app_metadata.role='admin' for platform admin user(s).
(현재 플랫폼 관리자 계정에 app_metadata.role='admin' 부여 — 1회 실행)

Why:
  Until this runs, the backend falls back to a hardcoded user_id allowlist
  (`_ADMIN_USER_IDS`) and email match (`admin@test.com`) to grant ADMIN
  privileges. After this runs, those shortcuts are removed and the JWT's
  app_metadata.role claim drives authorization.

Run from backend/ directory:
    PYTHONPATH=. .venv/bin/python scripts/seed_admin_role.py            # apply
    PYTHONPATH=. .venv/bin/python scripts/seed_admin_role.py --dry-run  # print plan only

After running, the admin user MUST log out + log back in for their new JWT
to carry app_metadata.role='admin'.
(실행 후 admin 계정은 반드시 재로그인해야 새 JWT에 role이 포함됨)
"""
from __future__ import annotations

import asyncio
import sys

import httpx

from app.core.config import settings

# Existing platform admins — add new user_ids here when promoting more admins.
# Phase 2-B Users & Roles page replaces this with on-demand PATCH /users/{id}/role.
# (Phase 2-B Users & Roles 페이지가 등장하면 이 목록 대신 UI에서 부여)
ADMIN_USER_IDS: list[str] = [
    "ba885c40-a9ed-4fba-a307-fe3db8329377",  # admin@test.com
]


async def main(dry_run: bool = False) -> int:
    headers = {
        "apikey":        settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type":  "application/json",
    }
    base = f"{settings.supabase_url}/auth/v1/admin/users"

    print(f"Target admin user_ids: {ADMIN_USER_IDS}")
    if dry_run:
        print("[dry-run] Would PUT app_metadata.role='admin' for each user_id above.")
        return 0

    failures = 0
    async with httpx.AsyncClient(timeout=15) as c:
        for uid in ADMIN_USER_IDS:
            # PUT preserves other app_metadata keys per Supabase admin API
            # (Supabase admin API는 PUT 시 다른 app_metadata 키 보존)
            r = await c.put(
                f"{base}/{uid}",
                headers=headers,
                json={"app_metadata": {"role": "admin"}},
            )
            email = ""
            try:
                email = r.json().get("email", "")
            except Exception:
                pass
            ok = r.status_code == 200
            status = "OK" if ok else "FAIL"
            print(f"  [{status}] {uid}  {email}  (http {r.status_code})")
            if not ok:
                failures += 1
                print(f"        body: {r.text[:200]}")

    if failures:
        print(f"\n{failures} failure(s). Verify SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY in .env.")
        return 1
    print("\nDone. Admin users must log out + log back in to refresh JWT claims.")
    return 0


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    sys.exit(asyncio.run(main(dry_run=dry)))
