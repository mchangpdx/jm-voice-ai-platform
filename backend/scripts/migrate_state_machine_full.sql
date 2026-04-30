-- Migration: align DB CHECK constraints with state_machine.py + script source
--
-- state_machine.py defines 9 states: pending, payment_sent, paid, fulfilled,
-- canceled, failed, refunded, fired_unpaid, no_show. The original
-- migrate_bridge_server.sql only listed the first 7, so any UPDATE that set
-- state='fired_unpaid' (fire_immediate lane after POS create_pending) failed
-- with check_violation 23514 — silently breaking the fire_immediate path and
-- leaving Loyverse with a receipt but bridge_transactions stuck in pending.
--
-- bridge_events.source CHECK also missed 'script', so recovery one-shot
-- scripts (retry_pos_injection.py, etc.) couldn't write audit rows.
--
-- Idempotent: each block drops the old CHECK if present, then re-adds.
-- (state_machine.py와 DB 제약 정렬 — fired_unpaid/no_show/script 추가)

set local statement_timeout = '30s';

-- ── 1. bridge_transactions.state ────────────────────────────────────────────
-- Drop the auto-named CHECK (column-level CHECK becomes
-- "<table>_state_check" by PostgreSQL convention) and replace with the
-- full enum.
alter table bridge_transactions
    drop constraint if exists bridge_transactions_state_check;

alter table bridge_transactions
    add constraint bridge_transactions_state_check
    check (state in (
        'pending',
        'payment_sent',
        'paid',
        'fulfilled',
        'canceled',
        'failed',
        'refunded',
        'fired_unpaid',
        'no_show'
    ));

-- ── 2. bridge_events.source ────────────────────────────────────────────────
-- Allow 'script' for one-shot recovery / reconciliation jobs that need
-- to write audit rows outside the normal voice / webhook / cron paths.
alter table bridge_events
    drop constraint if exists bridge_events_source_check;

alter table bridge_events
    add constraint bridge_events_source_check
    check (source in (
        'voice',
        'webhook',
        'cron',
        'admin',
        'script'
    ));

-- ── 3. Sanity ──────────────────────────────────────────────────────────────
-- Confirm the new constraints are in place. Should return 2 rows.
select conname, pg_get_constraintdef(oid) as def
  from pg_constraint
 where conrelid in ('public.bridge_transactions'::regclass,
                    'public.bridge_events'::regclass)
   and conname in ('bridge_transactions_state_check',
                   'bridge_events_source_check')
 order by conname;
