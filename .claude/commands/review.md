# review.md — Rule-Based Code Review Checklist
# (코드 리뷰 체크리스트 — 규칙 기반 자동 검토)

## Security & RLS
- [ ] Every new DB model inherits `TenantBase` with `tenant_id` column
- [ ] No raw SQL queries bypass RLS policies
- [ ] No hardcoded API keys, tokens, or secrets in any file

## Architecture Layer Rules
- [ ] Skills (`app/skills/`) do NOT import from `knowledge/` or `adapters/`
- [ ] Route handlers (`app/api/`) contain NO business logic — delegate to skills
- [ ] External relay calls (Solink/Loyverse) are async fire-and-forget

## Frontend Rules
- [ ] Components receive all data via props — no direct store reads in widgets
- [ ] All API calls go through `src/services/` — no direct fetch in views
- [ ] Agency views never expose single-store secrets

## TDD Compliance
- [ ] New feature has a corresponding test file written FIRST
- [ ] No new code reduces coverage below 85% in skill modules

## Coding Standards
- [ ] Comments follow `// English description (한국어 요약)` format
- [ ] US currency ($) and timezone formats used as default
- [ ] `variant_id` preserved in all product/POS-related data flows
