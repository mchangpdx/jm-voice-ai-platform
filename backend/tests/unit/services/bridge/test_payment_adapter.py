# Bridge Server — Payment Adapter interface TDD tests
# (Bridge Server — 결제 어댑터 인터페이스 TDD 테스트)
#
# PaymentAdapter abstracts the payment gateway.
# Today: NoOpPaymentAdapter (amount=0 case for free reservations — instant succeed)
# Future: MaverickPaymentAdapter (HPP create + webhook verify, awaits real spec)
#
# Both implement the same protocol so the bridge orchestration code is identical.

import pytest


# ── Interface contract ────────────────────────────────────────────────────────

def test_payment_adapter_base_defines_protocol():
    from app.services.bridge.payments.base import PaymentAdapter

    for method in ("create_session", "verify_webhook", "is_enabled"):
        assert hasattr(PaymentAdapter, method), f"PaymentAdapter must define {method}"


@pytest.mark.asyncio
async def test_base_methods_raise_not_implemented():
    from app.services.bridge.payments.base import PaymentAdapter

    a = PaymentAdapter()
    with pytest.raises(NotImplementedError):
        await a.create_session(amount_cents=100, transaction_id="x", purpose="full")
    with pytest.raises(NotImplementedError):
        a.verify_webhook(raw_body=b"{}", signature="x")


# ── NoOpPaymentAdapter — current default (no real gateway) ────────────────────

def test_noop_adapter_reports_disabled_when_no_creds():
    from app.services.bridge.payments.noop import NoOpPaymentAdapter
    a = NoOpPaymentAdapter()
    assert a.is_enabled() is False


@pytest.mark.asyncio
async def test_noop_create_session_for_zero_amount_returns_instant_success():
    """Reservations and other free transactions: amount=0 → no gateway call needed.
    Adapter returns {sent: True, paid: True, pay_url: None, session_id: synthetic}.
    """
    from app.services.bridge.payments.noop import NoOpPaymentAdapter

    a = NoOpPaymentAdapter()
    result = await a.create_session(
        amount_cents=0,
        transaction_id="TXN-123",
        purpose="full",
    )
    assert result["paid"] is True
    assert result["pay_url"] is None
    assert result["session_id"].startswith("noop_")
    assert result["amount_cents"] == 0


@pytest.mark.asyncio
async def test_noop_create_session_for_nonzero_amount_returns_pending():
    """Non-zero amount but no real gateway → adapter signals 'cannot collect'.
    Caller is responsible for surfacing this (e.g. mark transaction failed).
    """
    from app.services.bridge.payments.noop import NoOpPaymentAdapter

    a = NoOpPaymentAdapter()
    result = await a.create_session(
        amount_cents=1000,
        transaction_id="TXN-123",
        purpose="full",
    )
    assert result["paid"] is False
    assert result["pay_url"] is None
    assert result.get("reason") == "no_payment_gateway_configured"


def test_noop_verify_webhook_always_false():
    """NoOp gateway never sends webhooks; verifying any payload is a security violation."""
    from app.services.bridge.payments.noop import NoOpPaymentAdapter
    a = NoOpPaymentAdapter()
    assert a.verify_webhook(raw_body=b'{}', signature="anything") is False


# ── Adapter selection (factory pattern, env-driven) ──────────────────────────

def test_get_payment_adapter_returns_noop_when_maverick_disabled(monkeypatch):
    """Factory chooses adapter based on env. Default = NoOp (safe, zero-config)."""
    from app.services.bridge.payments import factory
    from app.services.bridge.payments.noop import NoOpPaymentAdapter

    monkeypatch.setattr(factory.settings, "maverick_enabled", False, raising=False)
    monkeypatch.setattr(factory.settings, "maverick_api_key", "", raising=False)

    a = factory.get_payment_adapter()
    assert isinstance(a, NoOpPaymentAdapter)


def test_get_payment_adapter_returns_maverick_when_enabled_and_keys_set(monkeypatch):
    """Once Maverick is configured, factory returns the real adapter."""
    from app.services.bridge.payments import factory
    from app.services.bridge.payments.maverick import MaverickPaymentAdapter

    monkeypatch.setattr(factory.settings, "maverick_enabled", True, raising=False)
    monkeypatch.setattr(factory.settings, "maverick_api_key", "test_key", raising=False)
    monkeypatch.setattr(factory.settings, "maverick_webhook_secret", "wh_secret", raising=False)

    a = factory.get_payment_adapter()
    assert isinstance(a, MaverickPaymentAdapter)


# ── MaverickPaymentAdapter stub (skeleton until real spec arrives) ────────────

def test_maverick_adapter_class_exists_with_correct_interface():
    """Class exists today as a placeholder. Real implementation arrives with the spec."""
    from app.services.bridge.payments.maverick import MaverickPaymentAdapter

    a = MaverickPaymentAdapter()
    # Verifies the placeholder still respects PaymentAdapter contract
    from app.services.bridge.payments.base import PaymentAdapter
    assert isinstance(a, PaymentAdapter)


@pytest.mark.asyncio
async def test_maverick_adapter_create_session_raises_until_spec_implemented():
    """Until Maverick spec arrives, calling create_session raises clear NotImplementedError.
    This forces us to fail loudly if someone wires Maverick before the spec lands."""
    from app.services.bridge.payments.maverick import MaverickPaymentAdapter

    a = MaverickPaymentAdapter()
    with pytest.raises(NotImplementedError, match="spec"):
        await a.create_session(amount_cents=100, transaction_id="X", purpose="full")
