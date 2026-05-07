# Phase 7-A — Sync freeze unit tests (F1–F7)
# (Phase 7-A — 동기화 freeze 단위 테스트)

import time
from unittest.mock import patch

import pytest

from app.services.sync import freeze


@pytest.fixture(autouse=True)
def _reset_state():
    """Each test starts with an empty freeze state."""
    freeze._frozen_until.clear()
    yield
    freeze._frozen_until.clear()


# ── F1: default not frozen ────────────────────────────────────────────────────

def test_f1_default_not_frozen():
    assert freeze.is_globally_frozen() is False
    assert freeze.is_frozen("any-store") is False
    assert freeze.is_blocked("any-store") is False


# ── F2: freeze_all then is_globally_frozen ────────────────────────────────────

def test_f2_freeze_all_blocks_global():
    freeze.freeze_all(duration_min=10)
    assert freeze.is_globally_frozen() is True
    assert freeze.is_blocked("store-A") is True
    assert freeze.is_blocked("store-B") is True


# ── F3: freeze_store blocks one store only ───────────────────────────────────

def test_f3_freeze_store_isolates():
    freeze.freeze_store("store-A", duration_min=10)
    assert freeze.is_globally_frozen() is False
    assert freeze.is_blocked("store-A") is True
    assert freeze.is_blocked("store-B") is False


# ── F4: unfreeze clears state ────────────────────────────────────────────────

def test_f4_unfreeze_clears():
    freeze.freeze_all(10)
    assert freeze.unfreeze_store("*") is True
    assert freeze.is_globally_frozen() is False

    freeze.freeze_store("store-A", 10)
    assert freeze.unfreeze_store("store-A") is True
    assert freeze.is_blocked("store-A") is False
    # Already unfrozen — second call returns False
    assert freeze.unfreeze_store("store-A") is False


# ── F5: auto-expiry on read ──────────────────────────────────────────────────

def test_f5_auto_expire_on_read():
    # Manually plant an already-expired entry.
    freeze._frozen_until["store-A"] = time.time() - 1.0
    assert freeze.is_frozen("store-A") is False
    # Lazy cleanup — entry is removed
    assert "store-A" not in freeze._frozen_until


# ── F6: status snapshot ───────────────────────────────────────────────────────

def test_f6_status_snapshot():
    freeze.freeze_all(60)
    freeze.freeze_store("store-A", 30)
    s = freeze.status()
    assert s["global_frozen"] is True
    assert "*" in s["active"]
    assert "store-A" in s["active"]
    assert s["active"]["*"]["remaining_seconds"] > 0


# ── F7: status drops expired entries ─────────────────────────────────────────

def test_f7_status_drops_expired():
    freeze.freeze_all(10)
    freeze._frozen_until["expired-store"] = time.time() - 60.0  # already expired
    s = freeze.status()
    assert "expired-store" not in s["active"]
    assert "expired-store" not in freeze._frozen_until
