#!/usr/bin/env python3
"""
Generate synthetic reservations from call_logs that mention reservations.
(예약 관련 call_logs에서 합성 예약 데이터 생성)

Usage:
    python scripts/gen_reservations.py --dry-run
    python scripts/gen_reservations.py
"""
import argparse
import os
import re
import random
import sys
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
STORE_ID     = "7c425fcb-91c7-4eb7-982a-591c094ba9c9"

HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=minimal",
}

CUSTOMER_NAMES = [
    "Alex Johnson", "Maria Rodriguez", "Jake Chen", "Sarah Kim",
    "Michael Brown", "Emily Davis", "Chris Wilson", "Ashley Taylor",
    "David Martinez", "Jessica Lee", "Ryan Thompson", "Amanda Garcia",
    "Tyler Anderson", "Brittany Jackson", "Brandon White", "Kayla Harris",
    "Justin Clark", "Megan Lewis", "Austin Robinson", "Nicole Walker",
    "Ethan Young", "Samantha Hall", "Nathan Allen", "Stephanie Wright",
    "Zachary Scott", "Rebecca Green", "Dylan Adams", "Lauren Baker",
]

PORTLAND_CODES = ["+15031", "+15032", "+15034", "+15036", "+15038",
                  "+19712", "+19713", "+19715", "+19718"]


def parse_party_size(summary: str) -> int:
    """Extract party size from call summary text. (통화 요약에서 예약 인원 추출)"""
    patterns = [
        r'party of (\d+)',
        r'for (\d+) guests?',
        r'table for (\d+)',
        r'(\d+) guests?',
        r'for (\d+) people',
        r'(\d+) people',
        r'for (\d+) at',
        r'reservation for (\d+)',
        r'seats? for (\d+)',
    ]
    for pat in patterns:
        m = re.search(pat, summary, re.IGNORECASE)
        if m:
            size = int(m.group(1))
            if 1 <= size <= 20:
                return size
    return random.randint(2, 6)  # default if not parseable


def parse_reservation_hour(summary: str) -> int | None:
    """Extract hour (24h) from time mention in summary. (요약에서 예약 시간 추출)"""
    # Patterns like "7:30 PM", "6 PM", "11 AM", "8:00 PM"
    m = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(AM|PM)', summary, re.IGNORECASE)
    if not m:
        return None
    hour = int(m.group(1))
    am_pm = m.group(3).upper()
    if am_pm == 'PM' and hour != 12:
        hour += 12
    elif am_pm == 'AM' and hour == 12:
        hour = 0
    if 10 <= hour <= 22:
        return hour
    return None


def fetch_reservation_calls(client: httpx.Client) -> list[dict]:
    """Fetch all call_logs with 'reservation' in summary. (예약 관련 통화 내역 조회)"""
    all_logs = []
    offset = 0
    while True:
        resp = client.get(
            f"{SUPABASE_URL}/rest/v1/call_logs",
            headers=HEADERS,
            params={
                "store_id":    f"eq.{STORE_ID}",
                "summary":     "ilike.*reservation*",
                "call_status": "eq.Successful",
                "select":      "call_id,start_time,customer_phone,summary",
                "order":       "start_time.asc",
                "limit":       "1000",
                "offset":      str(offset),
            },
        )
        batch = resp.json() if isinstance(resp.json(), list) else []
        all_logs.extend(batch)
        if len(batch) < 1000:
            break
        offset += 1000
    return all_logs


def build_reservations(call_logs: list[dict], rng: random.Random) -> list[dict]:
    """Convert call_log records into reservation rows. (call_log → 예약 레코드 변환)"""
    rows = []
    for log in call_logs:
        summary  = log.get("summary", "")
        call_id  = log["call_id"]
        phone    = log.get("customer_phone") or (
            rng.choice(PORTLAND_CODES) + "".join(str(rng.randint(0, 9)) for _ in range(6))
        )

        party_size = parse_party_size(summary)
        res_hour   = parse_reservation_hour(summary) or rng.choice([11, 12, 13, 18, 19, 20])
        res_minute = rng.choice([0, 0, 0, 15, 30, 30, 45])

        # Parse call start_time, then set reservation 1–10 days forward
        try:
            call_dt  = datetime.fromisoformat(log["start_time"].replace("Z", "+00:00"))
        except Exception:
            call_dt  = datetime.now(timezone.utc)
        days_ahead   = rng.randint(0, 10)
        res_date     = call_dt + timedelta(days=days_ahead)
        res_dt       = res_date.replace(hour=res_hour, minute=res_minute, second=0, microsecond=0)

        # Status distribution: confirmed 45%, pending 25%, seated 20%, cancelled 10%
        status = rng.choices(
            ["confirmed", "pending", "seated", "cancelled"],
            weights=[45, 25, 20, 10],
        )[0]

        rows.append({
            "store_id":         STORE_ID,
            "call_log_id":      call_id,
            "customer_name":    rng.choice(CUSTOMER_NAMES),
            "customer_phone":   phone,
            "party_size":       party_size,
            "reservation_time": res_dt.isoformat(),
            "status":           status,
            "notes":            summary[:200] if len(summary) > 20 else None,
        })
    return rows


def batch_insert(client: httpx.Client, rows: list[dict], batch: int = 100) -> None:
    """Insert reservations in batches. (배치 삽입)"""
    for i in range(0, len(rows), batch):
        chunk = rows[i : i + batch]
        resp  = client.post(
            f"{SUPABASE_URL}/rest/v1/reservations",
            headers=HEADERS,
            json=chunk,
        )
        if resp.status_code in (200, 201):
            print(f"  ✅ reservations[{i}:{i+len(chunk)}]  {len(chunk)}건")
        else:
            print(f"  ❌ 실패: {resp.status_code} {resp.text[:300]}")
            sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic reservation data")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--seed",    type=int, default=77)
    args = parser.parse_args()

    rng = random.Random(args.seed)

    with httpx.Client(timeout=30) as client:
        print("🔍 예약 관련 call_logs 조회 중...")
        call_logs = fetch_reservation_calls(client)
        print(f"  → {len(call_logs)}건 발견")

        rows = build_reservations(call_logs, rng)

        # Summary preview
        statuses = {}
        for r in rows:
            statuses[r["status"]] = statuses.get(r["status"], 0) + 1
        total_covers = sum(r["party_size"] for r in rows)
        print(f"\n  총 {len(rows)}건 예약 생성 예정")
        print(f"  상태: {statuses}")
        print(f"  총 커버(인원): {total_covers}명")
        print(f"  파티 사이즈 평균: {total_covers/len(rows):.1f}명")

        if args.dry_run:
            print("\n✅ Dry-run 완료 (DB 변경 없음)")
            return

        print(f"\n📅 reservations {len(rows)}건 삽입 중...")
        batch_insert(client, rows)

    print(f"\n🎉 완료!")


if __name__ == "__main__":
    main()
