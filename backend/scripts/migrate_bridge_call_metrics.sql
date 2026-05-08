-- Wave 1 CRM — call duration + returning-caller analytics columns
-- (CRM Wave 1 — 통화 시간 + 재방문 고객 분석용 컬럼 추가)
--
-- Wave A.3 closed the create_order voice-perceived latency gap (3200→293ms).
-- Now we need an empirical answer to "did CRM Wave 1 actually cut returning-
-- caller AHT by the projected 25%?" That requires per-call duration on
-- bridge_transactions plus a few low-cardinality flags so SQL like
--
--   SELECT crm_returning, AVG(call_duration_ms)/1000.0 AS aht_sec
--   FROM bridge_transactions
--   WHERE store_id = $1 AND created_at >= NOW() - INTERVAL '24 hours'
--   GROUP BY crm_returning;
--
-- can prove the lift without grep'ing ngrok logs after the fact.
--
-- Pair with: services/crm/customer_lookup.py (T1 lookup)
--            api/realtime_voice.py _persist_call_metrics (T5 update)
--
-- All columns are NULLABLE — pre-existing rows keep NULL forever, no
-- backfill needed. New rows populate at WebSocket close (background task,
-- fire-and-forget per Wave A.3 latency discipline).
--
-- Idempotent: ADD COLUMN IF NOT EXISTS only. Safe to re-run.

alter table bridge_transactions
    add column if not exists call_duration_ms   bigint,
    add column if not exists crm_returning      boolean,
    add column if not exists crm_visit_count    integer,
    add column if not exists crm_usual_offered  boolean,
    add column if not exists crm_usual_accepted boolean;

comment on column bridge_transactions.call_duration_ms is
  'End-to-end voice call duration in milliseconds (Twilio WebSocket open → '
  'close). Populated by realtime_voice._persist_call_metrics on call end. '
  'NULL for legacy rows or aborted calls without a tx_id binding.';

comment on column bridge_transactions.crm_returning is
  'TRUE when CRM Wave 1 phone-keyed lookup returned a non-empty '
  'CustomerContext at call start (visit_count >= 1). Drives AHT before/after '
  'analytics. NULL for calls before the CRM Wave 1 rollout.';

comment on column bridge_transactions.crm_visit_count is
  'Visit count at call start (paid + settled + fired_unpaid + canceled + '
  'no_show, store-scoped). Snapshot — does not include the current call. '
  'NULL for legacy rows or anonymous callers.';

comment on column bridge_transactions.crm_usual_offered is
  'TRUE when the agent emitted the phrase "the usual" during the call '
  '(detected via transcript regex). Lets us measure whether the offer '
  'happened at all, separate from acceptance.';

comment on column bridge_transactions.crm_usual_accepted is
  'TRUE when the customer accepted "the usual" suggestion and the resulting '
  'create_order used the recent[0] item_set verbatim. Useful for tuning the '
  'usual-eligibility rule in Wave 2.';

-- Phone+store lookup index. The Wave 1 customer_lookup query is
-- (store_id = $1 AND customer_phone = $2 ORDER BY created_at DESC LIMIT 5),
-- which without this index does a sequential scan that grows linearly with
-- the table. Partial index on customer_phone IS NOT NULL avoids bloating
-- with anonymous-caller rows.
create index if not exists idx_bridge_tx_phone_store
    on bridge_transactions (store_id, customer_phone, created_at desc)
    where customer_phone is not null;
