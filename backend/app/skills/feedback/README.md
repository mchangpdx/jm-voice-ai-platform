# skills/feedback/ — Review Collection & CRM Data
# (피드백 스킬 — 리뷰 수집 및 CRM 데이터화)

## Role
Captures post-interaction feedback, ratings, and structured review data.
Feeds into the Agency dashboard for multi-store satisfaction analytics.
(대화 후 피드백·평점·구조화 리뷰 데이터 수집. 에이전시 대시보드의 다중 매장 만족도 분석에 활용)

## Key Files Expected
| File | Purpose (목적) |
|------|----------------|
| `__init__.py` | Exposes `execute()` entry point (실행 진입점 공개) |
| `collector.py` | Prompt generation for feedback solicitation (피드백 요청 프롬프트 생성) |
| `analyzer.py` | Sentiment analysis via Gemini (Gemini 기반 감성 분석) |
| `crm_writer.py` | Persist structured feedback to CRM table (구조화 피드백 CRM 테이블에 저장) |

## Coding Rules
- Feedback collection must only trigger after a completed transaction or booking.
  (피드백 수집은 거래·예약 완료 후에만 트리거)
- Sentiment scores must be stored as `FLOAT` between -1.0 (negative) and 1.0 (positive).
  (감성 점수는 -1.0 ~ 1.0 범위의 `FLOAT`으로 저장)
