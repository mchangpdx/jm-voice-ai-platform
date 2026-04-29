-- Phase 2-B.1.7b — Order Policy Engine + fire_immediate lane columns
-- (Phase 2-B.1.7b — 주문 정책 엔진 + fire_immediate lane 컬럼)
--
-- A-axis only in this version: ticket threshold.
-- B-axis (trusted tier) and C-axis (daily uncollected cap) are deferred.
--
-- Idempotent: every change is gated by IF NOT EXISTS or guarded with a
-- DO-block + information_schema lookup so re-running is a no-op.

-- ── store_configs.order_policy ────────────────────────────────────────────
-- Per-store policy JSON. NULL = policy off (pay_first for every order — the
-- safe default that matches current behaviour).
alter table store_configs
    add column if not exists order_policy jsonb;

comment on column store_configs.order_policy is
  'Order routing policy. Keys: fire_immediate_threshold_cents (int). '
  'Total < threshold ⇒ kitchen now, pay link later. '
  '>= threshold or NULL ⇒ pay_first (current default).';

-- ── bridge_transactions.payment_lane ──────────────────────────────────────
-- Records the lane chosen at order time — fire_immediate | pay_first.
-- NULL means the row predates the policy engine (legacy reservation flow).
alter table bridge_transactions
    add column if not exists payment_lane text;

-- Add the CHECK constraint only if it doesn't exist yet. Postgres has no
-- "ADD CONSTRAINT IF NOT EXISTS", so we look it up first.
-- Note: NULL is allowed alongside the two enum values — `payment_lane IS
-- NULL OR payment_lane IN (...)` is the correct shape; a bare IN list
-- silently rejects NULL because NULL-comparisons return NULL (not TRUE).
do $$
begin
  if not exists (
    select 1 from information_schema.table_constraints
     where table_name      = 'bridge_transactions'
       and constraint_name = 'bridge_transactions_payment_lane_check'
  ) then
    alter table bridge_transactions
      add constraint bridge_transactions_payment_lane_check
      check (payment_lane is null
             or payment_lane in ('fire_immediate', 'pay_first'));
  end if;
end $$;

-- ── Timestamp columns for fire_immediate lane ─────────────────────────────
-- fired_at:     when the kitchen received the order. Set on
--               PENDING → FIRED_UNPAID (fire_immediate) and on
--               PAID    → FULFILLED   (pay_first).
-- no_show_at:   terminal write-off moment when reconciliation marks an
--               unpaid fire_immediate order NO_SHOW (T+30min default).
alter table bridge_transactions
    add column if not exists fired_at   timestamptz;
alter table bridge_transactions
    add column if not exists no_show_at timestamptz;

-- New state values (FIRED_UNPAID, NO_SHOW) are enforced in Python
-- (state_machine.py); bridge_transactions.state is text, so no DB enum
-- migration is needed.
