# ADR.md - Architecture Decision Records

## ADR-005: Universal Relay Engine for Security
- **Decision**: Centralize Solink/Loyverse relay logic in `backend/app/adapters/relay/`.
- **Reason**: To enable real-time "Eyes + Ears" (Voice AI + CCTV) intelligence on a single dashboard.

## ADR-006: Matrix Dashboard Layout
- **Decision**: Role-based UI structure (Agency vs Store).
- **Reason**: To support the "One Stop Solution" vision by providing management tools for Agencies and operational tools for Owners.