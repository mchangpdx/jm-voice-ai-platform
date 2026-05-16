-- Phase 2-D.2 — Audit log immutability + retention
-- (감사 로그 변조 방지 + 보관 기간)
--
-- Run once in Supabase SQL editor. Safe to re-run (CREATE OR REPLACE).
--
-- Effect:
--   • UPDATE on audit_logs → ALWAYS rejected (even by service_role).
--   • DELETE on audit_logs → rejected unless inside purge_old_audit_logs().
--   • purge_old_audit_logs(retention_days) — bypasses the DELETE trigger by
--     setting a session flag, then resets it. Default 90 days.

-- ── Block UPDATE (no exceptions — audit history must never be rewritten) ──
CREATE OR REPLACE FUNCTION audit_logs_block_update() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'audit_logs is append-only — UPDATE not allowed'
    USING ERRCODE = '42501';  -- insufficient_privilege
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_logs_no_update ON audit_logs;
CREATE TRIGGER audit_logs_no_update
  BEFORE UPDATE ON audit_logs
  FOR EACH ROW EXECUTE FUNCTION audit_logs_block_update();

-- ── Block DELETE except via purge function ────────────────────────────────
CREATE OR REPLACE FUNCTION audit_logs_block_delete() RETURNS trigger AS $$
BEGIN
  IF current_setting('app.audit_purge_allowed', true) = '1' THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'audit_logs is append-only — call purge_old_audit_logs() to drop entries past retention'
    USING ERRCODE = '42501';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_logs_no_delete ON audit_logs;
CREATE TRIGGER audit_logs_no_delete
  BEFORE DELETE ON audit_logs
  FOR EACH ROW EXECUTE FUNCTION audit_logs_block_delete();

-- ── Retention purge function ──────────────────────────────────────────────
-- Returns the number of rows purged. Default retention = 90 days.
CREATE OR REPLACE FUNCTION purge_old_audit_logs(retention_days int DEFAULT 90)
RETURNS int AS $$
DECLARE
  deleted_count int;
BEGIN
  -- Set session flag so the DELETE trigger lets us through
  PERFORM set_config('app.audit_purge_allowed', '1', true);

  DELETE FROM audit_logs
   WHERE created_at < (now() - (retention_days || ' days')::interval);

  GET DIAGNOSTICS deleted_count = ROW_COUNT;

  -- Reset for safety (transaction-scoped anyway with `true`)
  PERFORM set_config('app.audit_purge_allowed', '0', true);

  RETURN deleted_count;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Allow service_role to invoke the purge via PostgREST RPC
GRANT EXECUTE ON FUNCTION purge_old_audit_logs(int) TO service_role;
