# PRD.md - Product Requirements & Business Impact

## 1. Core Objectives
- Achieve 95%+ intent accuracy for Voice Agents.
- Provide a unified dashboard for CCTV (Solink), POS (Loyverse), and AI interactions.

## 2. Vertical-Specific Scenarios
- **FSR**: Table booking, menu navigation, automated POS injection, and payment link generation.
- **Home Care**: Variable-based estimation (sq.ft, pollution level), technician scheduling, and lead management.

## 3. Comprehensive KPI Metrics (Performance Tracking)
### FSR (Food Service)
- **MCRR (Missed Call Recovery Revenue)**: `(AI Confirmed Bookings * Avg Ticket Size)`. (부재중 전화 복구 매출액)
- **LCS (Labor Cost Savings)**: `(AI Call Duration / 60 * Staff Hourly Wage)`. (인건비 절감액)
- **UV (Upselling Value)**: `(Success Count of AI Recommendations * Item Price)`. (업셀링 추가 수익)
- **Table Turnover Rate**: Comparison between AI-booked and walk-in efficiency. (테이블 회전율)

### Home Care
- **LCR (Lead Conversion Rate)**: `(Confirmed Jobs / Total Inquiries) * 100`. (리드 전환율)
- **Quote Accuracy**: `|AI Estimate - Actual Billed| / Actual Billed`. (견적 정확도)
- **Lead Response Time**: First AI response latency (Target: < 2s). (응답 대기 시간)
- **Staff Utilization**: Ratio of travel time vs. actual working hours. (작업자 가동률)

## 4. One-Stop Feature Requirements
- Real-time POS Text Overlay on CCTV (Solink Integration).
- Matrix UI: Different views for Agency (Aggregated) vs. Store (Operational).