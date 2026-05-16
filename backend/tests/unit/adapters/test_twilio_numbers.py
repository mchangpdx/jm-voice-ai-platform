# A5 (2026-05-17) — Twilio Numbers adapter unit tests.
# (A5 — Twilio Numbers 어댑터 단위 테스트)
#
# Scope: verify update_voice_webhook's behavior contract without
# touching the live Twilio API. We monkeypatch httpx.AsyncClient on
# the adapter module so the assertions cover request shape, error
# fallback, and the credentials-missing skip path.

from __future__ import annotations

import pytest

from app.adapters.twilio import numbers as twilio_numbers


class _FakeResp:
    def __init__(self, status: int, payload: dict | None = None) -> None:
        self.status_code = status
        self._payload = payload or {}
        self.text     = str(self._payload)

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    """Records the GET/POST calls; replies according to a scripted plan."""

    def __init__(self, *_a, **_kw) -> None:
        self.calls: list[dict] = []
        self.script: list[_FakeResp] = []

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False

    async def get(self, url: str, *, params, auth):  # type: ignore[no-untyped-def]
        self.calls.append({"method": "GET", "url": url, "params": params})
        return self.script.pop(0)

    async def post(self, url: str, *, data, auth):  # type: ignore[no-untyped-def]
        self.calls.append({"method": "POST", "url": url, "data": data})
        return self.script.pop(0)


def _wire_client(monkeypatch: pytest.MonkeyPatch) -> _FakeClient:
    client = _FakeClient()

    def factory(*_a, **_kw) -> _FakeClient:
        return client

    monkeypatch.setattr(twilio_numbers.httpx, "AsyncClient", factory)
    return client


@pytest.fixture(autouse=True)
def _force_creds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test runs as if Twilio creds are set unless overridden."""
    monkeypatch.setattr(twilio_numbers, "_TWILIO_SID",   "ACtest")
    monkeypatch.setattr(twilio_numbers, "_TWILIO_TOKEN", "tok_test")


# ── Behavior contract ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_returns_invalid_phone_for_missing_e164() -> None:
    out = await twilio_numbers.update_voice_webhook(
        phone_e164="", webhook_url="https://x/inbound",
    )
    assert out["ok"] is False
    assert out["reason"] == "invalid_phone"


@pytest.mark.asyncio
async def test_returns_invalid_phone_for_non_e164() -> None:
    out = await twilio_numbers.update_voice_webhook(
        phone_e164="5035551234", webhook_url="https://x/inbound",
    )
    assert out["ok"] is False
    assert out["reason"] == "invalid_phone"


@pytest.mark.asyncio
async def test_returns_no_webhook_url_when_missing() -> None:
    out = await twilio_numbers.update_voice_webhook(
        phone_e164="+15035551234", webhook_url="",
    )
    assert out["ok"] is False
    assert out["reason"] == "no_webhook_url"


@pytest.mark.asyncio
async def test_skips_when_creds_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(twilio_numbers, "_TWILIO_SID",   "")
    monkeypatch.setattr(twilio_numbers, "_TWILIO_TOKEN", "")
    out = await twilio_numbers.update_voice_webhook(
        phone_e164="+15035551234", webhook_url="https://x/inbound",
    )
    assert out["ok"] is False
    assert out["reason"] == "twilio_not_configured"


@pytest.mark.asyncio
async def test_phone_not_owned_returns_friendly_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _wire_client(monkeypatch)
    # Lookup succeeds but the account owns no matching number.
    client.script = [_FakeResp(200, {"incoming_phone_numbers": []})]

    out = await twilio_numbers.update_voice_webhook(
        phone_e164="+15035551234", webhook_url="https://x/inbound",
    )
    assert out["ok"] is False
    assert out["reason"] == "phone_not_owned_by_account"
    # Only one HTTP call — we never PATCH when the SID is unresolved.
    assert len(client.calls) == 1
    assert client.calls[0]["method"] == "GET"


@pytest.mark.asyncio
async def test_happy_path_returns_ok_and_sid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _wire_client(monkeypatch)
    client.script = [
        _FakeResp(200, {"incoming_phone_numbers": [{"sid": "PN123"}]}),
        _FakeResp(200, {"voice_url": "https://x/inbound", "sid": "PN123"}),
    ]

    out = await twilio_numbers.update_voice_webhook(
        phone_e164="+15035551234", webhook_url="https://x/inbound",
    )
    assert out["ok"] is True
    assert out["sid"] == "PN123"
    assert out["voice_url"] == "https://x/inbound"

    # Verify the PATCH request shape — VoiceUrl + VoiceMethod must be
    # form-encoded onto the IncomingPhoneNumbers/{Sid}.json endpoint.
    post_call = next(c for c in client.calls if c["method"] == "POST")
    assert "/IncomingPhoneNumbers/PN123.json" in post_call["url"]
    assert post_call["data"] == {
        "VoiceUrl": "https://x/inbound",
        "VoiceMethod": "POST",
    }


@pytest.mark.asyncio
async def test_lookup_http_failure_surfaces_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _wire_client(monkeypatch)
    client.script = [_FakeResp(401, {"message": "unauth"})]

    out = await twilio_numbers.update_voice_webhook(
        phone_e164="+15035551234", webhook_url="https://x/inbound",
    )
    # 401 on lookup → empty rows → phone_not_owned. We could distinguish
    # auth failures later, but the operator-facing fallback is identical
    # (manually paste the URL into Twilio Console), so reuse the path.
    assert out["ok"] is False
    assert out["reason"] in {"phone_not_owned_by_account"}


@pytest.mark.asyncio
async def test_patch_http_failure_returns_status_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _wire_client(monkeypatch)
    client.script = [
        _FakeResp(200, {"incoming_phone_numbers": [{"sid": "PN123"}]}),
        _FakeResp(500, {"message": "server error"}),
    ]

    out = await twilio_numbers.update_voice_webhook(
        phone_e164="+15035551234", webhook_url="https://x/inbound",
    )
    assert out["ok"] is False
    assert out["reason"] == "http_500"


@pytest.mark.asyncio
async def test_method_override_threads_through_to_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _wire_client(monkeypatch)
    client.script = [
        _FakeResp(200, {"incoming_phone_numbers": [{"sid": "PN123"}]}),
        _FakeResp(200, {"voice_url": "https://x/inbound"}),
    ]
    await twilio_numbers.update_voice_webhook(
        phone_e164="+15035551234",
        webhook_url="https://x/inbound",
        method="get",
    )
    post_call = next(c for c in client.calls if c["method"] == "POST")
    assert post_call["data"]["VoiceMethod"] == "GET"
