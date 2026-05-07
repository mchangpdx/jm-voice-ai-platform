-- Phase 7-A grant fix — modifier system tables missing service_role/anon GRANT.
-- (modifier 시스템 테이블에 service_role/anon GRANT 추가 — Supabase 표준 패턴)
--
-- Diagnosis: PostgREST returns 42501 "permission denied" for service_role
-- on the new 3 tables. menu_items (existing) returns 200 — confirms the
-- new tables didn't inherit the public schema GRANTs. Apply this once.
--
-- Apply via Supabase SQL Editor.

GRANT ALL ON TABLE modifier_groups            TO service_role, authenticated, anon;
GRANT ALL ON TABLE modifier_options           TO service_role, authenticated, anon;
GRANT ALL ON TABLE menu_item_modifier_groups  TO service_role, authenticated, anon;

-- (Sequences: UUID PKs use gen_random_uuid() not sequences, so no GRANT needed.
--  But include defensive USAGE on sequences anyway — Supabase pattern.)
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO service_role, authenticated, anon;

-- Verify (run after):
-- SELECT grantee, privilege_type FROM information_schema.role_table_grants
-- WHERE table_name = 'modifier_groups';
