# DB_SCHEMA.md - Unified Multi-Tenant Schema

## 1. Store Management
- **stores**: Main tenant table.
  - `vertical_type`: FSR, HOME_CARE, RETAIL.
  - `solink_config`: JSONB (site_id, camera_mapping, api_keys).
  - `loyverse_token`: Encrypted access tokens.

## 2. Universal Inventory (Shared Skills Base)
- **menu_items**: Linked via `variant_id` for external POS sync.
- **resources**: Multi-purpose table for Tables (FSR) or Technicians (Home Care).

## 3. Transaction & Security Relay
- **pos_events**: Records all relay activities.
  - `mapped_data`: JSONB (Standardized items/totals for dashboard and overlay).
  - `overlay_status`: Tracking whether it's pushed to Solink.

## 4. Security (RLS)
- Every table MUST have `tenant_id`.
- Policies: `CREATE POLICY tenant_isolation ON tables FOR ALL TO authenticated USING (tenant_id = auth.uid());`