# Auth API router — Supabase JWT login bridge (인증 API 라우터 — Supabase JWT 로그인 브리지)

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.config import settings

router = APIRouter(prefix="/api/auth", tags=["Auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest) -> LoginResponse:
    """Authenticate via Supabase and return a JWT for subsequent API calls.
    (Supabase로 인증 후 이후 API 호출에 사용할 JWT 반환)
    """
    url = f"{settings.supabase_url}/auth/v1/token?grant_type=password"
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=headers, json={"email": body.email, "password": body.password})

    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    data = resp.json()
    return LoginResponse(access_token=data["access_token"], token_type=data["token_type"])
