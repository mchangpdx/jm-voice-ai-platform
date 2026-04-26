// Zustand store for CCTV camera state management
// (CCTV 카메라 상태 관리를 위한 Zustand 스토어)

import { create } from 'zustand'
import { fetchCameras, fetchVideoLink } from '../services/solinkApi'
import type { Camera } from '../services/solinkApi'

// CCTV store state and action interface (CCTV 스토어 상태 및 액션 인터페이스)
interface CctvState {
  cameras: Camera[]
  selectedCameraId: string | null
  videoUrl: string | null
  loading: boolean
  error: string | null
  // Actions (액션)
  loadCameras: () => Promise<void>
  selectCamera: (id: string, timestamp?: string) => Promise<void>
  clearError: () => void
}

// Create Zustand store with CCTV state (CCTV 상태를 가진 Zustand 스토어 생성)
export const useCctvStore = create<CctvState>((set) => ({
  cameras: [],
  selectedCameraId: null,
  videoUrl: null,
  loading: false,
  error: null,

  // Load all cameras from Solink (Solink에서 모든 카메라 로드)
  loadCameras: async () => {
    set({ loading: true, error: null })
    try {
      const cameras = await fetchCameras()
      set({ cameras, loading: false })
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load cameras'
      set({ error: message, loading: false })
    }
  },

  // Select a camera and fetch its video link (카메라 선택 및 비디오 링크 조회)
  selectCamera: async (id: string, timestamp?: string) => {
    const ts = timestamp ?? new Date().toISOString() // Default to current time (기본값: 현재 시각)
    set({ selectedCameraId: id, videoUrl: null, loading: true, error: null })
    try {
      const url = await fetchVideoLink(id, ts)
      set({ videoUrl: url, loading: false })
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch video link'
      set({ error: message, loading: false })
    }
  },

  // Clear any error state (에러 상태 초기화)
  clearError: () => set({ error: null }),
}))
