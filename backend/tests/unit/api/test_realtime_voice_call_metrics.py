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
