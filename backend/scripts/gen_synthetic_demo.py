#!/usr/bin/env python3
"""
Generate synthetic 30-day call_logs + orders for the $100K/month demo scenario.
(30일치 합성 데이터 생성 — $100K/월 레스토랑 데모 시나리오)

Usage:
    python scripts/gen_synthetic_demo.py --dry-run       # preview KPIs, no DB writes
    python scripts/gen_synthetic_demo.py                  # insert into Supabase

Target KPIs (period=month):
  MCRR   ~$10,044   (372 busy_successful × avg ~$27 ticket)
  LCS    ~$1,787    (89h AI call hours × $20/hr hourly wage)
  LCR     62.0%     (930 Successful / 1,500 total calls)
  UV     $1,125     (1,500 × 15% upsell × $5 avg upsell)
  Monthly Impact ~$12,956
"""
import argparse
import os
import random
import sys
import uuid
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

# ── Date window: last 30 days ending yesterday ────────────────────────────────
DAYS  = 30
START = datetime(2026, 3, 27, 0, 0, 0, tzinfo=timezone.utc)
END   = datetime(2026, 4, 25, 23, 59, 59, tzinfo=timezone.utc)

# ── Volume targets (목표 수량) ─────────────────────────────────────────────────
TOTAL_CALLS    = 1500
LCR_RATE       = 0.62   # 62% Successful → 930 calls
BUSY_RATE      = 0.40   # 40% is_store_busy=True → 600 calls

PAID_ORDERS    = 250
PENDING_ORDERS = 80

# ── Portland area codes (포틀랜드 지역 번호) ─────────────────────────────────
PORTLAND_CODES = ["+15031", "+15032", "+15034", "+15036", "+15038",
                  "+19712", "+19713", "+19715", "+19718"]

# ── Realistic call summaries (실제 같은 통화 요약) ────────────────────────────
SUCCESSFUL_SUMMARIES = [
    "Customer ordered a large cappuccino and blueberry muffin for pickup in 15 minutes.",
    "Table reservation made for 4 guests at 7:30 PM tonight.",
    "Customer inquired about gluten-free options and placed an avocado toast order.",
    "Order placed: 2 oat-milk lattes and a croissant. Pickup in 20 minutes.",
    "Reservation confirmed for anniversary dinner, party of 2 at 6 PM Saturday.",
    "Customer asked about daily specials and ordered the salmon bowl with sparkling water.",
    "Catering order for office lunch: 8 sandwiches and 8 drinks, confirmed for tomorrow noon.",
    "Table for 6 reserved for Friday evening at 8 PM, confirmed with customer name.",
    "Returning customer reordered their usual: flat white and everything bagel.",
    "Birthday party reservation for 12 guests, private dining room secured.",
    "Quick takeout: americano and banana bread, paid over phone successfully.",
    "Customer asked about allergen info; placed caesar salad order, no croutons.",
    "Kids menu inquiry; table for 4 with high chair confirmed at noon.",
    "Takeout order: chicken wrap, side of fries, and iced tea.",
    "Customer ordered matcha latte and egg sandwich for immediate pickup.",
    "Weekend brunch reservation for 3 confirmed at 11 AM Sunday.",
    "Corporate lunch for 10 confirmed; menu selections emailed to organizer.",
    "Customer added sparkling water and a croissant to an earlier call-in order.",
    "Happy hour inquiry; customer ordered 2 cold brews at the promotional rate.",
    "Team dinner reservation, party of 8, confirmed for next Thursday at 7 PM.",
    "Pickup order: 3 lattes and 2 muffins for morning meeting.",
    "Customer requested vegetarian menu; ordered avocado toast and matcha latte.",
    "Reservation for date night, table by window requested and confirmed.",
    "Customer placed birthday cake pre-order and reserved outdoor seating.",
    "Quick order: americano and fresh OJ. Ready in 10 minutes.",
]

UNSUCCESSFUL_SUMMARIES = [
    "Caller disconnected before completing the order.",
    "Menu inquiry only, no purchase intent expressed.",
    "Customer called to check hours; no order placed.",
    "Call dropped after 40 seconds, customer did not call back.",
    "Customer asked about loyalty program; no transaction completed.",
    "Wrong number, caller was looking for a different restaurant.",
    "Customer declined after hearing 25-minute wait time.",
    "Reservation requested for a date we are fully booked.",
    "Call dropped during order confirmation step.",
    "Customer decided to visit a different location.",
    "Customer hung up when asked to hold briefly.",
    "Call quality too poor to process an order.",
]

# ── Portland cafe menu (포틀랜드 카페 메뉴) ────────────────────────────────────
MENU = [
    {"name": "Cappuccino",          "price": 5.50},
    {"name": "Latte",               "price": 6.00},
    {"name": "Cold Brew",           "price": 5.75},
    {"name": "Flat White",          "price": 6.25},
    {"name": "Matcha Latte",        "price": 6.50},
    {"name": "Americano",           "price": 4.75},
    {"name": "Oat Milk Latte",      "price": 6.75},
    {"name": "Fresh-Squeezed OJ",   "price": 5.25},
    {"name": "Avocado Toast",       "price": 14.00},
    {"name": "Salmon Bowl",         "price": 18.50},
    {"name": "Caesar Salad",        "price": 12.50},
    {"name": "Egg Sandwich",        "price": 9.50},
    {"name": "Chicken Wrap",        "price": 13.00},
    {"name": "Blueberry Muffin",    "price": 3.75},
    {"name": "Croissant",           "price": 4.25},
    {"name": "Everything Bagel",    "price": 4.50},
    {"name": "Banana Bread",        "price": 3.50},
    {"name": "Side of Fries",       "price": 5.00},
    {"name": "Iced Tea",            "price": 3.50},
    {"name": "Sparkling Water",     "price": 2.75},
]

CUSTOMER_NAMES = [
    "Alex Johnson", "Maria Rodriguez", "Jake Chen", "Sarah Kim",
    "Michael Brown", "Emily Davis", "Chris Wilson", "Ashley Taylor",
    "David Martinez", "Jessica Lee", "Ryan Thompson", "Amanda Garcia",
    "Tyler Anderson", "Brittany Jackson", "Brandon White", "Kayla Harris",
    "Justin Clark", "Megan Lewis", "Austin Robinson", "Nicole Walker",
    "Ethan Young", "Samantha Hall", "Nathan Allen", "Stephanie Wright",
    "Zachary Scott", "Rebecca Green", "Dylan Adams", "Lauren Baker",
]


def rand_phone(rng: random.Random) -> str:
    code = rng.choice(PORTLAND_CODES)
    digits = "".join(str(rng.randint(0, 9)) for _ in range(6))
    return code + digits


def rand_time(rng: random.Random) -> datetime:
    """Random UTC datetime in the 30-day window, biased to business hours.
    (영업시간(7AM-10PM PDT = 14:00-05:00 UTC) 중 랜덤 시간 생성)
    """
    day    = rng.randint(0, DAYS - 1)
    # UTC hours for 7AM–10PM PDT; weight busier hours higher
    hour   = rng.choices(
        [14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4],
        weights=[3, 4, 5, 6, 8, 8, 8, 7, 6, 5, 4, 3, 2, 2, 2],
    )[0]
    minute = rng.randint(0, 59)
    second = rng.randint(0, 59)
    return (START + timedelta(days=day)).replace(hour=hour, minute=minute, second=second)


def gen_call_logs(rng: random.Random) -> list[dict]:
    """Generate TOTAL_CALLS call_log rows with target distributions.
    (목표 분포로 TOTAL_CALLS건 call_log 생성)
    """
    n_succ = round(TOTAL_CALLS * LCR_RATE)       # 930
    n_busy = round(TOTAL_CALLS * BUSY_RATE)       # 600

    successes = [True] * n_succ + [False] * (TOTAL_CALLS - n_succ)
    busies    = [True] * n_busy + [False] * (TOTAL_CALLS - n_busy)
    rng.shuffle(successes)
    rng.shuffle(busies)

    rows: list[dict] = []
    for i in range(TOTAL_CALLS):
        succ = successes[i]
        busy = busies[i]

        if succ:
            duration  = rng.randint(120, 540)    # 2–9 min for successful calls
            sentiment = rng.choices(
                ["Positive", "Neutral", "Negative"], weights=[75, 20, 5]
            )[0]
            summary   = rng.choice(SUCCESSFUL_SUMMARIES)
        else:
            duration  = rng.randint(20, 150)     # 20s–2.5 min for unsuccessful
            sentiment = rng.choices(
                ["Neutral", "Negative"], weights=[55, 45]
            )[0]
            summary   = rng.choice(UNSUCCESSFUL_SUMMARIES)

        cost = round(duration / 60 * 0.13, 4)   # ~$0.13/min (Vapi-style pricing)

        rows.append({
            "call_id":        str(uuid.uuid4()),
            "store_id":       STORE_ID,
            "start_time":     rand_time(rng).isoformat(),
            "customer_phone": rand_phone(rng),
            "duration":       duration,
            "sentiment":      sentiment,
            "call_status":    "Successful" if succ else "Unsuccessful",
            "cost":           cost,
            "recording_url":  None,
            "summary":        summary,
            "is_store_busy":  busy,
        })

    return rows


def gen_orders(rng: random.Random, start_id: int) -> list[dict]:
    """Generate paid + pending orders with realistic Portland cafe menu totals.
    (Portland 카페 메뉴 기반 paid/pending 주문 생성)
    """
    rows: list[dict] = []
    cur_id = start_id

    for status, count in [("paid", PAID_ORDERS), ("pending", PENDING_ORDERS)]:
        for _ in range(count):
            # 3-5 menu items per order → avg ~$27 per order
            n_items  = rng.choices([3, 4, 5], weights=[30, 50, 20])[0]
            selected = rng.sample(MENU, n_items)
            items    = [{"name": it["name"], "quantity": 1} for it in selected]
            total    = round(sum(it["price"] for it in selected), 2)

            name    = rng.choice(CUSTOMER_NAMES)
            t       = rand_time(rng)
            fname   = name.split()[0].lower()
            email   = f"{fname}{rng.randint(10, 99)}@gmail.com"

            rows.append({
                "id":             cur_id,
                "store_id":       STORE_ID,
                "customer_name":  name,
                "customer_phone": rand_phone(rng),
                "customer_email": email,
                "items":          items,
                "total_amount":   total,
                "status":         status,
                "created_at":     t.isoformat(),
            })
            cur_id += 1

    return rows


def preview_kpis(calls: list[dict], orders: list[dict]) -> None:
    """Print expected KPI numbers before committing to DB. (DB 삽입 전 예상 KPI 출력)"""
    total     = len(calls)
    succ      = sum(1 for c in calls if c["call_status"] == "Successful")
    busy_succ = sum(1 for c in calls if c["is_store_busy"] and c["call_status"] == "Successful")
    dur_h     = sum(c["duration"] for c in calls) / 3600

    paid    = [o for o in orders if o["status"] == "paid"]
    revenue = sum(o["total_amount"] for o in paid)
    avg_t   = revenue / len(paid) if paid else 0

    mcrr   = busy_succ * avg_t
    lcs    = dur_h * 20.0
    uv     = total * 0.15 * 5.0
    impact = mcrr + lcs + uv

    pos = sum(1 for c in calls if c["sentiment"] == "Positive")
    neu = sum(1 for c in calls if c["sentiment"] == "Neutral")
    neg = sum(1 for c in calls if c["sentiment"] == "Negative")

    print(f"\n{'='*58}")
    print(f"  예상 KPI (period=month, hourly_wage=$20)")
    print(f"{'='*58}")
    print(f"  Total calls          : {total:,}")
    print(f"  Successful           : {succ:,}  ({succ/total*100:.1f}%)")
    print(f"  is_busy=True         : {sum(1 for c in calls if c['is_store_busy']):,}  ({BUSY_RATE*100:.0f}%)")
    print(f"  is_busy+Successful   : {busy_succ:,}")
    print(f"  Sentiment P/N/Neg    : {pos}/{neu}/{neg}  ({pos/total*100:.0f}%/{neu/total*100:.0f}%/{neg/total*100:.0f}%)")
    print(f"  Total AI hours       : {dur_h:.1f}h")
    print(f"  Paid orders          : {len(paid):,}")
    print(f"  Avg ticket           : ${avg_t:.2f}")
    print(f"  Total AI revenue     : ${revenue:,.2f}")
    print(f"─────────────────────────────────────────────────────────")
    print(f"  MCRR  ({busy_succ} × ${avg_t:.2f}) : ${mcrr:,.2f}")
    print(f"  LCS   ({dur_h:.1f}h × $20)    : ${lcs:,.2f}")
    print(f"  UV    ({total} × 15% × $5)  : ${uv:,.2f}")
    print(f"  ──────────────────────────────────────────")
    print(f"  Monthly Impact       : ${impact:,.2f}")
    print(f"{'='*58}\n")


def batch_insert(client: httpx.Client, table: str, rows: list[dict], batch: int = 100) -> None:
    """Batch-insert rows into a Supabase table via PostgREST. (PostgREST 배치 삽입)"""
    for i in range(0, len(rows), batch):
        chunk = rows[i : i + batch]
        resp  = client.post(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers=HEADERS,
            json=chunk,
        )
        if resp.status_code in (200, 201):
            print(f"  ✅ {table}[{i}:{i+len(chunk)}]  {len(chunk)}건")
        else:
            print(f"  ❌ {table}[{i}:{i+len(chunk)}] 실패: {resp.status_code} {resp.text[:400]}")
            sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic demo data (합성 데모 데이터 생성)")
    parser.add_argument("--dry-run",        action="store_true",
                        help="Preview KPIs only, no DB writes (DB 변경 없이 미리보기만)")
    parser.add_argument("--start-order-id", type=int, default=200,
                        help="First ID for synthetic orders (기존 최대 order ID + 1)")
    parser.add_argument("--seed",           type=int, default=42,
                        help="Random seed for reproducibility (재현성 보장 난수 시드)")
    args = parser.parse_args()

    rng = random.Random(args.seed)

    print("🔧 합성 데이터 생성 중...")
    calls  = gen_call_logs(rng)
    orders = gen_orders(rng, start_id=args.start_order_id)
    preview_kpis(calls, orders)

    if args.dry_run:
        print("✅ Dry-run 완료 — DB 변경 없음")
        return

    with httpx.Client(timeout=60) as client:
        print(f"📞 call_logs {len(calls):,}건 삽입 중...")
        batch_insert(client, "call_logs", calls)

        print(f"\n🛒 orders {len(orders):,}건 삽입 중...")
        batch_insert(client, "orders", orders)

    max_id = max(o["id"] for o in orders)
    print(f"\n🎉 완료! Supabase SQL Editor에서 시퀀스 재설정:")
    print(f"   SELECT setval(pg_get_serial_sequence('orders', 'id'), {max_id});")


if __name__ == "__main__":
    main()
