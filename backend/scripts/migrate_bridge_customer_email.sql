-- Phase 2-B.1.10b followup — customer_email column on bridge_transactions
-- (이메일 fallback이 트랜잭션에 영구 기록되도록 컬럼 추가)
--
-- Until now create_order received customer_email as a tool arg and forwarded
-- it directly to send_pay_link_email() — fire-and-forget, no DB row. That's
-- fine for SMS (Twilio's own logs cover it), but for email:
--   - Reconciliation cron can't retry a failed delivery (no addressee on file)
--   - Operator dashboard can't show 'where did we send this?'
--   - Phase 3 CRM can't accumulate email history per phone
--
-- Idempotent: ADD COLUMN IF NOT EXISTS only.

alter table bridge_transactions
    add column if not exists customer_email text;

comment on column bridge_transactions.customer_email is
  'Optional customer email captured by the create_order tool. Used as the '
  'pay-link delivery target while Twilio TCR approval is pending; persisted '
  'so reconciliation + analytics can replay or attribute deliveries.';

-- Index intentionally NOT added — email is rarely a primary lookup key. The
-- create_order idempotency probe still uses (store_id, customer_phone,
-- pos_object_type) so this column is descriptive metadata only.
