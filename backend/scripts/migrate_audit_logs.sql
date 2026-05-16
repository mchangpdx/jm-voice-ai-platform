-- Phase 2-D — Audit log table for all admin mutations
-- (감사 로그 테이블 — 모든 admin mutation 추적)
--
-- Run once in Supabase SQL editor.
-- Safe to re-run (IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS audit_logs (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_user_id   UUID NOT NULL,
  actor_email     TEXT,
  action          TEXT NOT NULL,    -- e.g. 'agency.update', 'store.transfer', 'user.role_change'
  target_type     TEXT,             -- 'agency' | 'store' | 'user' | NULL
  target_id       UUID,
  before          JSONB,
  after           JSONB,
  ip_address      INET,
  user_agent      TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_actor   ON audit_logs(actor_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_target  ON audit_logs(target_type, target_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_action  ON audit_logs(action, created_at DESC);

-- RLS: only service_role can read/write. Admin endpoints use service_role anyway.
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

-- No policies → effectively service_role only.
-- (Add a policy here later if non-admin users ever need read access.)
