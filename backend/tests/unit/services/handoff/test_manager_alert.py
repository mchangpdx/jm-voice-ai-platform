# Phase 5 #26 — Tier-3 manager alert helper tests (M1–M6)
# (Phase 5 #26 — Tier-3 매니저 알림 헬퍼 테스트)
#
# Coverage:
#   M1: env empty → no_recipients, skipped, no SMTP call
#   M2: env single recipient → one fan-out send
#   M3: env multi recipients (comma-separated) → N fan-out sends
#   M4: SMTP raises in one fan-out → other recipients still receive (gather)
#   M5: HTML/plain composition includes store/caller/keyword/excerpt
#   M6: long transcript excerpt is trimmed to safe length

from unittest.mock import AsyncMock, patch

import pytest

from app.services.handoff import manager_alert


def _ok():
    return {"sent": True}


# ── M1: no recipients → skipped, no SMTP call ────────────────────────────────

@pytest.mark.asyncio
async def test_m1_no_recipients_skips_silently():
    with patch.object(manager_alert.settings, "tier3_alert_emails", ""), \
         patch.object(manager_alert, "send_html_email", new=AsyncMock(return_value=_ok())) as smtp:
        result = await manager_alert.send_tier3_alert(
            store_name         = "JM Cafe",
            caller_phone       = "+15037079566",
            triggered_keyword  = "epipen",
            transcript_excerpt = "I have an EpiPen for nuts.",
        )
    assert result["sent"] is False
    assert result["skipped"] is True
    assert result["reason"] == "no_recipients"
    assert result["recipients"] == 0
    smtp.assert_not_called()


# ── M2: single recipient → one fan-out send ──────────────────────────────────

@pytest.mark.asyncio
async def test_m2_single_recipient_one_send():
    with patch.object(manager_alert.settings, "tier3_alert_emails", "manager@store.com"), \
         patch.object(manager_alert, "send_html_email", new=AsyncMock(return_value=_ok())) as smtp:
        result = await manager_alert.send_tier3_alert(
            store_name         = "JM Cafe",
            caller_phone       = "+15037079566",
            triggered_keyword  = "anaphylaxis",
            transcript_excerpt = "I'll go into anaphylaxis if I eat nuts.",
        )
    assert result["sent"] is True
    assert result["recipients"] == 1
    assert smtp.call_count == 1
    kwargs = smtp.call_args.kwargs
    assert kwargs["to"] == "manager@store.com"
    assert "Tier-3" in kwargs["subject"]


# ── M3: multi recipients → fan-out per recipient ─────────────────────────────

@pytest.mark.asyncio
async def test_m3_multi_recipients_fanout():
    env = "manager@store.com, 5037079566@vtext.com,owner@store.com"
    with patch.object(manager_alert.settings, "tier3_alert_emails", env), \
         patch.object(manager_alert, "send_html_email", new=AsyncMock(return_value=_ok())) as smtp:
        result = await manager_alert.send_tier3_alert(
            store_name         = "JM Cafe",
            caller_phone       = "+15037079566",
            triggered_keyword  = "celiac",
            transcript_excerpt = "I'm celiac.",
        )
    assert result["sent"] is True
    assert result["recipients"] == 3
    assert smtp.call_count == 3
    sent_to = sorted(c.kwargs["to"] for c in smtp.call_args_list)
    assert sent_to == ["5037079566@vtext.com", "manager@store.com", "owner@store.com"]


# ── M4: one fan-out raises → others still succeed ────────────────────────────

@pytest.mark.asyncio
async def test_m4_partial_failure_does_not_block_other_recipients():
    env = "good@store.com,bad@store.com"
    side = [_ok(), Exception("smtp boom")]
    with patch.object(manager_alert.settings, "tier3_alert_emails", env), \
         patch.object(manager_alert, "send_html_email",
                      new=AsyncMock(side_effect=side)) as smtp:
        result = await manager_alert.send_tier3_alert(
            store_name         = "JM Cafe",
            caller_phone       = "+15037079566",
            triggered_keyword  = "epipen",
            transcript_excerpt = "EpiPen.",
        )
    assert result["sent"] is True            # at least one succeeded
    assert result["recipients"] == 2
    # Both attempts were dispatched
    assert smtp.call_count == 2
    # Failure was normalised, not raised
    assert any("error" in r for r in result["results"])


# ── M5: composition includes the salient context ─────────────────────────────

def test_m5_html_and_text_include_context():
    html = manager_alert.compose_tier3_alert_html(
        store_name         = "JM Cafe",
        caller_phone       = "+15037079566",
        triggered_keyword  = "epipen",
        transcript_excerpt = "I carry an EpiPen for tree nuts.",
        call_sid           = "CA677d601",
        timestamp_iso      = "2026-05-06T23:00:00+00:00",
    )
    for fragment in ("JM Cafe", "+15037079566", "epipen",
                     "EpiPen for tree nuts", "CA677d601"):
        assert fragment in html

    text = manager_alert.compose_tier3_alert_text(
        store_name         = "JM Cafe",
        caller_phone       = "+15037079566",
        triggered_keyword  = "epipen",
        transcript_excerpt = "I carry an EpiPen for tree nuts.",
        call_sid           = "CA677d601",
        timestamp_iso      = "2026-05-06T23:00:00+00:00",
    )
    for fragment in ("JM Cafe", "+15037079566", "epipen", "CA677d601"):
        assert fragment in text


# ── M6: long excerpt is trimmed to safe length ───────────────────────────────

def test_m6_excerpt_trim():
    long_text = "x" * 1000
    trimmed = manager_alert._excerpt(long_text, max_chars=240)
    assert len(trimmed) <= 240
    assert trimmed.endswith("…")
    # Short text untouched
    assert manager_alert._excerpt("short", max_chars=240) == "short"
