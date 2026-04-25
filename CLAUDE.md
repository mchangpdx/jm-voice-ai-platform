# CLAUDE.md - JM Voice AI Platform Constitution

## 1. Project Vision & Identity
- **Vision**: "One Stop, Total Solution" for SMBs & Agencies.
- **Goal**: Transition from a pure Voice Agent to a holistic Management OS (AI Voice + POS + Security).

## 2. Language & Coding Standards (CRITICAL)
- **Primary Language**: All code, filenames, and internal docs must be in **English**.
- **Comments/Help**: Format is **English + (Korean Summary)**.
  - *Example*: `// Process RLS-enabled query (RLS가 활성화된 쿼리 처리)`
- **Standard**: Follow US currency ($) and timezone formats as default.

## 3. Engineering & Security Rules
- **Data Isolation**: Mandatory PostgreSQL Row-Level Security (RLS). Every query must use `tenant_id`.
- **Fact-Based Logic**: Always conduct a full investigation of existing logic (e.g., variant_id mapping) before proposing changes.
- **Asynchronous Flow**: Use 'Fire-and-Forget' for external API relays (Solink/Loyverse) to maintain UI responsiveness.
- **TDD Requirement**: Write unit/integration tests BEFORE implementing features.

## 4. Directory Structure Hierarchy
- `backend/app/core/`: Layer 1 (Security, RLS, Gemini Engine)
- `backend/app/skills/`: Layer 2 (7 Universal Shared Skills)
- `backend/app/knowledge/`: Layer 3 (Vertical Knowledge Adapters)
- `backend/app/adapters/`: Layer 4 (External Bridges & Relay Engines)