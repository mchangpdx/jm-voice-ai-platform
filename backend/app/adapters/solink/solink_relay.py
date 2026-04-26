# Solink CCTV relay adapter — Layer 4 External Bridge
# (Solink CCTV 릴레이 어댑터 — Layer 4 외부 브리지)
# Auth: OAuth2 client_credentials → Bearer token + x-api-key header on every call
# (인증: OAuth2 클라이언트 자격증명 → 모든 호출에 Bearer 토큰 + x-api-key 헤더 필요)

import logging
from datetime import datetime, timezone
from uuid import uuid4

import httpx

logger = logging.getLogger(__name__)


class SolinkRelay:
    """Relay bridge to the Solink CCTV cloud API (us-west-2 region).

    Authentication flow (인증 플로우):
      1. POST /oauth/token with client_id + client_secret → access_token
      2. Use Bearer {access_token} + x-api-key: {api_key} on all subsequent calls

    Fire-and-Forget pattern applies to relay_event().
    Camera/video/snapshot calls are awaited synchronously (callers decide async strategy).
    """

    def __init__(
        self,
        api_url: str,
        token_url: str,
        audience: str,
        client_id: str,
        client_secret: str,
        api_key: str,
        timeout: int = 8,
    ) -> None:
        self.api_url = api_url.rstrip("/")      # Base URL (기본 URL)
        self.token_url = token_url              # OAuth2 token endpoint (토큰 엔드포인트)
        self.audience = audience                # OAuth2 audience (대상 청중)
        self.client_id = client_id             # OAuth2 client_id
        self.client_secret = client_secret     # OAuth2 client_secret
        self.api_key = api_key                 # x-api-key header value (x-api-key 헤더 값)
        self.timeout = timeout

    async def _get_access_token(self) -> str:
        """Fetch a short-lived OAuth2 access token from Solink.
        Uses client_credentials grant — no user interaction required.
        (클라이언트 자격증명 그랜트로 Solink OAuth2 액세스 토큰 발급 — 사용자 인터랙션 불필요)
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self.token_url,
                json={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "client_credentials",
                    "audience": self.audience,
                },
                headers={"x-api-key": self.api_key},
            )
            response.raise_for_status()
            return response.json()["access_token"]

    def _auth_headers(self, token: str) -> dict:
        """Build headers required for every authenticated Solink API call.
        (모든 인증된 Solink API 호출에 필요한 헤더 생성)
        """
        return {
            "Authorization": f"Bearer {token}",
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }

    async def get_cameras(self) -> list[dict]:
        """List all cameras registered to this Solink account.
        Returns normalized list of {id, name, status}.
        (Solink 계정에 등록된 모든 카메라 목록 반환. {id, name, status} 정규화)
        """
        try:
            token = await self._get_access_token()
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.api_url}/cameras",
                    headers=self._auth_headers(token),
                )
                response.raise_for_status()
                raw = response.json()
                cameras = raw if isinstance(raw, list) else []
                return [
                    {
                        "id": cam.get("id") or cam.get("cameraId", ""),
                        "name": cam.get("name") or cam.get("label", "Unnamed Camera"),
                        "status": cam.get("status", "unknown"),
                    }
                    for cam in cameras
                ]
        except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            logger.error("SolinkRelay.get_cameras failed: %s", exc)
            return []

    async def get_video_link(self, camera_id: str, timestamp_iso: str) -> str | None:
        """Fetch a video playback URL for a given camera and moment.
        Timestamp must be ISO 8601 (converted to Unix seconds for Solink).
        (카메라와 특정 시각의 영상 재생 URL 조회. 타임스탬프는 ISO 8601 → Unix 초 변환)
        """
        try:
            ts_ms = int(datetime.fromisoformat(timestamp_iso.replace("Z", "+00:00")).timestamp() * 1000)
            ts_seconds = ts_ms // 1000  # Solink requires Unix seconds (Solink는 Unix 초 단위 요구)
            token = await self._get_access_token()
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.api_url}/video/link",
                    headers=self._auth_headers(token),
                    params={"cameraId": camera_id, "timestamp": ts_seconds},
                )
                response.raise_for_status()
                return response.json().get("url")
        except (httpx.TimeoutException, httpx.HTTPStatusError, KeyError, ValueError) as exc:
            logger.error("SolinkRelay.get_video_link failed camera=%s: %s", camera_id, exc)
            return None

    async def get_snapshot(self, camera_id: str, timestamp_iso: str) -> bytes | None:
        """Fetch a raw JPEG snapshot for a given camera and moment.
        Returns binary image data, or None on failure.
        (카메라의 특정 시각 JPEG 스냅샷 이미지(바이너리) 반환. 실패 시 None)
        """
        try:
            token = await self._get_access_token()
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.api_url}/cameras/{camera_id}/snapshot",
                    headers=self._auth_headers(token),
                    params={"timestamp": timestamp_iso},  # Snapshot API uses ISO string (스냅샷 API는 ISO 문자열 사용)
                )
                response.raise_for_status()
                return response.content
        except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            logger.error("SolinkRelay.get_snapshot failed camera=%s: %s", camera_id, exc)
            return None

    async def relay_event(self, event_data: dict, tenant_id: str) -> dict:
        """Fire-and-Forget: forward a security event with X-Tenant-ID RLS header.
        Generates relay_id before the background call so callers can track the job.
        (X-Tenant-ID RLS 헤더로 보안 이벤트 비동기 전달. 릴레이 ID를 미리 생성해 추적 가능)
        """
        relay_id = str(uuid4())
        queued_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        try:
            token = await self._get_access_token()
            headers = self._auth_headers(token)
            headers["X-Tenant-ID"] = tenant_id  # RLS routing (RLS 라우팅)

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.api_url}/events",
                    headers=headers,
                    json=event_data,
                )
                response.raise_for_status()

        except httpx.TimeoutException as exc:
            logger.error("SolinkRelay.relay_event timed out tenant=%s: %s", tenant_id, exc)
        except httpx.HTTPStatusError as exc:
            logger.error(
                "SolinkRelay.relay_event HTTP %s tenant=%s: %s",
                exc.response.status_code, tenant_id, exc,
            )
        except Exception as exc:  # OAuth token failures or unexpected errors (OAuth 토큰 오류 등)
            logger.error("SolinkRelay.relay_event unexpected error tenant=%s: %s", tenant_id, exc)

        return {"relay_id": relay_id, "queued_at": queued_at}
