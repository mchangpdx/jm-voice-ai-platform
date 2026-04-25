# app/knowledge/ — Layer 3: Vertical Knowledge Adapters
# (레이어 3: 산업별 지식 어댑터)

## Role
Industry-specific business rules, prompt templates, and data mappings that customize
the universal skills for each vertical (FSR, Home Care, Retail).
(각 업종(FSR·홈케어·리테일)에 맞게 범용 스킬을 커스터마이징하는 업종별 규칙·프롬프트·매핑)

## Structure
| Directory | Vertical (업종) |
|-----------|----------------|
| `fsr/` | Food Service Restaurant — menus, tables, POS mappings (식당·POS 매핑) |
| `homecare/` | Home Care — pricing variables, technician rules (홈케어·가격변수·기사규칙) |
| `retail/` | Retail — inventory rules, product catalog (리테일·재고규칙·상품카탈로그) |

## Layer-Specific Coding Rules
- Knowledge modules inject context into skills via dependency injection, not direct import.
  (지식 모듈은 직접 임포트가 아닌 의존성 주입으로 스킬에 컨텍스트 제공)
- Prompt templates use Jinja2 formatting — no f-string prompt assembly in skills.
  (프롬프트 템플릿은 Jinja2 형식 사용 — 스킬 내 f-string 프롬프트 조립 금지)
- Each vertical directory must export a `KnowledgeAdapter` class with a standard interface.
  (각 업종 디렉토리는 표준 인터페이스를 가진 `KnowledgeAdapter` 클래스를 공개해야 함)
