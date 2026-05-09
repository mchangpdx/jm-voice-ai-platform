# CRM Wave 1 — call_end metrics + usual detection unit tests (Tier 3, R1–R4)
# (CRM Wave 1 — 통화 종료 영속화 + "the usual" 정규식 단위 테스트)

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.realtime_voice import _THE_USUAL_RE
from app.services.bridge.transactions import update_call_metrics


# ── R1: update_call_metrics with full payload PATCHes correctly ───────────────

@pytest.mark.asyncio
async def test_r1_update_call_metrics_sends_full_payload():
    fake_resp = MagicMock()
    fake_resp.status_code = 204
    fake_resp.text = ""

    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__  = AsyncMock(return_value=None)
    client.patch = AsyncMock(return_value=fake_resp)

    with patch("app.services.bridge.transactions.httpx.AsyncClient",
               return_value=client):
        await update_call_metrics(
            transaction_id     = "tx-abcd-1234",
            call_duration_ms   = 72103,
            crm_returning      = True,
            crm_visit_count    = 7,
            crm_usual_offered  = True,
            crm_usual_accepted = True,
        )

    client.patch.assert_called_once()
    kwargs = client.patch.call_args.kwargs
    body = kwargs["json"]

    assert body["call_duration_ms"]   == 72103
    assert body["crm_returning"]      is True
    assert body["crm_visit_count"]    == 7
    assert body["crm_usual_offered"]  is True
    assert body["crm_usual_accepted"] is True
    assert "updated_at" in body  # always stamped

    params = kwargs["params"]
    assert params == {"id": "eq.tx-abcd-1234"}


# ── R1b: optional fields omitted when None ────────────────────────────────────

@pytest.mark.asyncio
async def test_r1b_optional_fields_omitted_when_none():
    fake_resp = MagicMock()
    fake_resp.status_code = 204
    fake_resp.text = ""
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__  = AsyncMock(return_value=None)
    client.patch = AsyncMock(return_value=fake_resp)

    with patch("app.services.bridge.transactions.httpx.AsyncClient",
               return_value=client):
        await update_call_metrics(
            transaction_id     = "tx-xyz",
            call_duration_ms   = 1000,
            crm_returning      = False,
            crm_visit_count    = 0,
            crm_usual_offered  = False,
            crm_usual_accepted = None,   # explicit None — must be OMITTED
        )

    body = client.patch.call_args.kwargs["json"]
    assert "crm_usual_accepted" not in body  # None → omitted
    assert body["crm_returning"]     is False
    assert body["crm_visit_count"]   == 0
    assert body["crm_usual_offered"] is False


# ── R2: empty tx_id → no HTTP call, info log only ─────────────────────────────

@pytest.mark.asyncio
async def test_r2_no_tx_id_skips_http_call():
    """Mid-call hangup path — caller passes "" because session_state never
    latched an active_tx_id. Function must short-circuit without opening
    an HTTP client.
    """
    with patch("app.services.bridge.transactions.httpx.AsyncClient") as MockClient:
        await update_call_metrics(
            transaction_id   = "",
            call_duration_ms = 5000,
        )
    MockClient.assert_not_called()


# ── R3: 5xx response → warn log, never raises ─────────────────────────────────

@pytest.mark.asyncio
async def test_r3_5xx_does_not_raise():
    fake_resp = MagicMock()
    fake_resp.status_code = 503
    fake_resp.text = "service unavailable"

    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__  = AsyncMock(return_value=None)
    client.patch = AsyncMock(return_value=fake_resp)

    with patch("app.services.bridge.transactions.httpx.AsyncClient",
               return_value=client):
        # The whole point of the function is that a failure here MUST NOT
        # raise into the WS finally block (the call has already ended).
        await update_call_metrics(
            transaction_id   = "tx-9",
            call_duration_ms = 5000,
            crm_returning    = True,
            crm_visit_count  = 1,
        )


# ── R3b: client raises on PATCH → swallowed, never raises ─────────────────────

@pytest.mark.asyncio
async def test_r3b_client_exception_swallowed():
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__  = AsyncMock(return_value=None)
    client.patch = AsyncMock(side_effect=ConnectionError("boom"))

    with patch("app.services.bridge.transactions.httpx.AsyncClient",
               return_value=client):
        # Should not raise
        await update_call_metrics(
            transaction_id   = "tx-broken",
            call_duration_ms = 1234,
        )


# ── R4: _THE_USUAL_RE word-boundary + case insensitive matrix ─────────────────

class TestUsualRegex:
    @pytest.mark.parametrize("text", [
        "would you like the usual",
        "Would you like the usual?",
        "the Usual",
        "THE USUAL",
        "the   usual",  # multiple spaces
        "...the usual, iced oat latte large?",
        "I'll go with the usual please",
    ])
    def test_matches_positive(self, text: str):
        assert _THE_USUAL_RE.search(text) is not None

    @pytest.mark.parametrize("text", [
        "theusual",       # no whitespace
        "the unusual",    # 'usual' is a substring of 'unusual'
        "usually",        # word boundary fails
        "ritual",
        "thesual",
        "the usu al",     # broken word
        "",
    ])
    def test_matches_negative(self, text: str):
        assert _THE_USUAL_RE.search(text) is None

    # FIX-D (2026-05-09): multilingual usual-offer detector — Korean/Japanese/
    # Chinese/Spanish positive cases. Live regression: KO agent said
    # "평소 드시던 20온스 뜨거운 오트밀크 카페라떼로 하실까요" but DB column
    # stayed False because pre-fix regex was English-only.
    @pytest.mark.parametrize("text", [
        # Korean
        "평소처럼 아이스 오트 라떼로 드릴까요?",
        "평소 드시던 20온스 뜨거운 오트밀크 카페라떼로 하실까요?",
        "평소 같이 준비해 드릴까요?",
        "이전과 같이 준비해 드릴까요?",
        "오늘도 똑같이 드릴까요?",
        # Japanese
        "いつものでよろしいですか?",
        "前回と同じでよろしいですか?",
        # Chinese (Mandarin)
        "老样子嗎?",
        "和上次一样吗?",
        # Spanish
        "¿Lo de siempre?",
        "¿quieres lo usual?",
    ])
    def test_matches_multilingual_positive(self, text: str):
        assert _THE_USUAL_RE.search(text) is not None

    @pytest.mark.parametrize("text", [
        # Off-topic CJK strings should NOT match — these contain none of the
        # configured "usual" keywords, just generic ordering language.
        "안녕하세요, 무엇을 주문하시겠어요?",
        "ご注文は何になさいますか?",
        "您要点什么?",
        "Hola, ¿qué te gustaría ordenar hoy?",
    ])
    def test_matches_multilingual_negative(self, text: str):
        assert _THE_USUAL_RE.search(text) is None


# ── R5: FIX-C active_tx_id latch guard (idempotent re-hit) ──────────────────
# Mirrors the inline guard at realtime_voice.py around line 217:
#   if tx_id_latched and not result.get("idempotent"):
#       session_state["active_tx_id"] = tx_id_latched
# Live regression: 2026-05-09 caller redialed within 5 min → flows.py
# idempotency probe returned same tx_id → call_end overwrote first call's
# AHT + CRM flags. Guard must skip the latch on idempotent re-hits so the
# original tx keeps its analytics. Test-mirrors-source: if the production
# logic changes, update both sides intentionally.
# (FIX-C 분기 검증 — production logic 그대로 시뮬레이션)

class TestActiveTxLatch:
    @staticmethod
    def _apply_latch(session_state: dict, result: dict) -> None:
        """Mirror of realtime_voice.py:208-218 latch behavior."""
        if result.get("success"):
            tx_id_latched = str(result.get("transaction_id") or "")
            if tx_id_latched and not result.get("idempotent"):
                session_state["active_tx_id"] = tx_id_latched

    def test_new_tx_latches_active_tx_id(self):
        session_state = {"active_tx_id": None}
        result = {"success": True, "transaction_id": "new-tx-456"}
        self._apply_latch(session_state, result)
        assert session_state["active_tx_id"] == "new-tx-456"

    def test_idempotent_hit_does_not_latch(self):
        session_state = {"active_tx_id": None}
        result = {"success": True, "idempotent": True,
                  "transaction_id": "prior-call-tx-123"}
        self._apply_latch(session_state, result)
        assert session_state["active_tx_id"] is None  # FIX-C: must NOT latch

    def test_idempotent_hit_does_not_overwrite_existing_latch(self):
        # If a prior NEW create_order in the same call already latched,
        # an idempotent re-hit must not change it (defensive — current
        # production has only one create_order per call but be safe).
        session_state = {"active_tx_id": "prior-new-tx"}
        result = {"success": True, "idempotent": True,
                  "transaction_id": "prior-call-tx-123"}
        self._apply_latch(session_state, result)
        assert session_state["active_tx_id"] == "prior-new-tx"

    def test_failed_create_order_does_not_latch(self):
        session_state = {"active_tx_id": None}
        result = {"success": False, "reason": "validation_failed"}
        self._apply_latch(session_state, result)
        assert session_state["active_tx_id"] is None

    def test_missing_transaction_id_does_not_latch(self):
        session_state = {"active_tx_id": None}
        result = {"success": True, "transaction_id": None}
        self._apply_latch(session_state, result)
        assert session_state["active_tx_id"] is None
