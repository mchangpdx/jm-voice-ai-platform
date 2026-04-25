# skills/slot_filler/ — Conversational Data Collector
# (슬롯 필러 스킬 — 대화 기반 구조화 데이터 수집)

## Role
Extracts and validates structured data (slots) from natural language conversation.
Manages multi-turn dialogs to fill required fields before dispatching to other skills.
(자연어 대화에서 구조화 데이터를 추출·검증. 다음 스킬 호출 전 필수 필드를 채우는 멀티턴 대화 관리)

## Key Files Expected
| File | Purpose (목적) |
|------|----------------|
| `__init__.py` | Exposes `execute()` entry point (실행 진입점 공개) |
| `extractor.py` | NLP extraction via Gemini (Gemini 기반 NLP 추출) |
| `validator.py` | Type and constraint validation per slot (슬롯별 타입·제약 검증) |
| `schema.py` | Slot definitions per vertical (업종별 슬롯 정의) |

## Coding Rules
- Slot schemas are defined per vertical in `schema.py` but the extractor is universal.
  (슬롯 스키마는 업종별로 정의하되 추출기는 범용 사용)
- Never store PII (personal information) in slots beyond the session lifetime.
  (슬롯에 세션 수명을 초과한 개인정보 저장 금지)
