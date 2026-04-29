-- Phase 2-B.1.9 — items_json column on bridge_transactions
-- (Phase 2-B.1.9 — bridge_transactions에 items_json 컬럼)
--
-- create_order writes the resolved line items (variant_id, item_id, price,
-- quantity, name) here at order time. settle_payment reads them back when
-- the customer taps the SMS pay link, so the pay_first lane can build the
-- Loyverse receipt without re-resolving the menu.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS only.

alter table bridge_transactions
    add column if not exists items_json jsonb;

comment on column bridge_transactions.items_json is
  'Resolved order line items (variant_id, item_id, price, quantity, name) — '
  'NULL for non-order rows like reservations.';
