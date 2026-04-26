// Solink CCTV API service — calls /api/relay/solink/* endpoints
// (Solink CCTV API 서비스 — /api/relay/solink/* 엔드포인트 호출)

import axios from 'axios'

const BASE = '/api/relay/solink' // Vite dev proxy forwards to FastAPI (Vite 개발 프록시가 FastAPI로 전달)

// Get JWT from localStorage key 'jm_token' (localStorage에서 JWT 조회)
function authHeader(): Record<string, string> {
  const token = localStorage.getItem('jm_token') ?? ''
  return { Authorization: `Bearer ${token}` }
}

// Camera status values from Solink (Solink에서 반환하는 카메라 상태 값)
export interface Camera {
  id: string
  name: string
  status: 'online' | 'offline' | 'unknown'
}

// Fetch camera list (카메라 목록 조회)
export async function fetchCameras(): Promise<Camera[]> {
  const response = await axios.get<{ cameras: Camera[] }>(`${BASE}/cameras`, {
    headers: authHeader(),
  })
  return response.data.cameras
}

// Fetch video playback link for a camera at a given timestamp (특정 카메라와 타임스탬프의 비디오 링크 조회)
export async function fetchVideoLink(
  cameraId: string,
  timestamp: string,
): Promise<string | null> {
  const response = await axios.get<{ url: string | null; camera_id: string; timestamp: string }>(
    `${BASE}/video-link`,
    {
      headers: authHeader(),
      params: { camera_id: cameraId, timestamp },
    },
  )
  return response.data.url
}

// Build snapshot URL for use in <img src> (img src에서 사용할 스냅샷 URL 생성)
// NOTE: Authorization cannot be sent via img src; dev proxy handles session passthrough.
// Production requires a signed URL approach from the backend.
// (프로덕션에서는 백엔드에서 서명된 URL 방식 필요)
export function snapshotUrl(cameraId: string, timestamp: string): string {
  const params = new URLSearchParams({ camera_id: cameraId, timestamp })
  return `${BASE}/snapshot?${params.toString()}`
}
