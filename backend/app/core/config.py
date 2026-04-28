# Application settings loaded from environment variables (환경 변수에서 로드하는 애플리케이션 설정)
# Layer 1 — Core Security & Configuration (Layer 1 — 핵심 보안 및 설정)

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Pydantic-settings model for application configuration.

    All required fields must be present as environment variables or in .env file.
    (모든 필수 필드는 환경 변수 또는 .env 파일에 있어야 함)
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Ignore unknown env vars (알 수 없는 환경 변수 무시)
    )

    # Supabase project URL — required (Supabase 프로젝트 URL — 필수)
    supabase_url: str

    # Supabase service role key for privileged DB access — required
    # (권한 있는 DB 접근을 위한 Supabase 서비스 역할 키 — 필수)
    supabase_service_role_key: str

    # Google Gemini API key — required (Google Gemini API 키 — 필수)
    gemini_api_key: str

    # Debug mode flag, defaults to False (디버그 모드 플래그, 기본값 False)
    debug: bool = False

    # Solink CCTV API — OAuth2 client credentials flow (Solink OAuth2 클라이언트 자격증명 플로우)
    solink_api_url: str = "https://api-prod-us-west-2.solinkcloud.com/v2"
    solink_token_url: str = "https://api-prod-us-west-2.solinkcloud.com/v2/oauth/token"
    solink_audience: str = "https://prod.solinkcloud.com/"
    solink_client_id: str = ""    # OAuth2 client_id
    solink_client_secret: str = ""  # OAuth2 client_secret
    solink_api_key: str = ""      # x-api-key header required on all Solink requests (모든 요청에 필요한 x-api-key)

    # Loyverse POS API (Loyverse POS API 설정)
    loyverse_api_url: str = "https://api.loyverse.com/v1.0"
    loyverse_api_key: str = ""  # Loyverse bearer token

    # Retell AI — STT/TTS/VAT engine (Retell AI — 음성 엔진)
    retell_api_key: str = ""     # Bearer token for Retell REST API (Retell REST API용 Bearer 토큰)
    retell_api_url: str = "https://api.retellai.com"  # No /v2 prefix for agent endpoints (/v2 없음)

    # Twilio SMS — post-event customer notifications (Twilio SMS — 이벤트 후 고객 알림)
    twilio_account_sid: str = ""   # Twilio Account SID (AC...)
    twilio_auth_token:  str = ""   # Twilio Auth Token
    twilio_from_number: str = ""   # E.164 sender number (e.g. +15555550100)

    # Relay timeout (릴레이 타임아웃)
    relay_timeout_seconds: int = 8


# Module-level singleton — loaded once at import time (임포트 시 한 번 로드되는 모듈 수준 싱글톤)
settings = Settings()
