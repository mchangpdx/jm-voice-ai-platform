"""
JM Voice AI Platform — FastAPI Application Entry Point
(JM Voice AI 플랫폼 — FastAPI 애플리케이션 진입점)
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.audit import run_retention_loop  # Phase 2-D.2 — 90-day audit retention
from app.core.api_errors import ApiErrorTracker  # Phase 2-C — system health 4xx/5xx ring buffer


from app.api.agency import router as agency_router          # Agency multi-store dashboard (에이전시 멀티스토어 대시보드)
from app.api.analytics import router as analytics_router    # Analytics charts (분석 차트)
from app.api.auth import router as auth_router              # Auth login bridge (인증 로그인 브리지)
from app.api.menu import router as menu_router              # Menu sync + Loyverse inventory webhook (메뉴 동기화 + 인벤토리 웹훅)
from app.api.payment import router as payment_router        # Pay link mock callback (결제 링크 목 콜백)
from app.api.relay import router as relay_router            # Layer 4 Relay Bridge router (Layer 4 릴레이 브리지 라우터)
from app.api.reservations import router as reservations_router  # Reservations (예약 관리)
from app.api.settings import router as settings_router      # Store settings (스토어 설정)
from app.api.store import router as store_router            # Store dashboard data (스토어 대시보드 데이터)
from app.api.voice_bot import router as voice_bot_router    # AI Voice Bot settings (AI Voice Bot 설정)
from app.api.voice_websocket import router as voice_ws_router  # Retell Custom LLM WebSocket (Retell ↔ Gemini 브리지)
from app.api.realtime_voice import router as realtime_router  # Phase 2-D — Twilio Media Streams ↔ OpenAI Realtime (듀얼 트랙)
from app.api.admin.sync_control import router as admin_sync_router  # Phase 7-A — sync freeze toggle (관리 API — sync freeze)
from app.api.admin.onboarding import router as admin_onboarding_router  # 2026-05-12 — menu onboarding wizard endpoints (메뉴 온보딩 마법사)
from app.api.admin.mock_menu import router as admin_mock_menu_router  # 2026-05-15 TEMP — Mexican validation mock menu (검증용 임시)
from app.api.admin.platform import router as admin_platform_router  # 2026-05-17 — platform admin read-only (모든 agency·store 조회)
from app.api.admin.users import router as admin_users_router  # 2026-05-18 — Phase 2-B users & roles management
from app.api.public.menu_viewer import router as public_menu_router  # 2026-05-15 — public /menu/{slug} viewer (공개 메뉴 뷰어)
from app.api.public.scripts_viewer import router as public_scripts_router  # 2026-05-15 — public /scripts/{slug} test-call scripts (공개 통화 스크립트 뷰어)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Wire app.* loggers to uvicorn's handler on startup (uvicorn 시작 시 앱 로거 연결)
    uvicorn_handlers = logging.getLogger("uvicorn.error").handlers
    app_log = logging.getLogger("app")
    app_log.setLevel(logging.INFO)
    app_log.propagate = False
    for h in uvicorn_handlers:
        if h not in app_log.handlers:
            app_log.addHandler(h)

    # Start background retention loop (audit_logs 90-day purge)
    retention_task = asyncio.create_task(run_retention_loop())
    try:
        yield
    finally:
        retention_task.cancel()
        try:
            await retention_task
        except (asyncio.CancelledError, Exception):
            pass


app = FastAPI(
    title="JM Voice AI Platform",
    description="One Stop Total Solution — Voice AI + POS + CCTV",
    version="0.4.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    # Explicit headers required — wildcards are rejected with credentials by spec (자격증명 포함 시 와일드카드 사용 불가)
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
)

# Record every 4xx/5xx into an in-memory ring buffer for /admin/system-health
# (Phase 2-C — admin system health 패널용 에러 집계 미들웨어)
app.add_middleware(ApiErrorTracker)

app.include_router(auth_router)          # Auth (인증)
app.include_router(agency_router)        # Agency multi-store dashboard (에이전시 멀티스토어 대시보드)
app.include_router(relay_router)         # Layer 4 Relay Bridge (Layer 4 릴레이 브리지)
app.include_router(store_router)         # Store dashboard (스토어 대시보드)
app.include_router(settings_router)      # Store settings (스토어 설정)
app.include_router(reservations_router)  # Reservations (예약 관리)
app.include_router(analytics_router)     # Analytics (분석)
app.include_router(voice_bot_router)     # AI Voice Bot settings (AI Voice Bot 설정)
app.include_router(voice_ws_router)      # Retell Custom LLM WebSocket (Retell ↔ Gemini 브리지)
app.include_router(realtime_router)      # Phase 2-D — Twilio Media Streams ↔ OpenAI Realtime 브리지 (듀얼 트랙)
app.include_router(menu_router)          # Menu sync + Loyverse inventory webhook (메뉴 동기화 + 인벤토리 웹훅)
app.include_router(payment_router)       # Pay link mock callback (결제 링크 목 콜백)
app.include_router(admin_sync_router)    # Phase 7-A — sync freeze toggle (관리 API — sync freeze)
app.include_router(admin_onboarding_router)  # 2026-05-12 — menu onboarding wizard (메뉴 온보딩 마법사 API)
app.include_router(admin_mock_menu_router)  # 2026-05-15 TEMP — Mexican validation mock menu (검증용 임시, 검증 후 제거)
app.include_router(admin_platform_router)  # 2026-05-17 — platform admin read-only (모든 agency·store)
app.include_router(admin_users_router)     # 2026-05-18 — Phase 2-B users & roles (사용자 + 역할 관리)
app.include_router(public_menu_router)      # 2026-05-15 — public /menu/{slug} viewer (공개 메뉴 뷰어, 모든 매장 자동 지원)
app.include_router(public_scripts_router)   # 2026-05-15 — public /scripts/{slug} test-call scripts (공개 통화 스크립트 뷰어)


@app.get("/health")
async def health():
    # Health check endpoint (헬스 체크 엔드포인트)
    return {"status": "ok", "service": "jm-voice-ai-platform"}
