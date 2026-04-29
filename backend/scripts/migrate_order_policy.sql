-- Phase 2-B.1.7b — Order Policy Engine + fire_immediate lane columns
-- (Phase 2-B.1.7b — 주문 정책 엔진 + fire_immediate lane 컬럼)
--
-- A-axis only in this version: ticket threshold.
-- B-axis (trusted tier) and C-axis (daily uncollected cap) are deferred.

-- store_configs.order_policy: per-store policy JSON. NULL = policy off (pay_first
-- for every order — safe default that matches current behaviour).
alter table store_configs
    add column if not exists order_policy jsonb;

comment on column store_configs.order_policy is
  'Order routing policy. Keys: fire_immediate_threshold_cents (int). '
  'Total < threshold ⇒ kitchen now, pay link later. '
  '>= threshold or NULL ⇒ pay_first (current default).';

-- bridge_transactions.payment_lane records the lane chosen at order time —
-- fire_immediate or pay_first. Used by reconciliation + analytics.
alter table bridge_transactions
    add column if not exists payment_lane text
        check (payment_lane in ('fire_immediate', 'pay_first', null));

-- bridge_transactions.fired_at: timestamp the kitchen received the order
-- (for fire_immediate lane). pay_first lane writes this when fulfillment runs.
alter table bridge_transactions
    add column if not exists fired_at timestamptz;

-- bridge_transactions.no_show_at: terminal timestamp when reconciliation
-- writes off an unpaid fired_immediate order (T+30min default).
alter table bridge_transactions
    add column if not exists no_show_at timestamptz;

-- New state values are enforced in Python (state_machine.py) — no DB-level
-- enum migration needed since bridge_transactions.state is text.
