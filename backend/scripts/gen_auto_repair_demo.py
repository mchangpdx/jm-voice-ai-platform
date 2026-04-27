#!/usr/bin/env python3
"""Generate synthetic 60-day call_logs + service_orders for JM Auto Repair demo.
(JM Auto Repair 60일치 합성 데이터 생성 — 자동차 수리 데모 시나리오)

# STORE_ID below is a placeholder — replace with actual JM Auto Repair store_id after DB migration
# Run: INSERT INTO stores (...) VALUES ('JM Auto Repair', ...) then: SELECT id FROM stores WHERE name='JM Auto Repair'

Usage:
    python scripts/gen_auto_repair_demo.py --dry-run   # preview KPIs, no DB writes
    python scripts/gen_auto_repair_demo.py              # insert into Supabase

Target KPIs (period=60 days, seed=66):
  call_logs:      250 records
  busy_rate:      65% (is_store_busy=True)
  success_rate:   60% (call_status='Successful')
  service_orders: 140 records, ~50% linked to call_logs
  service_types:  oil_change(30%), brake(25%), tire(20%), engine(15%), ac(10%)
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

# STORE_ID below is a placeholder — replace with actual JM Auto Repair store_id after DB migration
# Run: INSERT INTO stores (...) VALUES ('JM Auto Repair', ...) then: SELECT id FROM stores WHERE name='JM Auto Repair'
STORE_ID = "3ebca19e-0bcf-49b2-9211-83675454b3ce"  # JM Auto Repair

HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=minimal",
}

SEED = 66
DAYS = 60

# Date window: last 60 days ending today (2026-04-26)
END   = datetime(2026, 4, 26, 23, 59, 59, tzinfo=timezone.utc)
START = END - timedelta(days=DAYS)

TOTAL_CALLS  = 250
SUCCESS_RATE = 0.60   # 60% Successful → ~150 calls
BUSY_RATE    = 0.65   # 65% is_store_busy=True → ~163 calls

TOTAL_ORDERS = 140
LINK_RATE    = 0.50   # ~50% of service_orders linked to a call_log

# Service type distribution (자동차 수리 서비스 종류 및 비율)
SERVICE_TYPES   = ["oil_change", "brake", "tire", "engine", "ac"]
SERVICE_WEIGHTS = [0.30, 0.25, 0.20, 0.15, 0.10]

# Estimate ranges per service type (서비스별 견적 범위)
ESTIMATE_RANGES = {
    "oil_change": (80,   120),
    "brake":      (200,  600),
    "tire":       (150,  500),
    "engine":     (500, 2000),
    "ac":         (200,  800),
}

# Order status distribution (주문 상태 분포)
ORDER_STATUSES  = ["completed", "in_progress", "quoted", "declined"]
ORDER_WEIGHTS   = [0.40, 0.20, 0.30, 0.10]

# Statuses that receive a final_price (최종 가격이 설정되는 상태)
PRICED_STATUSES = {"completed", "in_progress"}

CALL_STATUSES = ["Successful", "Unsuccessful", "Voicemail"]
SENTIMENTS    = ["Positive", "Neutral", "Negative"]


def rand_time(rng: random.Random) -> datetime:
    """Return a random timestamp within the 60-day window. (60일 윈도우 내 임의 타임스탬프 반환)"""
    delta = END - START
    return START + timedelta(seconds=rng.randint(0, int(delta.total_seconds())))


def build_call_logs(rng: random.Random) -> list[dict]:
    """Generate 250 call_log rows. (250건 call_log 생성)"""
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
            "call_id":        f"auto-{SEED}-{i:04d}",
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


def build_service_orders(call_logs: list[dict], rng: random.Random) -> list[dict]:
    """Generate 140 service_order rows, ~50% linked to a call_log.
    (140건 서비스 주문 생성, 약 50%는 call_log에 연결)
    Prefer linking to busy calls (is_store_busy=True). (바쁜 통화 우선 연결)
    final_price is set only for completed/in_progress orders. (완료/진행중 주문에만 최종 가격 설정)
    """
    # Separate call IDs into busy vs non-busy for preferential linking
    # (바쁜 통화와 그렇지 않은 통화를 분리하여 우선순위 부여)
    busy_call_ids  = [c["call_id"] for c in call_logs if c["is_store_busy"]]
    other_call_ids = [c["call_id"] for c in call_logs if not c["is_store_busy"]]

    # Pool to draw from: busy first, then non-busy (바쁜 통화 우선, 나머지 추가)
    link_pool = busy_call_ids + other_call_ids

    orders = []
    for i in range(TOTAL_ORDERS):
        service_type    = rng.choices(SERVICE_TYPES, weights=SERVICE_WEIGHTS)[0]
        est_lo, est_hi  = ESTIMATE_RANGES[service_type]

        estimate = round(rng.uniform(est_lo, est_hi), 2)
        status   = rng.choices(ORDER_STATUSES, weights=ORDER_WEIGHTS)[0]
        created  = rand_time(rng)

        # final_price: set for completed/in_progress (95% of estimate ± 10%)
        # (최종 가격: completed/in_progress 상태에서만 설정, 견적의 ±10% 범위)
        if status in PRICED_STATUSES:
            multiplier  = rng.uniform(0.90, 1.10)
            final_price = round(estimate * multiplier * 0.95, 2)
        else:
            final_price = None

        # ~50% chance to link to a call_log (약 50% 확률로 call_log 연결)
        call_log_id = None
        if link_pool and rng.random() < LINK_RATE:
            # Draw preferentially from the front (busy calls) (바쁜 통화 우선 선택)
            idx         = rng.randint(0, min(len(busy_call_ids) - 1, len(link_pool) - 1)) if busy_call_ids else rng.randint(0, len(link_pool) - 1)
            call_log_id = link_pool[idx]

        row = {
            "store_id":     STORE_ID,
            "call_log_id":  call_log_id,
            "service_type": service_type,
            "estimate":     estimate,
            "final_price":  final_price,
            "status":       status,
            "created_at":   created.isoformat(),
        }

        orders.append(row)
    return orders


def preview_kpis(call_logs: list[dict], orders: list[dict]) -> None:
    """Print expected KPIs from synthetic data. (합성 데이터 예상 KPI 미리보기)"""
    total      = len(call_logs)
    successful = sum(1 for c in call_logs if c["call_status"] == "Successful")
    busy       = sum(1 for c in call_logs if c["is_store_busy"])
    dur_h      = sum(c["duration"] for c in call_logs) / 3600

    linked    = [o for o in orders if o.get("call_log_id")]
    completed = [o for o in orders if o["status"] == "completed"]
    priced    = [o for o in orders if o.get("final_price") is not None]
    avg_price = (sum(o["final_price"] for o in priced) / len(priced)) if priced else 0.0
    avg_est   = (sum(o["estimate"] for o in orders) / len(orders)) if orders else 0.0

    # Service type breakdown (서비스 유형별 분포)
    service_counts: dict[str, int] = {}
    for o in orders:
        svc = o["service_type"]
        service_counts[svc] = service_counts.get(svc, 0) + 1

    lcs    = dur_h * 20.0   # AI call hours × $20/hr
    impact = len(completed) * avg_price + lcs

    print(f"\n{'='*60}")
    print(f"JM Auto Repair — Synthetic Data Preview (seed={SEED})")
    print(f"{'='*60}")
    print(f"  call_logs:      {total}  (Successful: {successful}, Busy: {busy})")
    print(f"  service_orders: {len(orders)}  (Completed: {len(completed)}, Linked: {len(linked)})")
    print(f"  avg_estimate:   ${avg_est:.2f}")
    print(f"  avg_final_price:${avg_price:.2f}  ({len(priced)} priced orders)")
    print(f"  LCS:            ${lcs:,.2f}  ({dur_h:.1f}h × $20)")
    print(f"  Est. Impact:    ${impact:,.2f}")
    print(f"\n  Service breakdown:")
    for svc in SERVICE_TYPES:
        count = service_counts.get(svc, 0)
        pct   = count / len(orders) * 100 if orders else 0
        print(f"    {svc:<12} {count:>3}  ({pct:.1f}%)")
    print(f"{'='*60}\n")


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
    parser = argparse.ArgumentParser(description="Generate JM Auto Repair demo data")
    parser.add_argument("--dry-run", action="store_true", help="Preview KPIs without DB writes")
    args = parser.parse_args()

    if STORE_ID == "REPLACE_WITH_ACTUAL_AUTO_REPAIR_STORE_ID" and not args.dry_run:
        print(
            "ERROR: STORE_ID is still a placeholder.\n"
            "  1. Run the DB migration to insert the auto repair store.\n"
            "  2. Run: SELECT id FROM stores WHERE name='JM Auto Repair';\n"
            "  3. Replace STORE_ID in this script with the actual UUID.\n",
            file=sys.stderr,
        )
        sys.exit(1)

    rng = random.Random(SEED)
    random.seed(SEED)

    print("Generating call_logs...")
    call_logs = build_call_logs(rng)
    print(f"  {len(call_logs)} call_logs ready")

    print("Generating service_orders...")
    orders = build_service_orders(call_logs, rng)
    print(f"  {len(orders)} service_orders ready")

    preview_kpis(call_logs, orders)

    if args.dry_run:
        print("DRY RUN — no DB writes.")
        return

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set", file=sys.stderr)
        sys.exit(1)

    with httpx.Client(timeout=30) as client:
        print("Inserting call_logs...")
        insert_batch(client, "call_logs", call_logs)
        print("Inserting service_orders...")
        insert_batch(client, "service_orders", orders)

    print("\nDone! JM Auto Repair demo data inserted.")


if __name__ == "__main__":
    main()
