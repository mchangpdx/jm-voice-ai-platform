# Onboarding Automation Research — 2026-05-07

세션 종합 분석. JM Cafe 메뉴 재설계 + Vertical Templates 다국어 정책 + Admin UI Wizard 설계.

## Files

| # | File | 내용 |
|---|---|---|
| 01 | [`01_jm_cafe_menu_redesign.md`](01_jm_cafe_menu_redesign.md) | 임시 메뉴 → 실제 PDX fast-casual 카페 메뉴 18개 + modifier 8 group + 다국어 alias (EN/ES/KO/JA/ZH) + 알러젠 정밀 매핑 + SQL migration script |
| 02 | [`02_vertical_templates_multilingual.md`](02_vertical_templates_multilingual.md) | 5 vertical (Cafe / KBBQ / Sushi / Chinese / Mexican) template 구조 + 다국어 정책 매트릭스 + 코드 재사용률 측정 |
| 03 | [`03_admin_ui_wizard_design.md`](03_admin_ui_wizard_design.md) | Admin UI Wizard 전수 조사 + 6-step UX flow + 기술 스택 옵션 + 경쟁사 onboarding 비교 + 단계별 구현 계획 + 전문가 의견 |

## 핵심 결정 사항 (이 세션)

1. **JM Cafe 메뉴 18개로 재설계** — 임시 피자/케이크 제거, 실제 PDX 카페 메뉴 (espresso 8 + non-espresso 3 + pastry 5 + food 2). 각 메뉴 5개 언어 alias + FDA-9 알러젠 정밀.

2. **다국어 정책 (사용자 명시)**:
   - 카페 (default vertical): EN + ES + KO + JA + ZH (5 lang)
   - 한식당 (KBBQ / 치킨 / etc): EN + KO
   - 일식당 (스시 / etc): EN + JA
   - 중식당: EN + ZH
   - 멕시칸 식당: EN + ES

3. **JM BBQ 어댑터 다음 작업으로 확정** (이전 세션 분석에서) — 그 작업 자체가 KBBQ template 추출 + Cafe template 비교 base 가 됨. 두 산출물 동시.

4. **Admin UI Wizard = Phase 2 진입 전 필수** (30매장은 수동 한계). saas-platform repo 작업, Phase 8-9에 우선순위.

## 다음 세션 첫 행동

1. OpenAI quota 확인 (사용자)
2. JM Cafe 메뉴 SQL 적용 (01_jm_cafe_menu_redesign.md 참조)
3. 라이브 검증 1통화 (새 메뉴 알러젠 + 다국어)
4. JM BBQ 어댑터 시작 (02_vertical_templates_multilingual.md KBBQ 섹션 참조)

## 사용자 메모

- 모든 비교 표 10점 만점 항목별 + 합계 (사용자 룰)
- Telegram 적극 사용 중
- 2인 팀 (PDX 본사) — 자동화는 ROI 결정적
