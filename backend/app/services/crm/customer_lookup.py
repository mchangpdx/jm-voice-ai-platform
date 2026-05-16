# CRM — phone-keyed customer lookup against bridge_transactions
# (CRM — bridge_transactions를 전화번호로 조회하여 재방문 고객 컨텍스트 생성)
#
# Wave 1 scope. Reads only — never mutates a transaction. The lookup runs
# once per call at WebSocket accept (T1 in the design), with a hard 500ms
# timeout so a slow Supabase doesn't block the first agent turn. All
# failure modes return None and let the call proceed as first-time —
# CRM is enrichment, not gating. PII (phone, email) is redacted in every
# log line per the project privacy rules (Cat 6.2 of the design spec).
#
# Reference: docs/superpowers/specs/2026-05-08-crm-wave-1-design.md

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import anyio
import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# State filter for the 5 transactions we hand to the LLM as "recent orders".
# Excludes canceled / no_show — feeding a cancelled order back as part of a
# usual-eligibility check produces awkward suggestions like
# "would you like the latte you didn't pick up last time?"
#
# 2026-05-12 — added "fulfilled". The mock_payment_callback flow transitions
# `paid → fulfilled` immediately after settle (kitchen has the order). Without
# "fulfilled" here, the CRM lookup returned visit_count=0 on returning callers
# whose previous orders had already moved past the bare PAID state. Live trigger:
# JM Pizza pilot tx 13068a40 / 12f1af0e — both fulfilled, neither surfaced as
# a recent order for the same caller phone. "settled" is the legacy SaaS state
# name retained for backward compatibility with stores still on the older
# flow. (CRM filter — fulfilled 추가, settled는 legacy 호환용 유지)
_PAID_STATES = ("paid", "fulfilled", "settled", "fired_unpaid")

# State filter for the visit_count tally. Includes canceled + no_show because
# any prior interaction (even abandoned) counts toward "is this a returning
# caller?" — they have spoken to this store before, so a "welcome back" is
# still natural. Used for the returning flag, never for usual-eligibility.
_VISIT_STATES = _PAID_STATES + ("canceled", "no_show")

_PAID_STATES_CSV  = ",".join(_PAID_STATES)
_VISIT_STATES_CSV = ",".join(_VISIT_STATES)

_LOOKUP_TIMEOUT_S = 0.5
_RECENT_LIMIT     = 5

# E.164 — leading +, country digit 1-9, then 6-14 more digits. Anonymous /
# blocked-CID callers arrive as None, "Private", "anonymous", etc. — anything
# that doesn't match this gets the first-time path.
_E164_RE = re.compile(r"^\+[1-9][0-9]{6,14}$")

_SUPABASE_HEADERS = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type":  "application/json",
}
_REST = f"{settings.supabase_url}/rest/v1"

# Columns we read into the recent-orders block. Explicit select keeps the
# payload tight and stable against future bridge_transactions schema growth.
_RECENT_SELECT = (
    "id,created_at,state,total_cents,items_json,customer_name,customer_email"
)


# ── Public types ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CustomerContext:
    """Snapshot of what we know about a returning caller at call start.
    (통화 시작 시점의 재방문 고객 스냅샷 — 통화 동안 불변)
    """
    visit_count:    int                       # all 5 visit-states, store-scoped
    recent:         list[dict[str, Any]]      # ≤5 paid/settled/fired_unpaid
    usual_eligible: bool                      # last 2 paid orders item_id-equal
    name:           Optional[str]             # from recent[0].customer_name
    email:          Optional[str]             # from recent[0].customer_email


# ── Public API ────────────────────────────────────────────────────────────────

async def customer_lookup(
    store_id:          str,
    caller_phone_e164: Optional[str],
) -> Optional[CustomerContext]:
    """Resolve a caller into a CustomerContext, or None for first-time / fail.

    (발신 번호로 고객 컨텍스트 조회 — 신규/실패 시 None 반환)

    Returns None for any of: anonymous caller, lookup timeout, Supabase 5xx,
    auth/RLS error, or zero rows. Callers must treat None as "proceed as
    first-time" — do NOT raise. Hard timeout = 500ms; the lookup is on the
    voice critical path before the first agent turn.
    """
    # F1: anonymous caller — phone missing or not E.164 shape
    if not caller_phone_e164 or not _E164_RE.match(caller_phone_e164):
        log.info("[crm] anonymous_caller skip_lookup store_id=%s", store_id)
        return None

    redacted = redact_phone(caller_phone_e164)

    try:
        async with httpx.AsyncClient(timeout=_LOOKUP_TIMEOUT_S + 0.1) as client:
            with anyio.move_on_after(_LOOKUP_TIMEOUT_S) as scope:
                recent, count = await asyncio.gather(
                    _fetch_recent(client, store_id, caller_phone_e164),
                    _fetch_visit_count(client, store_id, caller_phone_e164),
                )
            if scope.cancel_called:
                log.warning(
                    "[crm] lookup_timeout phone=%s store=%s timeout_ms=%d",
                    redacted, store_id, int(_LOOKUP_TIMEOUT_S * 1000),
                )
                return None
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        if 400 <= status < 500:
            log.error(
                "[crm] lookup_auth_error phone=%s store=%s status=%d",
                redacted, store_id, status,
            )
        else:
            log.warning(
                "[crm] lookup_failed graceful_degrade phone=%s store=%s status=%d",
                redacted, store_id, status,
            )
        return None
    except (httpx.HTTPError, asyncio.CancelledError) as e:
        log.warning(
            "[crm] lookup_failed graceful_degrade phone=%s store=%s err=%s",
            redacted, store_id, type(e).__name__,
        )
        return None
    except Exception:
        # Defensive — never let a CRM bug crash the voice loop
        log.exception("[crm] lookup_unexpected_error phone=%s store=%s",
                      redacted, store_id)
        return None

    # F5: zero rows = first-time caller. Returned as a positive signal so the
    # caller can log it and short-circuit the prompt block (visit_count=0
    # triggers the "no block" path in build_system_prompt).
    if count == 0:
        log.info("[crm] first_time_caller phone=%s store=%s", redacted, store_id)
        return CustomerContext(
            visit_count=0, recent=[], usual_eligible=False,
            name=None, email=None,
        )

    # Guard: two empty item lists would compare equal but offering "the
    # usual: <nothing>" is nonsense. Require a non-empty multiset on the
    # newest order before considering usual-eligibility.
    usual_eligible = (
        len(recent) >= 2
        and bool(_item_multiset(recent[0].get("items_json")))
        and _items_match(recent[0], recent[1])
    )

    name  = recent[0].get("customer_name")  if recent else None
    email = recent[0].get("customer_email") if recent else None

    log.info(
        "[crm] lookup_hit phone=%s store=%s visits=%d recent=%d usual=%s",
        redacted, store_id, count, len(recent), usual_eligible,
    )

    return CustomerContext(
        visit_count    = count,
        recent         = recent,
        usual_eligible = usual_eligible,
        name           = name,
        email          = email,
    )


# ── PII redaction (Cat 6.2) ───────────────────────────────────────────────────

def redact_phone(phone: Optional[str]) -> str:
    """+15035551234 → +1503***1234. Anything malformed → '***'.
    (전화번호 마스킹 — 앞 5자 + *** + 뒤 4자)
    """
    if not phone:
        return "***"
    if len(phone) < 9:
        return "***"
    return f"{phone[:5]}***{phone[-4:]}"


def redact_email(email: Optional[str]) -> str:
    """jamie@example.com → j***@example.com. Malformed → '***'.
    (이메일 마스킹 — 첫 글자 + *** + 도메인)
    """
    if not email or "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    if not local:
        return "***"
    return f"{local[0]}***@{domain}"


# ── Internal: Supabase fetchers ───────────────────────────────────────────────

async def _fetch_recent(
    client:   httpx.AsyncClient,
    store_id: str,
    phone:    str,
) -> list[dict[str, Any]]:
    """GET ≤5 most recent paid/settled/fired_unpaid txs for (store, phone).

    store_id is in the filter explicitly — RLS policy is the primary defense
    but we double-belt with a query filter (Cat 6.1 of the spec).
    """
    resp = await client.get(
        f"{_REST}/bridge_transactions",
        headers=_SUPABASE_HEADERS,
        params={
            "store_id":       f"eq.{store_id}",
            "customer_phone": f"eq.{phone}",
            "state":          f"in.({_PAID_STATES_CSV})",
            "select":         _RECENT_SELECT,
            "order":          "created_at.desc",
            "limit":          str(_RECENT_LIMIT),
        },
    )
    resp.raise_for_status()
    return resp.json() or []


async def _fetch_visit_count(
    client:   httpx.AsyncClient,
    store_id: str,
    phone:    str,
) -> int:
    """Exact count of all visit-state txs for (store, phone) via PostgREST
    Content-Range header. We send limit=1 + select=id to keep the payload
    small — only the count header matters.
    (visit_count는 Content-Range 헤더로 정확 집계 — 페이로드는 최소화)
    """
    resp = await client.get(
        f"{_REST}/bridge_transactions",
        headers={**_SUPABASE_HEADERS, "Prefer": "count=exact"},
        params={
            "store_id":       f"eq.{store_id}",
            "customer_phone": f"eq.{phone}",
            "state":          f"in.({_VISIT_STATES_CSV})",
            "select":         "id",
            "limit":          "1",
        },
    )
    resp.raise_for_status()
    # Content-Range looks like "0-0/47" — count is after the slash.
    cr = resp.headers.get("Content-Range") or resp.headers.get("content-range")
    if not cr or "/" not in cr:
        return len(resp.json() or [])
    try:
        total = cr.rsplit("/", 1)[-1]
        return int(total) if total != "*" else 0
    except (ValueError, IndexError):
        return 0


# ── Internal: usual-eligibility ───────────────────────────────────────────────

def _items_match(tx_a: dict[str, Any], tx_b: dict[str, Any]) -> bool:
    """True iff the item_id multiset of two transactions is identical.

    Wave 1 simplification: size and modifiers are not part of the comparison.
    Two orders with the same items but different sizes (small vs large) match.
    Reasoning: many POS catalogs encode size as a modifier under one item_id,
    and Pilot prefers safe/coarse matching to clever/fragile. Modifier-aware
    matching ships with the modifier-accuracy sprint (Wave 2).

    (Wave 1: item_id 멀티셋이 일치하면 True. 사이즈/모디파이어 미고려)
    """
    return _item_multiset(tx_a.get("items_json")) == \
           _item_multiset(tx_b.get("items_json"))


def _item_multiset(items: Optional[list[dict[str, Any]]]) -> tuple[str, ...]:
    """Stable multiset key — sorted tuple of item_id repeated by quantity.
    (수량을 풀어 사전순으로 정렬한 item_id 튜플 — 멀티셋 동등성 비교용)
    """
    if not items:
        return ()
    keys: list[str] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        k = it.get("item_id") or it.get("variant_id")
        if k is None:
            continue
        try:
            qty = int(it.get("quantity") or 1)
        except (TypeError, ValueError):
            qty = 1
        if qty < 1:
            qty = 1
        for _ in range(qty):
            keys.append(str(k))
    return tuple(sorted(keys))


# ── G6 fix (2026-05-10) — mid-call email update DB persistence ────────────────
#
# Live trigger CA7748f354... 2026-05-10 Jason call: caller did a NATO recital
# of a corrected email AFTER his only create_order had fired (then canceled),
# then hung up without a follow-up tool call. The new email never landed in
# bridge_transactions, so the next customer_lookup for this phone still
# returns the stale address. Fix: at call_end, PATCH the most recent
# bridge_transactions row for (store_id, phone) with the verified email so
# subsequent calls pick it up via _fetch_recent above.
#
# Additive — never mutates state machine, never blocks the voice path
# (caller is exiting). Returns True on a row patched, False on no-match /
# already-current / failure. Safe to fire-and-forget.

async def update_recent_customer_email(
    store_id: str,
    caller_phone_e164: Optional[str],
    new_email: Optional[str],
) -> bool:
    """PATCH customer_email on the most recent bridge_transactions row for
    (store, phone) if it differs from new_email.
    (가장 최근 tx의 customer_email을 PATCH — 신규 함수, 기존 함수 시그니처 변경 X)

    Guards:
    - anonymous caller (no/invalid phone) → no-op
    - empty/None email → no-op
    - no rows for (store, phone) → no-op
    - already matches → no-op
    """
    if not caller_phone_e164 or not _E164_RE.match(caller_phone_e164):
        return False
    if not new_email or "@" not in new_email:
        return False

    redacted_phone = redact_phone(caller_phone_e164)
    redacted_email = redact_email(new_email)

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            # Find the most recent row for (store, phone). Includes canceled /
            # no_show — we want the latest interaction's row, regardless of
            # final state. The email column is just contact metadata.
            # (최신 row 1건만 — state 무관)
            resp = await client.get(
                f"{_REST}/bridge_transactions",
                headers=_SUPABASE_HEADERS,
                params={
                    "store_id":       f"eq.{store_id}",
                    "customer_phone": f"eq.{caller_phone_e164}",
                    "select":         "id,customer_email",
                    "order":          "created_at.desc",
                    "limit":          "1",
                },
            )
            resp.raise_for_status()
            rows = resp.json() or []
            if not rows:
                log.info(
                    "[crm] email_update no_recent_tx phone=%s store=%s",
                    redacted_phone, store_id,
                )
                return False

            row = rows[0]
            current = (row.get("customer_email") or "").strip().lower()
            target  = new_email.strip().lower()
            if current == target:
                log.info(
                    "[crm] email_update already_current phone=%s store=%s email=%s",
                    redacted_phone, store_id, redacted_email,
                )
                return False

            patch = await client.patch(
                f"{_REST}/bridge_transactions",
                headers=_SUPABASE_HEADERS,
                params={"id": f"eq.{row['id']}"},
                json={"customer_email": new_email.strip()},
            )
            patch.raise_for_status()
            log.info(
                "[crm] email_update ok phone=%s store=%s tx=%s email=%s",
                redacted_phone, store_id, row["id"], redacted_email,
            )
            return True
    except httpx.HTTPStatusError as e:
        log.warning(
            "[crm] email_update http_error phone=%s store=%s status=%d",
            redacted_phone, store_id, e.response.status_code,
        )
        return False
    except Exception:
        log.exception(
            "[crm] email_update unexpected phone=%s store=%s",
            redacted_phone, store_id,
        )
        return False
