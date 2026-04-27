#!/usr/bin/env python3
"""Generate synthetic 30-day call_logs + jobs for JM Home Services demo.
(JM Home Services 30일치 합성 데이터 생성 — 홈서비스 데모 시나리오)

Usage:
    python scripts/gen_home_services_demo.py --dry-run   # preview KPIs, no DB writes
    python scripts/gen_home_services_demo.py              # insert into Supabase

Target KPIs (period=month, seed=99):
  FTR    ~$8,400   (21 field_booked_jobs × avg $400)
  LCS    ~$1,200   (60h AI call hours × $20/hr)
  JBR    ~60%      (180 booked / 300 total calls)
  LRR    ~$3,600   (300 × 30% × $400 × 10%)
  Monthly Impact ~$13,200
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

# JM Home Services store_id (confirmed from DB insert)
STORE_ID = "98ea891e-b2f7-4141-a89a-ab0f64e838dc"

HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=minimal",
}

DAYS  = 30
START = datetime(2026, 3, 27, 0, 0, 0, tzinfo=timezone.utc)
END   = datetime(2026, 4, 25, 23, 59, 59, tzinfo=timezone.utc)

TOTAL_CALLS    = 300
SUCCESS_RATE   = 0.70   # 70% Successful → 210 calls
FIELD_RATE     = 0.70   # 70% is_store_busy=True (contractor on-site) → 210 calls
BOOKING_RATE   = 0.60   # 60% of calls lead to booked jobs → 180 jobs
AVG_JOB_VALUE  = 400.0  # Average job value ($)

JOB_TYPES = ["paint", "repair", "carpet", "cleaning"]
JOB_TYPE_WEIGHTS = [0.30, 0.35, 0.15, 0.20]

CALL_STATUSES = ["Successful", "Unsuccessful", "Voicemail"]
SENTIMENTS    = ["Positive", "Neutral", "Negative"]

SEED = 99


def rand_time() -> datetime:
    delta = END - START
    return START + timedelta(seconds=random.randint(0, int(delta.total_seconds())))


def build_call_logs(rng: random.Random) -> list[dict]:
    """Generate 300 call_log rows. (300건 call_log 생성)"""
    records = []
    for i in range(TOTAL_CALLS):
        is_successful = rng.random() < SUCCESS_RATE
        is_busy       = rng.random() < FIELD_RATE
        status        = "Successful" if is_successful else rng.choices(
            ["Unsuccessful", "Voicemail"], weights=[0.6, 0.4]
        )[0]
        duration = rng.randint(60, 600) if is_successful else rng.randint(10, 90)
        start    = rand_time()
        records.append({
            "call_id":       f"hs-{SEED}-{i:04d}",
            "store_id":      STORE_ID,
            "call_status":   status,
            "duration":      duration,
            "is_store_busy": is_busy,
            "sentiment":     rng.choice(SENTIMENTS),
            "start_time":    start.isoformat(),
            "customer_phone": f"+1503{rng.randint(1000000, 9999999)}",
            "cost":          round(duration / 60 * 0.08, 4),
        })
    return records


def build_jobs(call_logs: list[dict], rng: random.Random) -> list[dict]:
    """Generate job rows for ~60% of calls. (전체 통화의 60%에 해당하는 작업 생성)"""
    jobs = []
    for call in call_logs:
        if rng.random() >= BOOKING_RATE:
            continue
        job_value = round(rng.uniform(150, 1200), 2)
        job_type  = rng.choices(JOB_TYPES, weights=JOB_TYPE_WEIGHTS)[0]
        call_dt   = datetime.fromisoformat(call["start_time"])
        sched_dt  = call_dt + timedelta(days=rng.randint(1, 14))
        status    = rng.choices(
            ["booked", "completed", "cancelled"],
            weights=[0.55, 0.35, 0.10],
        )[0]
        jobs.append({
            "store_id":       STORE_ID,
            "call_log_id":    call["call_id"],
            "job_type":       job_type,
            "scheduled_date": sched_dt.date().isoformat(),
            "job_value":      job_value,
            "status":         status,
        })
    return jobs


def preview_kpis(call_logs: list[dict], jobs: list[dict]) -> None:
    """Print expected KPIs from synthetic data. (합성 데이터 예상 KPI 미리보기)"""
    total    = len(call_logs)
    success  = sum(1 for c in call_logs if c["call_status"] == "Successful")
    field    = sum(1 for c in call_logs if c["is_store_busy"])
    dur_h    = sum(c["duration"] for c in call_logs) / 3600

    booked   = [j for j in jobs if j["status"] in ("booked", "completed")]
    field_ids = {c["call_id"] for c in call_logs if c["is_store_busy"]}
    field_booked = [j for j in booked if j["call_log_id"] in field_ids]
    avg_val  = (sum(j["job_value"] for j in booked) / len(booked)) if booked else AVG_JOB_VALUE

    ftr = len(field_booked) * avg_val
    lcs = dur_h * 20.0
    jbr = len(booked) / total * 100 if total else 0
    lrr = total * 0.30 * avg_val * 0.10
    impact = ftr + lcs + lrr

    print(f"\n{'='*50}")
    print(f"JM Home Services — Synthetic Data Preview (seed={SEED})")
    print(f"{'='*50}")
    print(f"  call_logs:  {total}  (Successful: {success}, Field: {field})")
    print(f"  jobs:       {len(jobs)}  (Booked+Completed: {len(booked)}, FieldBooked: {len(field_booked)})")
    print(f"  avg_job:    ${avg_val:.2f}")
    print(f"  FTR:        ${ftr:,.2f}  ({len(field_booked)} field jobs × ${avg_val:.0f})")
    print(f"  LCS:        ${lcs:,.2f}  ({dur_h:.1f}h × $20)")
    print(f"  JBR:        {jbr:.1f}%")
    print(f"  LRR:        ${lrr:,.2f}")
    print(f"  Impact:     ${impact:,.2f}")
    print(f"{'='*50}\n")


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
    parser = argparse.ArgumentParser(description="Generate JM Home Services demo data")
    parser.add_argument("--dry-run", action="store_true", help="Preview KPIs without DB writes")
    args = parser.parse_args()

    rng = random.Random(SEED)
    random.seed(SEED)

    print("Generating call_logs...")
    call_logs = build_call_logs(rng)
    print(f"  {len(call_logs)} call_logs ready")

    print("Generating jobs...")
    jobs = build_jobs(call_logs, rng)
    print(f"  {len(jobs)} jobs ready")

    preview_kpis(call_logs, jobs)

    if args.dry_run:
        print("DRY RUN — no DB writes.")
        return

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set", file=sys.stderr)
        sys.exit(1)

    with httpx.Client(timeout=30) as client:
        print("Inserting call_logs...")
        insert_batch(client, "call_logs", call_logs)
        print("Inserting jobs...")
        insert_batch(client, "jobs", jobs)

    print("\nDone! JM Home Services demo data inserted.")


if __name__ == "__main__":
    main()
