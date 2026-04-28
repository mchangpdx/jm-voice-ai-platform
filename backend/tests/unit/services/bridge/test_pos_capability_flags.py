# POS Adapter — capability flags TDD
# (POS 어댑터 — capability 플래그 TDD)
#
# Phase 2-B.1.5 goal: prove the adapter pattern works for a SECOND POS (Loyverse).
# A 2nd adapter exposes interface gaps that a 1st adapter never reveals.
#
# This file locks the capability flags pattern at the base class level. Each
# concrete adapter overrides only the flags it actually supports. Orchestration
# code (flows.py, vertical adapters) reads flags before calling optional methods.
#
# Capabilities chosen for v1.5 (most likely to differ across POS):
#   - SUPPORTS_MENU_SYNC      — adapter exposes a menu-fetch method (Loyverse: yes, Supabase: no)
#   - SUPPORTS_INVENTORY      — adapter tracks live stock_quantity per item
#   - SUPPORTS_PAYMENT_SYNC   — adapter receives paid/refund updates from POS

import pytest


def test_base_pos_adapter_declares_capability_flags():
    from app.services.bridge.pos.base import POSAdapter
    assert hasattr(POSAdapter, "SUPPORTS_MENU_SYNC"),    "base must declare SUPPORTS_MENU_SYNC"
    assert hasattr(POSAdapter, "SUPPORTS_INVENTORY"),    "base must declare SUPPORTS_INVENTORY"
    assert hasattr(POSAdapter, "SUPPORTS_PAYMENT_SYNC"), "base must declare SUPPORTS_PAYMENT_SYNC"


def test_base_capabilities_default_to_false():
    """Base class is conservative — every concrete adapter explicitly opts in."""
    from app.services.bridge.pos.base import POSAdapter
    assert POSAdapter.SUPPORTS_MENU_SYNC      is False
    assert POSAdapter.SUPPORTS_INVENTORY      is False
    assert POSAdapter.SUPPORTS_PAYMENT_SYNC   is False


def test_supabase_pos_capability_profile():
    """Supabase POS uses our own tables — no menu sync (we don't have one), no real
    inventory tracking. Mostly a "system of record" not a feature-rich POS."""
    from app.services.bridge.pos.supabase import SupabasePOSAdapter
    assert SupabasePOSAdapter.SUPPORTS_MENU_SYNC    is False
    assert SupabasePOSAdapter.SUPPORTS_INVENTORY    is False
    assert SupabasePOSAdapter.SUPPORTS_PAYMENT_SYNC is False


def test_loyverse_pos_capability_profile():
    """Loyverse exposes /items + /categories + /inventory endpoints — full feature set."""
    from app.services.bridge.pos.loyverse import LoyversePOSAdapter
    assert LoyversePOSAdapter.SUPPORTS_MENU_SYNC    is True
    assert LoyversePOSAdapter.SUPPORTS_INVENTORY    is True
    assert LoyversePOSAdapter.SUPPORTS_PAYMENT_SYNC is True
