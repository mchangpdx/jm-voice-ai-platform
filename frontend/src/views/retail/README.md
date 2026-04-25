# views/retail/ — Retail Module
# (리테일 뷰 모듈 — 리테일 업종 화면)

## Role
All UI views for the Retail vertical.
Covers product catalog browsing, inventory management, POS transaction history, and stock alerts.
(리테일 업종 모든 UI 뷰. 상품 카탈로그·재고 관리·POS 거래 내역·재고 알림 포함)

## Structure
| Directory | Role (역할) |
|-----------|------------|
| `agency/` | Multi-store inventory and sales aggregation (다중 매장 재고·매출 집계) |
| `store/` | Single-store operational POS and catalog (단일 매장 POS·카탈로그 운영) |

## Key Files Expected (per role dir)
- `Dashboard.tsx` — Main retail view entry (메인 리테일 뷰 진입점)
- `ProductCatalog.tsx` — Searchable product grid with filters (검색·필터 가능한 상품 그리드)
- `InventoryAlert.tsx` — Low-stock threshold alerts (재고 부족 임계치 알림)
- `TransactionHistory.tsx` — Paginated POS transaction log (페이징 POS 거래 로그)

## Coding Rules
- Product availability (`is_in_stock`) must reflect real-time inventory — cache max TTL is 30 seconds.
  (상품 가용성은 실시간 재고 반영 필수 — 캐시 최대 TTL 30초)
- All product actions carry `variant_id` for downstream POS relay compatibility.
  (모든 상품 작업은 POS 릴레이 호환을 위해 `variant_id` 포함)
