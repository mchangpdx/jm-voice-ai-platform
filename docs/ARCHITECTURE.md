# ARCHITECTURE.md - 4-Layer Intelligence OS

## 1. Layered Abstraction
- **Layer 1 (Core)**: Auth, Multi-tenant RLS, Gemini 3.1 Flash-Lite Orchestrator.
- **Layer 2 (7 Shared Skills)**: Catalog, Slot Filler, Scheduler, Estimator, Transaction, Tracker, Feedback.
- **Layer 3 (Knowledge)**: Dynamic prompt assembly (Global + Context + Essential + Temporary).
- **Layer 4 (Adapters)**: Solink Cloud API Bridge, Loyverse Webhook Relay.

## 2. Dynamic Prompt Orchestration
- **Global Rules**: Core safety and operational constraints.
- **Store Context**: Real-time menu, hours, and inventory data.
- **Essential Prompt**: Agency-defined core persona.
- **Temporary Prompt**: Owner-defined daily updates (e.g., "Sold out on specials").

## 3. POS Security Relay Engine
- **Ingestion**: Handles Loyverse `receipts.update` webhooks.
- **Mapping**: Matches `variant_id` and `payment_type_id` to ensure valid POS injection.
- **Relay**: Standardizes payload and pushes Text Overlay to Solink API for CCTV synchronization.