# skills/scheduler/ — Resource Reservation Engine
# (스케줄러 스킬 — 자원 예약 엔진)

## Role
Manages availability checks and reservations for any bookable resource:
tables (FSR), technicians (Home Care), or appointment slots (Retail).
(테이블·기술자·예약 슬롯 등 모든 예약 가능 자원의 가용성 확인 및 예약 관리)

## Key Files Expected
| File | Purpose (목적) |
|------|----------------|
| `__init__.py` | Exposes `execute()` entry point (실행 진입점 공개) |
| `availability.py` | Time-slot availability query logic (시간대 가용성 쿼리 로직) |
| `reservation.py` | Create/update/cancel reservation records (예약 생성·수정·취소) |
| `conflict.py` | Double-booking detection (중복 예약 감지) |

## Coding Rules
- All reservation operations must be wrapped in a DB transaction to prevent race conditions.
  (모든 예약 작업은 경쟁 조건 방지를 위해 DB 트랜잭션으로 래핑)
- Resource type is determined by the calling vertical's `SkillContext.vertical`.
  (자원 유형은 호출 업종의 `SkillContext.vertical`로 결정)
