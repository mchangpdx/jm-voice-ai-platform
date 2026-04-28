# Bridge Server — POS Adapter base interface
# (Bridge Server — POS 어댑터 베이스 인터페이스)
#
# Concrete adapters today: SupabasePOSAdapter (uses our own reservations/jobs/etc tables)
# Concrete adapters future: QuanticPOSAdapter (white-label deal pending)
#
# Both implement this protocol. vertical_adapter / bridge.create_reservation()
# call only this interface — they never know which adapter is wired underneath.
# Switching to Quantic = swap the adapter instance, zero changes elsewhere.

from __future__ import annotations

from typing import Any, Optional


class POSAdapter:
    """Abstract POS adapter interface. All methods must be overridden.
    (POS 어댑터 추상 인터페이스 — 모든 메서드 override 필수)
    """

    # ── Capability flags (Phase 2-B.1.5) ────────────────────────────────────
    # Concrete adapters override only the flags they actually support. Orchestration
    # code (flows.py, vertical adapters) reads these BEFORE calling optional methods
    # so a missing capability fails gracefully instead of with NotImplementedError.
    # (어댑터별로 지원 여부 명시 — 호출 전 flag 확인하여 우아한 fallback 보장)
    SUPPORTS_MENU_SYNC:    bool = False
    SUPPORTS_INVENTORY:    bool = False
    SUPPORTS_PAYMENT_SYNC: bool = False

    async def create_pending(
        self,
        *,
        vertical: str,
        store_id: str,
        payload:  dict[str, Any],
    ) -> str:
        """INSERT a pending object (reservation/job/appointment/SO) and return its id as string.
        (대기 상태 객체 INSERT 후 id를 string으로 반환)
        """
        raise NotImplementedError

    async def mark_paid(
        self,
        *,
        vertical:  str,
        object_id: str,
        extra:     Optional[dict[str, Any]] = None,
    ) -> None:
        """Transition the POS object to its 'paid' equivalent (confirmed/scheduled/etc).
        (POS 객체를 'paid' 등가 상태로 전이 — confirmed/scheduled 등)
        """
        raise NotImplementedError

    async def get_object(
        self,
        *,
        vertical:  str,
        object_id: str,
    ) -> Optional[dict[str, Any]]:
        """Fetch object by id. Returns None if not found.
        (id로 객체 조회 — 없으면 None)
        """
        raise NotImplementedError
