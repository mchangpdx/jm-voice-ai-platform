#!/usr/bin/env python3
"""Generate synthetic 60-day call_logs + orders for JM Korean BBQ demo.
(JM Korean BBQ 60일치 합성 데이터 생성 — 한국식 BBQ FSR 데모 시나리오)

Mirrors gen_auto_repair_demo.py pattern but uses `orders` table (restaurant
pattern) instead of `service_orders`. KBBQ-specific calibration:
  - avg ticket ~$78 (BBQ Combo $85-105, A La Carte 2-portion minimum)
  - menu category distribution: BBQ Beef 30%, BBQ Pork 25%, Hot Pot 15%,
    Entree 25%, Appetizer 5%
  - 70% busy rate (FSR dinner rush)
  - language hint: 70% English, 30% Korean (Korean-named customers — embeds
    via summary text "Caller spoke Korean" for downstream filter)

Usage:
    python scripts/gen_kbbq_demo.py --dry-run   # preview KPIs, no DB writes
    python scripts/gen_kbbq_demo.py              # insert into Supabase
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

# JM Korean BBQ store_id — created via B1 step on 2026-05-10
# (B1 단계에서 생성된 JM Korean BBQ store_id — 2026-05-10)
STORE_ID = "e365aa0e-6e62-49a1-8c5f-0c55af72a53d"

HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=minimal",
}

SEED = 510   # 2026-05-10 — distinct from auto_repair (66), beauty, home_services
DAYS = 60

END   = datetime(2026, 5, 10, 23, 59, 59, tzinfo=timezone.utc)
START = END - timedelta(days=DAYS)

TOTAL_CALLS  = 280
SUCCESS_RATE = 0.62   # 62% Successful → ~174 calls
BUSY_RATE    = 0.70   # 70% is_store_busy=True (FSR dinner rush) → ~196 calls
KO_LANG_RATE = 0.30   # 30% Korean callers (다언어 wedge)

TOTAL_ORDERS = 180
LINK_RATE    = 0.60   # ~60% of orders linked to a call_log

# Menu category distribution (KBBQ-specific menu breakdown)
# (KBBQ 메뉴 카테고리 분포)
CATEGORIES = ["bbq_beef", "bbq_pork", "hot_pot", "entree", "appetizer", "bbq_combo"]
CAT_WEIGHTS = [0.28, 0.23, 0.13, 0.23, 0.05, 0.08]   # combo 8% (premium upsell)

# Per-category total range (USD) — derived from menu.yaml × bbq_min_two_orders
# (메뉴 yaml 가격 × 최소 2인분 룰 반영한 카테고리별 총액 범위)
TOTAL_RANGES = {
    "bbq_beef":   (59.90, 91.90),   # 2 × $29.95-$45.95
    "bbq_pork":   (55.90, 61.90),   # 2 × $27.95-$30.95
    "hot_pot":    (45.95, 91.90),   # $45.95 × 1-2 hot pots
    "entree":     (14.95, 55.90),   # $14.95-$27.95 × 1-2 entrees
    "appetizer":  (8.95,  35.95),   # 1-3 appetizers
    "bbq_combo":  (85.00, 210.00),  # combo A/B + sides
}

# Order status distribution (cafe-aligned pattern: paid / pending)
# (cafe 일관 패턴 — knowledge/kbbq.py가 status='paid'를 priced order로 간주)
ORDER_STATUSES = ["paid", "pending"]
ORDER_WEIGHTS  = [0.85, 0.15]

PRICED_STATUSES = {"paid"}

CALL_STATUSES = ["Successful", "Unsuccessful", "Voicemail"]
SENTIMENTS    = ["Positive", "Neutral", "Negative"]

# Sample Korean + English customer names (sim privacy-safe)
EN_NAMES = ["John Doe", "Sarah Park", "Michael Kim", "Emily Chen", "David Lee",
            "Jessica Brown", "Andrew Wilson", "Karen Liu", "Tom Garcia", "Rachel Yoo"]
KO_NAMES = ["김민수", "이지영", "박서준", "최유진", "정태현",
            "강하늘", "윤서연", "한지원", "조민재", "임수빈"]

# Sample call summary phrases (downstream filter / dashboard preview)
EN_SUMMARIES = [
    "Caller ordered BBQ Combo A for 4 people. Confirmed 7pm dine-in.",
    "Customer asked about Galbi doneness — preferred medium-rare. 2 portions.",
    "Reservation for party of 6 — auto 18% gratuity applied per policy.",
    "Caller had peanut allergy concern. Recommended Soondubu and Bulgogi.",
    "Spicy Pork Bulgogi takeout, party_size=2. Picked up at 6:30pm.",
    "Caller asked if Kimchi has shellfish — confirmed yes (anchovy/shrimp paste).",
]
KO_SUMMARIES = [
    "양념갈비 4인분 + 부대전골 1개 주문. 8시 픽업 예정.",
    "삼겹살 2인분 + 차돌배기 2인분 — 매장 식사. 7시 30분 예약.",
    "콤보 B 1세트 + 떡볶이 라면 추가. 30분 후 픽업.",
    "비빔밥 2개 + 된장찌개 1개 takeout. 30분 후 도착 예정.",
    "예약 문의 — 토요일 저녁 6명. 18% 봉사료 안내 후 확정.",
    "김치찌개 매운맛 + 공기밥 추가. 15분 후 픽업.",
]


def rand_time(rng: random.Random) -> datetime:
    """Return a random timestamp within the 60-day window."""
    delta = END - START
    return START + timedelta(seconds=rng.randint(0, int(delta.total_seconds())))


def build_call_logs(rng: random.Random) -> list[dict]:
    """Generate 280 call_log rows (KBBQ FSR pattern)."""
    records = []
    for i in range(TOTAL_CALLS):
        is_ko        = rng.random() < KO_LANG_RATE
        is_successful = rng.random() < SUCCESS_RATE
        is_busy       = rng.random() < BUSY_RATE
        if is_successful:
            status   = "Successful"
            duration = rng.randint(90, 540)   # KBBQ calls slightly longer (FSR menu Q&A)
            sentiment = rng.choices(SENTIMENTS, weights=[0.65, 0.25, 0.10])[0]
            summary  = rng.choice(KO_SUMMARIES if is_ko else EN_SUMMARIES)
        else:
            status   = rng.choices(["Unsuccessful", "Voicemail"], weights=[0.55, 0.45])[0]
            duration = rng.randint(10, 90)
            sentiment = rng.choices(SENTIMENTS, weights=[0.20, 0.40, 0.40])[0]
            summary  = "Voicemail — caller hung up." if status == "Voicemail" else "Call disconnected before completion."
        start = rand_time(rng)
        records.append({
            "call_id":        f"kbbq-{SEED}-{i:04d}",
            "store_id":       STORE_ID,
            "call_status":    status,
            "duration":       duration,
            "is_store_busy":  is_busy,
            "sentiment":      sentiment,
            "start_time":     start.isoformat(),
            "customer_phone": f"+1971{rng.randint(1000000, 9999999)}",
            "cost":           round(duration / 60 * 0.08, 4),
            "summary":        summary,
        })
    return records


def build_orders(call_logs: list[dict], rng: random.Random) -> list[dict]:
    """Generate 180 order rows for KBBQ. ~60% linked to a call_log (busy-preferred)."""
    busy_call_ids  = [c["call_id"] for c in call_logs if c["is_store_busy"]]
    other_call_ids = [c["call_id"] for c in call_logs if not c["is_store_busy"]]
    link_pool = busy_call_ids + other_call_ids

    orders = []
    for i in range(TOTAL_ORDERS):
        category = rng.choices(CATEGORIES, weights=CAT_WEIGHTS)[0]
        lo, hi   = TOTAL_RANGES[category]
        total    = round(rng.uniform(lo, hi), 2)
        status   = rng.choices(ORDER_STATUSES, weights=ORDER_WEIGHTS)[0]
        created  = rand_time(rng)

        is_ko = rng.random() < KO_LANG_RATE
        cust  = rng.choice(KO_NAMES if is_ko else EN_NAMES)

        # ~60% link to a call_log (busy-preferred)
        call_log_id = None
        if link_pool and rng.random() < LINK_RATE:
            idx = rng.randint(0, min(len(busy_call_ids) - 1, len(link_pool) - 1)) if busy_call_ids else rng.randint(0, len(link_pool) - 1)
            # call_log_id reference uses the call_id; orders.call_log_id stores the call_log row id,
            # not the call_id. We'll link via call_id string match later if needed. For sim purposes,
            # we leave call_log_id NULL and let the dashboard infer association via timestamps.
            call_log_id = None

        items = [{
            "name":     f"KBBQ {category}",
            "category": category,
            "price":    total,
            "quantity": 1,
        }]

        row = {
            "store_id":      STORE_ID,
            "call_log_id":   call_log_id,
            "customer_name": cust,
            "customer_phone": f"+1971{rng.randint(1000000, 9999999)}",
            "total_amount":  total,
            "status":        status,
            "items":         items,
            "created_at":    created.isoformat(),
            "notes":         f"[sim seed={SEED}] cat={category} lang={'ko' if is_ko else 'en'}",
        }
        orders.append(row)
    return orders


def preview_kpis(call_logs: list[dict], orders: list[dict]) -> None:
    """Print expected KPIs from synthetic data."""
    total      = len(call_logs)
    successful = sum(1 for c in call_logs if c["call_status"] == "Successful")
    busy       = sum(1 for c in call_logs if c["is_store_busy"])
    dur_h      = sum(c["duration"] for c in call_logs) / 3600
    ko_count   = sum(1 for c in call_logs if any(ko in c["summary"] for ko in ["갈비", "삼겹살", "콤보", "비빔밥", "예약", "김치"]))

    completed = [o for o in orders if o["status"] == "paid"]
    priced    = [o for o in orders if o["status"] in PRICED_STATUSES]
    avg_total = (sum(o["total_amount"] for o in priced) / len(priced)) if priced else 0.0

    # Category breakdown
    cat_counts: dict[str, int] = {}
    for o in orders:
        cat = o["items"][0]["category"]
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    lcs    = dur_h * 20.0   # AI call hours × $20/hr
    impact = len(completed) * avg_total + lcs

    print(f"\n{'='*60}")
    print(f"JM Korean BBQ — Synthetic Data Preview (seed={SEED})")
    print(f"{'='*60}")
    print(f"  call_logs:      {total}  (Successful: {successful}, Busy: {busy})")
    print(f"    KO callers:   ~{ko_count}  ({ko_count/total*100:.1f}%)")
    print(f"  orders:         {len(orders)}  (Completed: {len(completed)}, Priced: {len(priced)})")
    print(f"  avg total:      ${avg_total:.2f}  (target ~$78)")
    print(f"  LCS:            ${lcs:,.2f}  ({dur_h:.1f}h × $20/hr)")
    print(f"  Est. Impact:    ${impact:,.2f}")
    print(f"\n  Menu category breakdown:")
    for cat in CATEGORIES:
        count = cat_counts.get(cat, 0)
        pct   = count / len(orders) * 100 if orders else 0
        print(f"    {cat:<12} {count:>3}  ({pct:.1f}%)")
    print(f"{'='*60}\n")


def insert_batch(client: httpx.Client, table: str, rows: list[dict]) -> None:
    """Insert rows in 200-row batches."""
    for i in range(0, len(rows), 200):
        batch = rows[i : i + 200]
        r = client.post(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers=HEADERS,
            json=batch,
        )
        if r.status_code not in (200, 201):
            print(f"ERROR inserting {table}: {r.status_code} {r.text[:300]}", file=sys.stderr)
            sys.exit(1)
        print(f"  Inserted {len(batch)} rows into {table} (offset {i})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate JM Korean BBQ demo data")
    parser.add_argument("--dry-run", action="store_true", help="Preview KPIs without DB writes")
    args = parser.parse_args()

    rng = random.Random(SEED)
    random.seed(SEED)

    print("Generating call_logs...")
    call_logs = build_call_logs(rng)
    print(f"  {len(call_logs)} call_logs ready")

    print("Generating orders...")
    orders = build_orders(call_logs, rng)
    print(f"  {len(orders)} orders ready")

    preview_kpis(call_logs, orders)

    if args.dry_run:
        print("DRY RUN — no DB writes.")
        return

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set", file=sys.stderr)
        sys.exit(1)

    # Idempotency check
    with httpx.Client(timeout=30) as client:
        r = client.get(
            f"{SUPABASE_URL}/rest/v1/call_logs",
            headers={**HEADERS, "Prefer": "count=exact"},
            params={"store_id": f"eq.{STORE_ID}", "select": "call_id", "limit": "1"},
        )
        existing = int(r.headers.get("content-range", "0/0").split("/")[-1] or 0)
        if existing >= TOTAL_CALLS:
            print(f"  ! Already {existing} call_logs exist for KBBQ store — SKIP INSERT to prevent duplicates.")
            return

        print("Inserting call_logs...")
        insert_batch(client, "call_logs", call_logs)
        print("Inserting orders...")
        insert_batch(client, "orders", orders)

    print("\nDone! JM Korean BBQ demo data inserted.")


if __name__ == "__main__":
    main()
