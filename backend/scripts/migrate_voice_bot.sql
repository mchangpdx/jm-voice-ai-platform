-- ═══════════════════════════════════════════════════════════════════════════
-- JM Voice AI Platform — Voice Bot DB Migration
-- Supabase SQL Editor에서 전체 선택 후 Run 하세요
-- ═══════════════════════════════════════════════════════════════════════════

-- Step 1: stores 테이블에 Voice Bot + 매장 지식 관련 컬럼 추가
ALTER TABLE stores
  ADD COLUMN IF NOT EXISTS retell_agent_id  TEXT,
  ADD COLUMN IF NOT EXISTS system_prompt    TEXT,
  ADD COLUMN IF NOT EXISTS temporary_prompt TEXT,
  ADD COLUMN IF NOT EXISTS business_hours   TEXT,
  ADD COLUMN IF NOT EXISTS custom_knowledge TEXT,
  ADD COLUMN IF NOT EXISTS is_active        BOOLEAN DEFAULT true;

-- Step 2: JM Cafe — CAFE-JM-Aria (retell-Grace)
UPDATE stores SET
  retell_agent_id  = 'agent_68e9f01ec4d5502b990755d2ef',
  system_prompt    = 'You are Aria, the friendly AI voice assistant for JM Cafe. Help customers with reservations, menu questions, hours, and general inquiries. Always be warm, concise, and professional. The cafe is located in Portland, Oregon and operates in the Pacific Time zone.',
  temporary_prompt = NULL,
  business_hours   = 'Monday to Friday: 8:00 AM to 8:00 PM. Saturday and Sunday: 9:00 AM to 6:00 PM.',
  custom_knowledge = 'Free Wi-Fi password: jmcafe2026. Free parking available at the back of the building for up to 2 hours — validate at the counter. Restrooms are on the left side of the counter. Gluten-free options available upon request.',
  is_active        = true
WHERE id = '7c425fcb-91c7-4eb7-982a-591c094ba9c9';

-- Step 3: JM Home Services — HOME-JM-Rex (retell-Nico)
UPDATE stores SET
  retell_agent_id  = 'agent_1fb403be0c5428e1a4539ce531',
  system_prompt    = 'You are Rex, the reliable AI voice assistant for JM Home Services. Help customers schedule appointments, get service quotes, and answer questions about plumbing, electrical, HVAC, and general home repair services. Always be professional, efficient, and reassuring.',
  temporary_prompt = NULL,
  business_hours   = 'Monday to Friday: 7:00 AM to 6:00 PM. Saturday: 8:00 AM to 4:00 PM. Sunday: Closed.',
  custom_knowledge = 'Service areas: Portland metro and surrounding areas within 30 miles. Emergency services available 24/7 for existing customers. Free estimates for jobs over $500. Licensed and bonded.',
  is_active        = true
WHERE id = '98ea891e-b2f7-4141-a89a-ab0f64e838dc';

-- Step 4: JM Beauty Salon — BEAUTY-JM-Luna (retell-Rita)
UPDATE stores SET
  retell_agent_id  = 'agent_8dc7692ae9cbee72d548abe967',
  system_prompt    = 'You are Luna, the elegant AI voice assistant for JM Beauty Salon. Help clients book appointments for haircuts, coloring, facials, nails, and other beauty services. Always be gracious, attentive, and make clients feel valued and welcome.',
  temporary_prompt = NULL,
  business_hours   = 'Tuesday to Friday: 10:00 AM to 7:00 PM. Saturday: 9:00 AM to 6:00 PM. Sunday and Monday: Closed.',
  custom_knowledge = 'Walk-ins welcome based on availability. Appointments recommended for color services. 24-hour cancellation policy applies. Gift cards available. Parking available in the lot next to the building.',
  is_active        = true
WHERE id = '34f44792-b200-450e-aeed-cbaaa1c7ff6e';

-- Step 5: JM Auto Repair — AUTO-JM-Alex (retell-Leland)
UPDATE stores SET
  retell_agent_id  = 'agent_40679cdb10a1f29eddbcbe10af',
  system_prompt    = 'You are Alex, the knowledgeable AI voice assistant for JM Auto Repair. Help customers schedule service appointments, get estimates, and answer questions about diagnostics, oil changes, brakes, tires, and general vehicle maintenance. Always be straightforward, trustworthy, and technically clear.',
  temporary_prompt = NULL,
  business_hours   = 'Monday to Friday: 8:00 AM to 6:00 PM. Saturday: 9:00 AM to 3:00 PM. Sunday: Closed.',
  custom_knowledge = 'Free diagnostics with any repair over $200. Loaner cars available for repairs over 4 hours. All parts come with 1-year warranty. AAA-approved facility. Free shuttle service within 5 miles.',
  is_active        = true
WHERE id = '3ebca19e-0bcf-49b2-9211-83675454b3ce';

-- Step 6: 결과 확인 (4개 행 모두 컬럼이 채워져야 함)
SELECT
  name,
  retell_agent_id,
  is_active,
  LEFT(system_prompt, 50)    AS prompt_preview,
  LEFT(business_hours, 40)   AS hours_preview,
  LEFT(custom_knowledge, 50) AS knowledge_preview
FROM stores
ORDER BY name;
