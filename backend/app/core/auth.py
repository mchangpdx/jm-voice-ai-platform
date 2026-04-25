# JWT tenant resolver — FastAPI dependency for Layer 1 security
# (Layer 1 보안용 FastAPI 의존성 — JWT 테넌트 리졸버)
# Layer 1 — Core Security & Configuration (Layer 1 — 핵심 보안 및 설정)

from fastapi import Header, HTTPException
from jose import ExpiredSignatureError, JWTError, jwt

from app.core.config import settings


async def get_tenant_id(authorization: str = Header(None)) -> str:
    """Extract and validate the Supabase JWT, returning the tenant_id (sub claim).

    Raises HTTP 401 for missing, malformed, expired, or otherwise invalid tokens.
    (누락, 형식 오류, 만료 또는 유효하지 않은 토큰에 대해 HTTP 401 반환)
    """
    # Reject missing header immediately (헤더 누락 즉시 거부)
    if authorization is None:
        raise HTTPException(
            status_code=401,
            detail="Authorization header is missing",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Expect "Bearer <token>" format (Bearer <token> 형식 검증)
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Authorization header must be in 'Bearer <token>' format",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw_token = parts[1]

    try:
        # Decode JWT locally using service role key as secret
        # (서비스 역할 키를 비밀로 사용해 JWT를 로컬에서 디코딩)
        payload = jwt.decode(
            raw_token,
            settings.supabase_service_role_key,
            algorithms=["HS256"],
        )
    except ExpiredSignatureError:
        # Token has expired — return 401 with WWW-Authenticate header
        # (토큰 만료 — WWW-Authenticate 헤더와 함께 401 반환)
        raise HTTPException(
            status_code=401,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError:
        # Any other JWT decode failure (기타 JWT 디코딩 오류)
        raise HTTPException(
            status_code=401,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Extract sub claim as tenant_id (sub 클레임을 tenant_id로 추출)
    tenant_id: str | None = payload.get("sub")
    if not tenant_id:
        raise HTTPException(
            status_code=401,
            detail="Token missing 'sub' claim",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return tenant_id
