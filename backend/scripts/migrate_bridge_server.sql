-- Bridge Server schema — Phase 2-B.0
-- (Bridge Server 스키마 — Phase 2-B.0)
--
-- Run order: stores → call_logs → THIS migration
-- Run via: psql / Supabase SQL editor
--
-- Three tables:
--   bridge_transactions — one row per high-level transaction (order/job/appt/SO)
--   bridge_payments     — Maverick HPP sessions; many-to-one with transactions
--   bridge_events       — append-only audit log
--
-- All FKs assume gen_random_uuid() is enabled (Supabase default).

create extension if not exists "pgcrypto";

-- ── 1. bridge_transactions ──────────────────────────────────────────────────
create table if not exists bridge_transactions (
    id              uuid primary key default gen_random_uuid(),
    store_id        uuid not null references stores(id),
    vertical        text not null check (vertical in (
                        'restaurant','home_services','beauty','auto_repair'
                    )),
    pos_object_type text not null,
    pos_object_id   text not null,
    customer_phone  text not null,
    customer_name   text,
    state           text not null default 'pending'
                    check (state in (
                        'pending','payment_sent','paid','fulfilled',
                        'canceled','failed','refunded'
                    )),
    total_cents     bigint not null,
    paid_cents      bigint not null default 0,
    call_log_id     text,                   -- backfilled by retell webhook (no FK to avoid race)
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

create index if not exists bridge_transactions_store_state_idx
    on bridge_transactions (store_id, state, created_at desc);

create index if not exists bridge_transactions_phone_idx
    on bridge_transactions (customer_phone, created_at desc);

-- ── 2. bridge_payments ──────────────────────────────────────────────────────
create table if not exists bridge_payments (
    id                  uuid primary key default gen_random_uuid(),
    transaction_id      uuid not null references bridge_transactions(id) on delete cascade,
    maverick_session_id text unique,
    maverick_txn_id     text unique,
    amount_cents        bigint not null,
    purpose             text not null check (purpose in (
                            'full','deposit','balance','estimate','addon','tip','refund'
                        )),
    state               text not null default 'pending'
                        check (state in ('pending','sent','succeeded','failed','expired','refunded')),
    pay_url             text,
    sent_to_phone       text,
    sent_at             timestamptz,
    succeeded_at        timestamptz,
    failed_at           timestamptz,
    failure_reason      text,
    idempotency_key     text unique not null,
    created_at          timestamptz not null default now()
);

create index if not exists bridge_payments_txn_idx
    on bridge_payments (transaction_id, state);

-- ── 3. bridge_events (append-only audit) ────────────────────────────────────
create table if not exists bridge_events (
    id              bigserial primary key,
    transaction_id  uuid references bridge_transactions(id),
    payment_id      uuid references bridge_payments(id),
    event_type      text not null,
    from_state      text,
    to_state        text,
    source          text not null check (source in ('voice','webhook','cron','admin')),
    actor           text,
    payload_hash    text,
    payload_json    jsonb,
    created_at      timestamptz not null default now()
);

create index if not exists bridge_events_txn_idx
    on bridge_events (transaction_id, created_at desc);

create index if not exists bridge_events_payment_idx
    on bridge_events (payment_id, created_at desc);

-- ── RLS policies ────────────────────────────────────────────────────────────
-- service_role bypasses RLS; per-store isolation enforced via store_id matching jwt claim
alter table bridge_transactions enable row level security;
alter table bridge_payments     enable row level security;
alter table bridge_events       enable row level security;

-- Grants (service_role + authenticated)
grant all on all tables    in schema public to anon, authenticated, service_role;
grant all on all sequences in schema public to anon, authenticated, service_role;

-- ── updated_at trigger ──────────────────────────────────────────────────────
create or replace function _set_updated_at()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

drop trigger if exists bridge_transactions_updated_at on bridge_transactions;
create trigger bridge_transactions_updated_at
    before update on bridge_transactions
    for each row execute function _set_updated_at();
