# Phase 7-A.D Wave A.3 Plan E — NATO recital → email extraction
# (NATO 음성 음철 → 이메일 추출 — 서버 권위 보정 로직)
#
# Why this exists:
#   The voice agent's NATO readback ('C as in Charlie, Y as in Yankee...')
#   is what the customer audibly verifies and confirms with 'yes'. But the
#   LLM independently generates the function-call arg `customer_email` from
#   its own internal representation. Live ops 2026-05-08 measured 10/11
#   emails landing at the wrong address (cymeet → cymet drop, cymeet →
#   cyeet M-drop, cymeet → cyeemt order-flip) because the model collapses
#   doubles and reorders letters when forming function args, even when the
#   spoken NATO recital is correct.
#
# The recital is the customer-confirmed source of truth. This module gives
# the dispatcher a way to extract that truth and override args drift before
# create_order persists.
#
# Public API:
#   extract_email_from_recital(text)      — returns email or None
#   reconcile_email_with_recital(args, t) — returns the reconciled address

from __future__ import annotations

import re
from typing import Optional


# ── NATO-letter regex ────────────────────────────────────────────────────────
# Match patterns like:
#   'C as in Charlie' / 'C like Charlie' / 'C, as in Charlie'
# The bot may use em-dash, en-dash, comma, semicolon between letters; tolerate
# all of them. Letter is captured group 1.
# (NATO 패턴: 한 글자 + 'as in'/'like' + NATO 단어)
#
# 2026-05-12 — also accept bare digits between separators ("R, 1, S, P, E, E,
# D, S at yahoo.com" → r1speds → r1speeds). The NATO discipline only applies
# to letters; numerals are spoken plainly ("the number 1") and the bot reads
# them back as a bare digit between commas. Live trigger CA5a14bbf... where
# r1speeds@yahoo.com landed as rspeeds@yahoo.com because the digit dropped.
# Capture digit in group 2 so the extractor can take either group.
# (숫자도 매칭 — NATO 외 digit 토큰 별도 capture)
_LETTER_PATTERN = re.compile(
    r"(?:\b([A-Za-z])\s*[—–-]?\s*[,;]?\s*(?:as\s+in|like)\s+[A-Za-z]+)"
    r"|(?:(?<=[\s,;:])([0-9])(?=[\s,;:.]|$))",
    re.IGNORECASE,
)

# Domain part — 'at <something>' where <something> is a domain. The bot may
# say 'at gmail.com' or the more TTS-friendly 'at gmail dot com'. We capture
# the longest run of letters/digits/dots/spaces (for the 'dot' alias) ending
# in an alphanumeric — so 'at gmail.com' grabs the whole 'gmail.com' and
# 'at gmail dot com' grabs 'gmail dot com' which _normalize_domain rewrites.
# Trailing sentence punctuation (em-dash / period / comma) is excluded.
# (도메인 패턴: 'at <domain>' — greedy까지 + 후처리로 'dot' 변환)
_AT_DOMAIN_PATTERN = re.compile(
    r"\bat\s+([A-Za-z0-9](?:[A-Za-z0-9.\s-]*[A-Za-z0-9])?)",
    re.IGNORECASE,
)


def _normalize_domain(raw: str) -> str:
    """Convert spoken-form ('gmail dot com') into written-form ('gmail.com').
    Strips inner whitespace, replaces ' dot ' with '.'.
    (구어체 'dot' → '.'  /  공백 제거)
    """
    s = raw.strip().lower()
    # Replace ' dot ' (with surrounding spaces) before any internal-whitespace cleanup
    s = re.sub(r"\s+dot\s+", ".", s)
    # If the model wrote 'dot' adjacent to letters somehow, also handle
    s = re.sub(r"\bdot\b", ".", s)
    # Collapse any remaining whitespace
    s = re.sub(r"\s+", "", s)
    # Tidy double dots that can arise from punctuation noise
    s = re.sub(r"\.+", ".", s)
    return s.strip(".")


def extract_email_from_recital(text: Optional[str]) -> Optional[str]:
    """Parse `text` for the LAST 'X as in NAME, Y as in NAME, ... at DOMAIN'
    sequence and return 'xy@domain' (lowercased). Returns None if no NATO
    pattern is present, no domain follows, or the recital is otherwise
    incomplete.
    (text의 마지막 NATO recital → 'letters@domain' 형태로 반환)

    The LAST sequence wins because models occasionally read back, get
    corrected, and read back again — only the corrected (final) form is
    customer-confirmed.
    """
    if not text:
        return None

    # Find the LAST 'at <domain>' anchor in the text. We search from this
    # backwards to grab the NATO letters that immediately precede it,
    # ignoring any earlier (corrected-away) recital blocks.
    # (마지막 'at DOMAIN' 기준으로 직전 NATO 블록 채택)
    at_matches = list(_AT_DOMAIN_PATTERN.finditer(text))
    if not at_matches:
        return None
    last_at = at_matches[-1]
    domain_raw = last_at.group(1)
    domain = _normalize_domain(domain_raw)
    if not domain or "." not in domain:
        # 'at gmail' alone is not a usable domain.
        return None

    # Walk backwards through letter-pattern matches that end before the
    # 'at ' anchor. Keep the contiguous trailing run — once we hit a gap
    # (i.e. earlier recital block separated by 'at <something>'), stop.
    # (마지막 at 직전의 연속 letter 시퀀스만 채택)
    cutoff = last_at.start()
    letter_matches = [m for m in _LETTER_PATTERN.finditer(text) if m.end() <= cutoff]
    if not letter_matches:
        return None

    # Find the largest contiguous trailing block. We treat letter matches
    # as belonging to one block if no 'at <domain>' falls between them.
    # (이전 'at' 경계로 블록 분리 — 마지막 블록만 사용)
    prev_at_ends = [m.end() for m in at_matches[:-1]]
    last_block_start = max(
        (e for e in prev_at_ends if e <= cutoff),
        default=0,
    )
    block = [m for m in letter_matches if m.start() >= last_block_start]
    if not block:
        return None

    # Each match yields either a NATO letter (group 1) or a bare digit (group 2);
    # take whichever the OR branch populated. (둘 중 매칭된 캡처를 사용)
    letters = "".join(((m.group(1) or m.group(2) or "")).lower() for m in block)
    return f"{letters}@{domain}"


def reconcile_email_with_recital(
    *,
    args_email:          Optional[str],
    last_assistant_text: Optional[str],
) -> Optional[str]:
    """If the bot's last response contained a NATO recital, return the
    address parsed from THAT recital — otherwise return args_email
    untouched. The recital is the customer-confirmed source of truth.
    (recital 기반 권위 — 추출 가능 시 args를 NATO 결과로 override)

    Behaviour matrix:
        recital_email | args_email | result
        --------------|------------|---------------------
        present       | any        | recital_email
        None          | any        | args_email (verbatim)
    """
    recital_email = extract_email_from_recital(last_assistant_text)
    if recital_email:
        return recital_email
    return args_email
