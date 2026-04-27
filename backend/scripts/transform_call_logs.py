#!/usr/bin/env python3
# Transform legacy call_logs CSV for import into new Supabase project.
# (레거시 call_logs CSV를 새 Supabase 프로젝트용으로 변환)
#
# Usage:
#   python3 backend/scripts/transform_call_logs.py \
#     --input ~/Downloads/call_logs_rows.csv \
#     --output ~/Downloads/call_logs_ready.csv \
#     --store-id "7c425fcb-91c7-4eb7-982a-591c094ba9c9"
#
# What this script does (스크립트 동작):
#   1. Preserve ALL columns from original CSV (모든 원본 컬럼 유지)
#   2. Replace store_id with new project's UUID
#   3. Add is_store_busy column based on call start_time vs peak hours

import argparse
import csv
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

STORE_TZ = ZoneInfo("America/Los_Angeles")

# Peak windows — matches busy_schedules seeded in new project
# (day_of_week: 0=Sun, 1=Mon, ..., 6=Sat)
PEAK_WINDOWS = [
    (1, "11:30", "14:00"),
    (2, "11:30", "14:00"),
    (3, "11:30", "14:00"),
    (4, "11:30", "14:00"),
    (5, "11:30", "14:00"),
    (2, "17:30", "21:00"),
    (3, "17:30", "21:00"),
    (4, "17:30", "21:00"),
    (5, "17:30", "22:00"),
    (6, "11:30", "22:00"),
    (0, "10:00", "15:00"),
]


def _hm_to_minutes(hm: str) -> int:
    h, m = map(int, hm.split(":"))
    return h * 60 + m


def _is_peak(start_time_str: str) -> bool:
    if not start_time_str:
        return False
    try:
        # Normalize: space → T, strip all tz suffixes (+00:00, +00, Z)
        ts = start_time_str.strip().replace(" ", "T")
        for tz_suffix in ("+00:00", "-00:00", "+00", "-00"):
            ts = ts.replace(tz_suffix, "")
        ts = ts.rstrip("Z")
        if "." in ts:
            dt_utc = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc)
        else:
            dt_utc = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return False

    dt_local = dt_utc.astimezone(STORE_TZ)
    dow = (dt_local.weekday() + 1) % 7  # Python Mon=0 → 0=Sun…6=Sat
    call_min = dt_local.hour * 60 + dt_local.minute

    for (peak_dow, start_hm, end_hm) in PEAK_WINDOWS:
        if dow == peak_dow and _hm_to_minutes(start_hm) <= call_min < _hm_to_minutes(end_hm):
            return True
    return False


def transform(input_path: str, output_path: str, new_store_id: str) -> None:
    with open(input_path, newline="", encoding="utf-8") as f_in:
        reader = csv.DictReader(f_in)
        rows_in = list(reader)
        original_headers = list(reader.fieldnames or [])

    # Rename ll_id → call_id if the legacy CSV uses that column name
    out_headers = ["call_id" if h == "ll_id" else h for h in original_headers]

    # Append is_store_busy if not already present
    if "is_store_busy" not in out_headers:
        out_headers.append("is_store_busy")

    print(f"Input columns  ({len(original_headers)}): {original_headers}")
    print(f"Output columns ({len(out_headers)}): {out_headers}")

    peak_count = 0
    rows_out = []
    for row in rows_in:
        # Rename ll_id key → call_id
        if "ll_id" in row:
            row["call_id"] = row.pop("ll_id")

        # Replace store_id with new project's UUID
        row["store_id"] = new_store_id

        # Compute is_store_busy from start_time
        start_val = row.get("start_time") or ""
        busy = _is_peak(start_val)
        row["is_store_busy"] = "true" if busy else "false"
        if busy:
            peak_count += 1

        rows_out.append({col: row.get(col, "") for col in out_headers})

    with open(output_path, "w", newline="", encoding="utf-8") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=out_headers)
        writer.writeheader()
        writer.writerows(rows_out)

    total = len(rows_out)
    print(f"\nDone: {total} rows → {output_path}")
    print(f"  is_store_busy=true  : {peak_count} ({peak_count/total*100:.1f}%)")
    print(f"  is_store_busy=false : {total-peak_count} ({(total-peak_count)/total*100:.1f}%)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Transform legacy call_logs CSV for new Supabase project")
    parser.add_argument("--input",    required=True, help="Path to exported CSV from legacy Supabase")
    parser.add_argument("--output",   required=True, help="Output path for transformed CSV")
    parser.add_argument("--store-id", required=True, help="New project's store UUID")
    args = parser.parse_args()
    transform(args.input, args.output, args.store_id)


if __name__ == "__main__":
    main()
