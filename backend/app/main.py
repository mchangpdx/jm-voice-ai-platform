"""
JM Voice AI Platform — FastAPI Application Entry Point
(JM Voice AI 플랫폼 — FastAPI 애플리케이션 진입점)
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="JM Voice AI Platform",
    description="One Stop Total Solution — Voice AI + POS + CCTV",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    # Explicit headers required — wildcards are rejected with credentials by spec (자격증명 포함 시 와일드카드 사용 불가)
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
)


@app.get("/health")
async def health():
    # Health check endpoint (헬스 체크 엔드포인트)
    return {"status": "ok", "service": "jm-voice-ai-platform"}
