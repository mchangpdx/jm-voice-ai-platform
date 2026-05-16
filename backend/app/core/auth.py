# JWT tenant resolver — FastAPI dependency for Layer 1 security
# (Layer 1 보안용 FastAPI 의존성 — JWT 테넌트 리졸버)
# Layer 1 — Core Security & Configuration (Layer 1 — 핵심 보안 및 설정)
#
# Algorithm dispatch:
#   HS256  → validate with supabase_service_role_key (test / legacy tokens)
#   ES256  → validate with JWKS public key from Supabase (production tokens)
# (알고리즘 분기: HS256은 서비스 역할 키, ES256은 JWKS 공개키로 검증)

import httpx
from fastapi import Header, HTTPException
from jose import ExpiredSignatureError, JWTError, jwt

from app.core.config import settings

# Module-level JWKS cache — fetched once per process (프로세스당 한 번 로드되는 JWKS 캐시)
_jwks_cache: dict[str, dict] = {}


async def _get_public_key(kid: str) -> dict:
    """Return the JWKS public key dict for the given kid, fetching from Supabase if needed.
    (kid에 해당하는 JWKS 공개키 반환, 필요 시 Supabase에서 조회)
    """
    global _jwks_cache
    if kid not in _jwks_cache:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
            )
            for key in resp.json().get("keys", []):
                _jwks_cache[key["kid"]] = key
    return _jwks_cache.get(kid, {})


async def _decode_jwt_payload(authorization: str | None) -> dict:
    """Validate JWT and return full decoded payload. (JWT 검증 + 전체 payload 반환)

    Supports both ES256 (production Supabase tokens) and HS256 (test/legacy tokens).
    Raises HTTP 401 for missing, malformed, expired, or otherwise invalid tokens.
    """
    if authorization is None:
        raise HTTPException(
            status_code=401,
            detail="Authorization header is missing",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Authorization header must be in 'Bearer <token>' format",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw_token = parts[1]

    try:
        header = jwt.get_unverified_header(raw_token)
    except JWTError:
        raise HTTPException(
            status_code=401,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    alg = header.get("alg", "ES256")

    try:
        if alg == "HS256":
            # Test / legacy path — validate with service_role_key
            # (테스트/레거시 경로 — 서비스 역할 키로 검증)
            payload = jwt.decode(
                raw_token,
                settings.supabase_service_role_key,
                algorithms=["HS256"],
            )
        else:
            # Production path — fetch JWKS and validate with EC public key
            # (프로덕션 경로 — JWKS에서 EC 공개키를 가져와 검증)
            kid = header.get("kid", "")
            public_key = await _get_public_key(kid)
            if not public_key:
                raise HTTPException(
                    status_code=401,
                    detail="Unknown token signing key",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            # Supabase sets aud="authenticated"; skip aud validation
            # (Supabase는 aud="authenticated" 설정; aud 검증 생략)
            payload = jwt.decode(
                raw_token,
                public_key,
                algorithms=[alg],
                options={"verify_aud": False},
            )
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError:
        raise HTTPException(
            status_code=401,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


async def get_tenant_id(authorization: str = Header(None)) -> str:
    """Extract and validate the Supabase JWT, returning the tenant_id (sub claim).
    (JWT 검증 후 sub 클레임을 tenant_id로 반환)
    """
    payload = await _decode_jwt_payload(authorization)
    tenant_id: str | None = payload.get("sub")
    if not tenant_id:
        raise HTTPException(
            status_code=401,
            detail="Token missing 'sub' claim",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return tenant_id


async def is_platform_admin(authorization: str = Header(None)) -> bool:
    """Return True if JWT app_metadata.role == 'admin'.
    (JWT의 app_metadata.role이 'admin'이면 True)

    Phase 2-E migration helper — replaces hardcoded user_id allowlists and
    email matches with the canonical Supabase role claim. Provisioned by
    `scripts/seed_admin_role.py` and `PATCH /api/admin/users/{id}/role`.
    """
    payload = await _decode_jwt_payload(authorization)
    role = ((payload.get("app_metadata") or {}).get("role") or "").lower()
    return role == "admin"
