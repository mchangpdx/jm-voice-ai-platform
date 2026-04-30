-- Phase F-1 검증용 — 시나리오 1 통화 직후 Supabase에서 실행
-- (각 블록을 SQL Editor 새 탭에 복사 → Run. 5분 윈도우 사용)

-- ────────────────────────────────────────────────────────────────────────
-- (1) 통화가 backend에 도달했는지
-- 합격 기준: 1건 이상 (없으면 ngrok/Retell 경로 문제)
-- ────────────────────────────────────────────────────────────────────────
SELECT id, agent_id, created_at
  FROM call_logs
 WHERE created_at > NOW() - INTERVAL '5 minutes'
 ORDER BY created_at DESC
 LIMIT 5;


-- ────────────────────────────────────────────────────────────────────────
-- (2) create_order 흐름이 transaction을 만들었는지
-- 합격 기준:
--   payment_lane IN ('fire_immediate','pay_first')   ← NULL이면 reservation fallback (=F-1 미해결)
--   total_cents > 0
--   has_items = true
-- ────────────────────────────────────────────────────────────────────────
SELECT id, state, payment_lane, total_cents,
       items_json IS NOT NULL AS has_items,
       customer_phone, customer_email,
       fired_at, no_show_at, created_at
  FROM bridge_transactions
 WHERE created_at > NOW() - INTERVAL '5 minutes'
 ORDER BY created_at DESC;


-- ────────────────────────────────────────────────────────────────────────
-- (3) 어느 actor가 호출됐는지 (F-1 핵심 검증)
-- 합격 기준:
--   actor 컬럼에 'tool_call:create_order' 등장  ← 이전엔 'tool_call:create_reservation'
--   payload_json의 vertical='order' 또는 'restaurant'
-- ────────────────────────────────────────────────────────────────────────
SELECT event_type, from_state, to_state, actor,
       payload_json::text AS payload, created_at
  FROM bridge_events
 WHERE created_at > NOW() - INTERVAL '5 minutes'
 ORDER BY created_at;


-- ────────────────────────────────────────────────────────────────────────
-- (4) menu_cache 정화 검증 — 'Reservation - $0.00' 라인이 사라졌는지
-- 합격 기준: lines 배열에 'Reservation - $0.00' 없음
-- ────────────────────────────────────────────────────────────────────────
SELECT name, length(menu_cache) AS chars,
       string_to_array(menu_cache, E'\n') AS lines
  FROM stores
 WHERE name = 'JM Cafe';
