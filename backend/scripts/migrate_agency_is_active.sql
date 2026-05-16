-- Phase 2-A — Add is_active to agencies for soft delete support
-- (에이전시 soft delete를 위한 is_active 컬럼 추가)
--
-- Run once in Supabase SQL editor.
-- Safe to re-run.

ALTER TABLE agencies ADD COLUMN IF NOT EXISTS is_active boolean DEFAULT true;

UPDATE agencies SET is_active = true WHERE is_active IS NULL;

CREATE INDEX IF NOT EXISTS idx_agencies_active
  ON agencies(is_active) WHERE is_active = true;
