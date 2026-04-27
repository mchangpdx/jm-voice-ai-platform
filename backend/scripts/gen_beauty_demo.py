#!/usr/bin/env python3
"""Generate synthetic 60-day call_logs + appointments for JM Beauty Salon demo.
(JM Beauty Salon 60일치 합성 데이터 생성 — 뷰티 살롱 데모 시나리오)

# STORE_ID below is a placeholder — replace with actual JM Beauty Salon store_id after DB migration
# Run: INSERT INTO stores (...) VALUES ('JM Beauty Salon', ...) then: SELECT id FROM stores WHERE name='JM Beauty Salon'

Usage:
    python scripts/gen_beauty_demo.py --dry-run   # preview KPIs, no DB writes
    python scripts/gen_beauty_demo.py              # insert into Supabase

Target KPIs (period=60 days, seed=55):
  call_logs:    200 records
  busy_rate:    75% (is_store_busy=True)
  success_rate: 65% (call_status='Successful')
  appointments: 120 records, ~50% linked to call_logs
  avg_price:    ~$95  (range $35–$200)
"""
import argparse
import os
import random
import sys
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# STORE_ID below is a placeholder — replace with actual JM Beauty Salon store_id after DB migration
# Run: INSERT INTO stores (...) VALUES ('JM Beauty Salon', ...) then: SELECT id FROM stores WHERE name='JM Beauty Salon'
STORE_ID = "34f44792-b200-450e-aeed-cbaaa1c7ff6e"  # JM Beauty Salon

HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=minimal",
}

SEED = 55
DAYS = 60

# Date window: last 60 days ending today (2026-04-26)
END   = datetime(2026, 4, 26, 23, 59, 59, tzinfo=timezone.utc)
START = END - timedelta(days=DAYS)

TOTAL_CALLS  = 200
SUCCESS_RATE = 0.65   # 65% Successful → ~130 calls
BUSY_RATE    = 0.75   # 75% is_store_busy=True → ~150 calls

TOTAL_APPOINTMENTS  = 120
LINK_RATE           = 0.50   # ~50% of appointments linked to a call_log

# Service type distribution (뷰티 서비스 종류 및 비율)
SERVICE_TYPES   = ["haircut", "color", "manicure", "pedicure", "gel"]
SERVICE_WEIGHTS = [0.30, 0.25, 0.20, 0.15, 0.10]

# Price ranges per service type (서비스별 가격 범위)
PRICE_RANGES = {
    "haircut":  (35,  65),
    "color":    (80, 200),
    "manicure": (35,  55),
    "pedicure": (40,  65),
    "gel":      (45,  80),
}

# Duration ranges in minutes per service type (서비스별 소요 시간 범위)
DURATION_RANGES = {
    "haircut":  (30,  60),
    "color":    (90, 180),
    "manicure": (45,  60),
    "pedicure": (45,  75),
    "gel":      (60,  90),
}

# Appointment status distribution (예약 상태 분포)
APPT_STATUSES  = ["completed", "booked", "no_show", "cancelled"]
APPT_WEIGHTS   = [0.60, 0.25, 0.10, 0.05]

CALL_STATUSES = ["Successful", "Unsuccessful", "Voicemail"]
SENTIMENTS    = ["Positive", "Neutral", "Negative"]

# Sample first names for customer_name generation (고객 이름 샘플)
FIRST_NAMES = [
    "Emma", "Olivia", "Ava", "Sophia", "Isabella",
    "Mia", "Charlotte", "Amelia", "Harper", "Evelyn",
    "Abigail", "Emily", "Elizabeth", "Mila", "Ella",
    "Avery", "Sofia", "Camila", "Aria", "Scarlett",
    "Victoria", "Madison", "Luna", "Grace", "Chloe",
    "Penelope", "Layla", "Riley", "Zoey", "Nora",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones",
    "Garcia", "Miller", "Davis", "Martinez", "Hernandez",
    "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas",
    "Taylor", "Moore", "Jackson", "Martin", "Lee",
]


def rand_time(rng: random.Random) -> datetime:
    """Return a random timestamp within the 60-day window. (60일 윈도우 내 임의 타임스탬프 반환)"""
    delta = END - START
    return START + timedelta(seconds=rng.randint(0, int(delta.total_seconds())))


def build_call_logs(rng: random.Random) -> list[dict]:
    """Generate 200 call_log rows. (200건 call_log 생성)"""
    records = []
    for i in range(TOTAL_CALLS):
        is_successful = rng.random() < SUCCESS_RATE
        is_busy       = rng.random() < BUSY_RATE
        if is_successful:
            status   = "Successful"
            duration = rng.randint(60, 600)
        else:
            status   = rng.choices(["Unsuccessful", "Voicemail"], weights=[0.6, 0.4])[0]
            duration = rng.randint(10, 90)
        start = rand_time(rng)
        records.append({
            "call_id":        f"beauty-{SEED}-{i:04d}",
            "store_id":       STORE_ID,
            "call_status":    status,
            "duration":       duration,
            "is_store_busy":  is_busy,
            "sentiment":      rng.choice(SENTIMENTS),
            "start_time":     start.isoformat(),
            "customer_phone": f"+1503{rng.randint(1000000, 9999999)}",
            "cost":           round(duration / 60 * 0.08, 4),
        })
    return records


def build_appointments(call_logs: list[dict], rng: random.Random) -> list[dict]:
    """Generate 120 appointment rows, ~50% linked to a call_log.
    (120건 예약 생성, 약 50%는 call_log에 연결)
    Prefer linking to busy calls (is_store_busy=True). (바쁜 통화 우선 연결)
    """
    # Separate call IDs into busy vs non-busy for preferential linking
    # (바쁜 통화와 그렇지 않은 통화를 분리하여 우선순위 부여)
    busy_call_ids   = [c["call_id"] for c in call_logs if c["is_store_busy"]]
    other_call_ids  = [c["call_id"] for c in call_logs if not c["is_store_busy"]]

    # Pool to draw from: busy first, then non-busy (바쁜 통화 우선, 나머지 추가)
    link_pool = busy_call_ids + other_call_ids

    appointments = []
    for i in range(TOTAL_APPOINTMENTS):
        service_type = rng.choices(SERVICE_TYPES, weights=SERVICE_WEIGHTS)[0]
        price_lo, price_hi  = PRICE_RANGES[service_type]
        dur_lo,   dur_hi    = DURATION_RANGES[service_type]

        price        = round(rng.uniform(price_lo, price_hi), 2)
        duration_min = rng.randint(dur_lo, dur_hi)
        status       = rng.choices(APPT_STATUSES, weights=APPT_WEIGHTS)[0]
        scheduled_at = rand_time(rng)

        # ~50% chance to link to a call_log (약 50% 확률로 call_log 연결)
        call_log_id = None
        if link_pool and rng.random() < LINK_RATE:
            # Draw preferentially from the front (busy calls) (바쁜 통화 우선 선택)
            idx         = rng.randint(0, min(len(busy_call_ids) - 1, len(link_pool) - 1)) if busy_call_ids else rng.randint(0, len(link_pool) - 1)
            call_log_id = link_pool[idx]

        customer_name  = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        customer_phone = f"+1503{rng.randint(1000000, 9999999)}"

        row = {
            "store_id":       STORE_ID,
            "call_log_id":    call_log_id,
            "service_type":   service_type,
            "duration_min":   duration_min,
            "price":          price,
            "status":         status,
            "scheduled_at":   scheduled_at.isoformat(),
            "customer_name":  customer_name,
            "customer_phone": customer_phone,
        }

        appointments.append(row)
    return appointments


def preview_kpis(call_logs: list[dict], appointments: list[dict]) -> None:
    """Print expected KPIs from synthetic data. (합성 데이터 예상 KPI 미리보기)"""
    total      = len(call_logs)
    successful = sum(1 for c in call_logs if c["call_status"] == "Successful")
    busy       = sum(1 for c in call_logs if c["is_store_busy"])
    dur_h      = sum(c["duration"] for c in call_logs) / 3600

    linked     = [a for a in appointments if a.get("call_log_id")]
    completed  = [a for a in appointments if a["status"] == "completed"]
    avg_price  = (sum(a["price"] for a in appointments) / len(appointments)) if appointments else 0.0

    # Service type breakdown (서비스 유형별 분포)
    service_counts: dict[str, int] = {}
    for a in appointments:
        svc = a["service_type"]
        service_counts[svc] = service_counts.get(svc, 0) + 1

    lcs    = dur_h * 20.0   # AI call hours × $20/hr
    impact = len(completed) * avg_price + lcs

    print(f"\n{'='*55}")
    print(f"JM Beauty Salon — Synthetic Data Preview (seed={SEED})")
    print(f"{'='*55}")
    print(f"  call_logs:    {total}  (Successful: {successful}, Busy: {busy})")
    print(f"  appointments: {len(appointments)}  (Completed: {len(completed)}, Linked: {len(linked)})")
    print(f"  avg_price:    ${avg_price:.2f}")
    print(f"  LCS:          ${lcs:,.2f}  ({dur_h:.1f}h × $20)")
    print(f"  Est. Impact:  ${impact:,.2f}")
    print(f"\n  Service breakdown:")
    for svc in SERVICE_TYPES:
        count = service_counts.get(svc, 0)
        pct   = count / len(appointments) * 100 if appointments else 0
        print(f"    {svc:<12} {count:>3}  ({pct:.1f}%)")
    print(f"{'='*55}\n")


def insert_batch(client: httpx.Client, table: str, rows: list[dict]) -> None:
    """Insert rows in 200-row batches. (200건씩 배치 삽입)"""
    for i in range(0, len(rows), 200):
        batch = rows[i : i + 200]
        r = client.post(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers=HEADERS,
            json=batch,
        )
        if r.status_code not in (200, 201):
            print(f"ERROR inserting {table}: {r.status_code} {r.text}", file=sys.stderr)
            sys.exit(1)
        print(f"  Inserted {len(batch)} rows into {table} (offset {i})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate JM Beauty Salon demo data")
    parser.add_argument("--dry-run", action="store_true", help="Preview KPIs without DB writes")
    args = parser.parse_args()

    if STORE_ID == "REPLACE_WITH_ACTUAL_BEAUTY_SALON_STORE_ID" and not args.dry_run:
        print(
            "ERROR: STORE_ID is still a placeholder.\n"
            "  1. Run the DB migration to insert the beauty salon store.\n"
            "  2. Run: SELECT id FROM stores WHERE name='JM Beauty Salon';\n"
            "  3. Replace STORE_ID in this script with the actual UUID.\n",
            file=sys.stderr,
        )
        sys.exit(1)

    rng = random.Random(SEED)
    random.seed(SEED)

    print("Generating call_logs...")
    call_logs = build_call_logs(rng)
    print(f"  {len(call_logs)} call_logs ready")

    print("Generating appointments...")
    appointments = build_appointments(call_logs, rng)
    print(f"  {len(appointments)} appointments ready")

    preview_kpis(call_logs, appointments)

    if args.dry_run:
        print("DRY RUN — no DB writes.")
        return

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set", file=sys.stderr)
        sys.exit(1)

    with httpx.Client(timeout=30) as client:
        print("Inserting call_logs...")
        insert_batch(client, "call_logs", call_logs)
        print("Inserting appointments...")
        insert_batch(client, "appointments", appointments)

    print("\nDone! JM Beauty Salon demo data inserted.")


if __name__ == "__main__":
    main()
