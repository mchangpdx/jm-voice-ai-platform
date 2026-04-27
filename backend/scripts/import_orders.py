"""
Import orders from legacy CSV into new Supabase project.
(레거시 CSV를 새 Supabase 프로젝트의 orders 테이블로 임포트)

Usage:
    python scripts/import_orders.py --csv ~/Downloads/orders_rows.csv --dry-run
    python scripts/import_orders.py --csv ~/Downloads/orders_rows.csv
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL    = os.getenv("SUPABASE_URL")
SUPABASE_KEY    = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
NEW_STORE_ID    = "7c425fcb-91c7-4eb7-982a-591c094ba9c9"
OLD_STORE_IDS   = {
    "c14ee546-a5bb-4bd8-add5-17c3f376cc6b",  # JM Cafe (old project)
}

HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=minimal",
}


def parse_created_at(raw: str) -> str:
    """Normalize created_at to UTC ISO 8601. (UTC ISO 8601로 정규화)"""
    raw = raw.strip()
    # Formats seen: '2026-02-24 23:21:51.401', '2026-02-24 23:21:51'
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue
    # Already has timezone info
    return raw


def parse_items(raw: str):
    """Parse items JSON, return empty list on failure. (items JSON 파싱)"""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


def transform(csv_path: str) -> list[dict]:
    """Read CSV and return rows ready for Supabase insert. (CSV → Supabase 삽입 형식 변환)"""
    rows = []
    skipped = []

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if r["store_id"] not in OLD_STORE_IDS:
                skipped.append(r["id"])
                continue

            total_amount_raw = r.get("total_amount", "").strip()
            total_amount = float(total_amount_raw) if total_amount_raw else 0.0

            rows.append({
                "id":             int(r["id"]),
                "store_id":       NEW_STORE_ID,
                # agent_id not in new schema — omitted (새 스키마에 없는 컬럼 제외)
                "customer_phone": r.get("customer_phone") or None,
                "customer_email": r.get("customer_email") or None,
                "customer_name":  r.get("customer_name") or None,
                "items":          parse_items(r.get("items", "[]")),
                "total_amount":   total_amount,
                "status":         r.get("status", "pending"),
                "created_at":     parse_created_at(r.get("created_at", "")),
            })

    if skipped:
        print(f"[SKIP] {len(skipped)}건 제외 (다른 스토어): id={skipped}")

    return rows


def run_import(rows: list[dict], dry_run: bool) -> None:
    if dry_run:
        print(f"\n[DRY-RUN] {len(rows)}건 삽입 예정")
        for r in rows[:5]:
            print(f"  id={r['id']} status={r['status']} amount={r['total_amount']:.2f} "
                  f"created_at={r['created_at'][:19]}")
        if len(rows) > 5:
            print(f"  ... 외 {len(rows) - 5}건")
        return

    # Batch insert (배치 삽입)
    BATCH = 50
    inserted = 0
    with httpx.Client() as client:
        for i in range(0, len(rows), BATCH):
            batch = rows[i : i + BATCH]
            resp = client.post(
                f"{SUPABASE_URL}/rest/v1/orders",
                headers=HEADERS,
                json=batch,
            )
            if resp.status_code in (200, 201):
                inserted += len(batch)
                print(f"  ✅ 배치 {i//BATCH + 1}: {len(batch)}건 삽입 완료")
            else:
                print(f"  ❌ 배치 {i//BATCH + 1} 실패: {resp.status_code} {resp.text[:200]}")
                sys.exit(1)

    print(f"\n✅ 총 {inserted}건 삽입 완료")

    # Reset Postgres sequence so next auto-increment is correct
    # (다음 auto-increment 값이 올바르도록 Postgres 시퀀스 초기화)
    max_id = max(r["id"] for r in rows)
    print(f"\n📌 Supabase SQL Editor에서 다음을 실행해 시퀀스를 재설정하세요:")
    print(f"   SELECT setval(pg_get_serial_sequence('orders', 'id'), {max_id});")


def main():
    parser = argparse.ArgumentParser(description="Import orders CSV into new Supabase project")
    parser.add_argument("--csv",      default="/Users/mchangpdx/Downloads/orders_rows.csv")
    parser.add_argument("--dry-run",  action="store_true")
    args = parser.parse_args()

    csv_path = Path(args.csv).expanduser()
    if not csv_path.exists():
        print(f"❌ CSV 파일을 찾을 수 없음: {csv_path}")
        sys.exit(1)

    print(f"📂 CSV: {csv_path}")
    rows = transform(str(csv_path))
    print(f"📊 변환 완료: {len(rows)}건 (paid={sum(1 for r in rows if r['status']=='paid')}, "
          f"pending={sum(1 for r in rows if r['status']=='pending')})")

    run_import(rows, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
