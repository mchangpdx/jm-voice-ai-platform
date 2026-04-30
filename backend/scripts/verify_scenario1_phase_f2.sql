-- Phase F-2 verification — drop the time-window guess; pull the most-recent
-- rows directly so we can see (a) whether data exists at all and (b) what
-- timezone offset the Supabase clock is on.
-- (Phase F-2 검증 — 윈도우 무관, 가장 최신 row 직접 조회)


-- ────────────────────────────────────────────────────────────────────────
-- (A) Server clock — confirm tz offset before doing any window logic
-- ────────────────────────────────────────────────────────────────────────
SELECT NOW()                       AS server_now,
       current_setting('TIMEZONE') AS tz;


-- ────────────────────────────────────────────────────────────────────────
-- (1) Latest 10 call_logs (no window)
-- ────────────────────────────────────────────────────────────────────────
SELECT call_id, agent_id, store_id, customer_phone, call_status, created_at
  FROM call_logs
 ORDER BY created_at DESC
 LIMIT 10;


-- ────────────────────────────────────────────────────────────────────────
-- (2) Latest 10 bridge_transactions (no window)
--     Look for: payment_lane IN ('pay_first','fire_immediate'),
--               total_cents > 0, customer_phone like '%5037079566%'
-- ────────────────────────────────────────────────────────────────────────
SELECT id,
       state,
       payment_lane,
       total_cents,
       (items_json IS NOT NULL)        AS has_items,
       jsonb_array_length(items_json)  AS item_count,
       customer_phone,
       customer_name,
       customer_email,
       pos_object_type,
       pos_object_id,
       call_log_id,
       created_at
  FROM bridge_transactions
 ORDER BY created_at DESC
 LIMIT 10;


-- ────────────────────────────────────────────────────────────────────────
-- (3) Latest 30 bridge_events (no window)
--     Look for: actor = 'tool_call:create_order'
-- ────────────────────────────────────────────────────────────────────────
SELECT event_type,
       from_state,
       to_state,
       actor,
       source,
       transaction_id,
       created_at
  FROM bridge_events
 ORDER BY created_at DESC
 LIMIT 30;


-- ────────────────────────────────────────────────────────────────────────
-- (4) Idempotency check across the latest 30 minutes (server clock)
--     PASS: distinct_tx = 1 per (store_id, customer_phone)
-- ────────────────────────────────────────────────────────────────────────
SELECT store_id,
       customer_phone,
       COUNT(*)                       AS row_count,
       COUNT(DISTINCT id)             AS distinct_tx,
       MIN(created_at)                AS first_seen,
       MAX(created_at)                AS last_seen
  FROM bridge_transactions
 WHERE pos_object_type = 'order'
   AND created_at > NOW() - INTERVAL '30 minutes'
 GROUP BY store_id, customer_phone
 ORDER BY last_seen DESC;


-- ────────────────────────────────────────────────────────────────────────
-- (5) Pass/fail summary using a 60-minute window (more forgiving)
--     Returns ONE row. all_pass = true means F-2 verification gate cleared.
-- ────────────────────────────────────────────────────────────────────────
WITH win AS (SELECT NOW() - INTERVAL '60 minutes' AS t0),
     calls   AS (SELECT COUNT(*) AS n FROM call_logs, win
                  WHERE call_logs.created_at > win.t0),
     good_tx AS (SELECT COUNT(*) AS n FROM bridge_transactions, win
                  WHERE bridge_transactions.created_at > win.t0
                    AND payment_lane IN ('pay_first','fire_immediate')
                    AND total_cents > 0),
     tc_evt  AS (SELECT COUNT(*) AS n FROM bridge_events, win
                  WHERE bridge_events.created_at > win.t0
                    AND actor = 'tool_call:create_order'),
     menu_ok AS (SELECT NOT (menu_cache ILIKE '%Reservation%') AS ok
                   FROM stores WHERE name = 'JM Cafe')
SELECT calls.n   AS call_count,
       good_tx.n AS good_tx_count,
       tc_evt.n  AS tool_call_event_count,
       menu_ok.ok AS menu_cache_clean,
       (calls.n   >= 1
        AND good_tx.n >= 1
        AND tc_evt.n  >= 1
        AND menu_ok.ok)        AS all_pass
  FROM calls, good_tx, tc_evt, menu_ok;


-- ────────────────────────────────────────────────────────────────────────
-- (6) menu_cache hygiene
-- ────────────────────────────────────────────────────────────────────────
SELECT name,
       length(menu_cache) AS chars,
       (menu_cache ILIKE '%Reservation%') AS has_reservation_line,
       string_to_array(menu_cache, E'\n') AS lines
  FROM stores
 WHERE name = 'JM Cafe';
