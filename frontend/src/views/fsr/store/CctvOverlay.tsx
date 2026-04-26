// CCTV Overlay component — camera grid with video link display
// (CCTV 오버레이 컴포넌트 — 카메라 그리드와 비디오 링크 표시)

import { useEffect } from 'react'
import { useCctvStore } from '../../../store/cctvStore'
import type { Camera } from '../../../services/solinkApi'
import styles from './CctvOverlay.module.css'

// Determine CSS class for status badge (상태 배지 CSS 클래스 결정)
function statusBadgeClass(status: Camera['status']): string {
  if (status === 'online') return styles.statusOnline
  if (status === 'offline') return styles.statusOffline
  return styles.statusUnknown
}

// Determine CSS class for status dot (상태 점 CSS 클래스 결정)
function dotClass(status: Camera['status']): string {
  if (status === 'online') return styles.dotOnline
  if (status === 'offline') return styles.dotOffline
  return styles.dotUnknown
}

export default function CctvOverlay() {
  const { cameras, selectedCameraId, videoUrl, loading, error, loadCameras, selectCamera, clearError } =
    useCctvStore()

  // Load cameras on mount (마운트 시 카메라 로드)
  useEffect(() => {
    void loadCameras()
  }, [loadCameras])

  // Handle camera card click — fetch video link for current time (카메라 카드 클릭 처리 — 현재 시각 비디오 링크 조회)
  function handleCameraClick(cameraId: string) {
    void selectCamera(cameraId, new Date().toISOString())
  }

  return (
    <div className={styles.container}>
      <h3 className={styles.header}>Live CCTV Cameras</h3>

      {/* Error banner (에러 배너) */}
      {error && (
        <div className={styles.error}>
          <span className={styles.errorText}>{error}</span>
          <button className={styles.errorDismiss} onClick={clearError} aria-label="Dismiss error">
            ×
          </button>
        </div>
      )}

      {/* Loading state (로딩 상태) */}
      {loading && (
        <div className={styles.spinner}>
          <span className={styles.spinnerIcon} />
          <span>Loading...</span>
        </div>
      )}

      {/* Camera grid (카메라 그리드) */}
      {!loading && cameras.length === 0 && !error && (
        <p className={styles.emptyState}>No cameras found.</p>
      )}

      {cameras.length > 0 && (
        <div className={styles.grid}>
          {cameras.map((cam) => (
            <button
              key={cam.id}
              className={`${styles.card} ${selectedCameraId === cam.id ? styles.cardSelected : ''}`}
              onClick={() => handleCameraClick(cam.id)}
              aria-pressed={selectedCameraId === cam.id}
              aria-label={`Select camera ${cam.name}`}
            >
              <span className={styles.cameraName}>{cam.name}</span>
              <span className={`${styles.statusBadge} ${statusBadgeClass(cam.status)}`}>
                <span className={`${styles.dot} ${dotClass(cam.status)}`} />
                {cam.status}
              </span>
            </button>
          ))}
        </div>
      )}

      {/* Video link for selected camera (선택된 카메라의 비디오 링크) */}
      {selectedCameraId && !loading && (
        <div className={styles.videoSection}>
          <span className={styles.videoLabel}>
            Video:{' '}
            {cameras.find((c) => c.id === selectedCameraId)?.name ?? selectedCameraId}
          </span>
          {videoUrl ? (
            <a
              href={videoUrl}
              target="_blank"
              rel="noopener noreferrer"
              className={styles.videoLink}
            >
              Open Playback
            </a>
          ) : (
            <span className={styles.noVideo}>No footage available for this moment.</span>
          )}
        </div>
      )}
    </div>
  )
}
