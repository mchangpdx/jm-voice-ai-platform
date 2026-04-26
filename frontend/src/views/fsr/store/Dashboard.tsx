// FSR Store Operations Dashboard — main view container
// (FSR 스토어 운영 대시보드 — 메인 뷰 컨테이너)

import CctvOverlay from './CctvOverlay'
import LiveReservations from './LiveReservations'
import VoiceCallLog from './VoiceCallLog'
import styles from './Dashboard.module.css'

export default function Dashboard() {
  return (
    <div className={styles.page}>
      {/* Top header bar with brand name (브랜드명이 있는 상단 헤더 바) */}
      <header className={styles.header}>
        <span className={styles.brandName}>JM Voice AI Platform</span>
        <span className={styles.headerBadge}>One Stop Total Solution</span>
      </header>

      {/* Main content area (메인 콘텐츠 영역) */}
      <main className={styles.content}>
        {/* Page title section (페이지 제목 섹션) */}
        <div className={styles.titleSection}>
          <h1 className={styles.title}>FSR Store Operations</h1>
          <p className={styles.subtitle}>Real-time AI Voice + POS + CCTV</p>
        </div>

        {/* Two-column dashboard grid (2단 대시보드 그리드) */}
        <div className={styles.grid}>
          {/* Left column: CCTV overlay + Voice call log (좌측: CCTV 오버레이 + 음성 통화 로그) */}
          <div className={styles.leftColumn}>
            <section className={styles.panel}>
              <CctvOverlay />
            </section>
            <section className={styles.panel}>
              <VoiceCallLog />
            </section>
          </div>

          {/* Right column: Live reservations + Status info (우측: 실시간 예약 + 상태 정보) */}
          <div className={styles.rightColumn}>
            <section className={styles.panel}>
              <LiveReservations />
            </section>
            <section className={styles.panel}>
              {/* Platform status summary (플랫폼 상태 요약) */}
              <div className={styles.statusInfo}>
                <h3 className={styles.statusTitle}>Platform Status</h3>
                <div className={styles.statusRow}>
                  <span>AI Voice Engine</span>
                  <span className={styles.statusValue}>
                    <span className={styles.onlineIndicator} />
                    Online
                  </span>
                </div>
                <div className={styles.statusRow}>
                  <span>Loyverse POS</span>
                  <span className={styles.statusValue}>
                    <span className={styles.onlineIndicator} />
                    Connected
                  </span>
                </div>
                <div className={styles.statusRow}>
                  <span>Solink CCTV</span>
                  <span className={styles.statusValue}>
                    <span className={styles.onlineIndicator} />
                    Connected
                  </span>
                </div>
                <div className={styles.statusRow}>
                  <span>RLS Tenant Isolation</span>
                  <span className={styles.statusValue}>Active</span>
                </div>
              </div>
            </section>
          </div>
        </div>
      </main>
    </div>
  )
}
