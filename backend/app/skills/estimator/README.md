# skills/estimator/ — Pricing & Quote Calculator
# (견적 스킬 — 가격 및 견적 계산기)

## Role
Computes dynamic quotes based on vertical-specific variables:
area size and pollution level (Home Care), item quantities and modifiers (FSR/Retail).
Aligns with PRD.md Quote Accuracy KPI: |AI Estimate − Actual| / Actual.
(업종별 변수 기반 동적 견적 계산. PRD 견적 정확도 KPI에 부합)

## Key Files Expected
| File | Purpose (목적) |
|------|----------------|
| `__init__.py` | Exposes `execute()` entry point (실행 진입점 공개) |
| `pricing_rules.py` | Business rules per vertical (업종별 가격 규칙) |
| `calculator.py` | Core arithmetic and rounding logic (핵심 연산 및 반올림) |
| `quote_model.py` | Pydantic quote output schema (견적 출력 스키마) |

## Coding Rules
- Always return both `subtotal`, `tax`, and `total` in USD with 2 decimal precision.
  (항상 `subtotal`, `tax`, `total`을 소수 둘째 자리 USD로 반환)
- Variable-based pricing (sq.ft, pollution level) rules are injected from `knowledge/homecare/`.
  (변수 기반 가격 규칙은 `knowledge/homecare/`에서 주입)
