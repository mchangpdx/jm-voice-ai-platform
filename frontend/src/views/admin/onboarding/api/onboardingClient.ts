// Onboarding API client — switches between live axios and mock fixture
// (온보딩 API 클라이언트 — 라이브 axios와 mock fixture 전환)
// While backend endpoints (POST /api/admin/onboarding/*) are not deployed,
// USE_MOCK=true returns deterministic JM Pizza data.
// (백엔드 endpoint 미배포 동안 USE_MOCK 사용 — Phase 4-5 완료 후 false로)

import api from '../../../../core/api'
import type {
  ExtractRequest, RawMenuExtraction,
  NormalizedMenuItem, PreviewYamlRequest, PreviewYamlResponse,
  FinalizeRequest, FinalizeResponse,
} from '../types'
import {
  mockExtract, mockNormalize, mockPreviewYaml, mockFinalize,
} from './mockOnboarding'

// Toggle here to flip the entire wizard onto real endpoints
// (이 한 줄만 false 로 바꾸면 라이브 endpoint 사용)
const USE_MOCK = false

export async function extractMenu(req: ExtractRequest): Promise<RawMenuExtraction> {
  if (USE_MOCK) return mockExtract(req)
  const { data } = await api.post<RawMenuExtraction>('/admin/onboarding/extract', req)
  return data
}

export async function normalizeMenu(raw: RawMenuExtraction): Promise<NormalizedMenuItem[]> {
  if (USE_MOCK) return mockNormalize(raw)
  const { data } = await api.post<NormalizedMenuItem[]>('/admin/onboarding/normalize', raw)
  return data
}

export async function previewYaml(req: PreviewYamlRequest): Promise<PreviewYamlResponse> {
  if (USE_MOCK) return mockPreviewYaml(req)
  const { data } = await api.post<PreviewYamlResponse>('/admin/onboarding/preview-yaml', req)
  return data
}

export async function finalizeOnboarding(req: FinalizeRequest): Promise<FinalizeResponse> {
  if (USE_MOCK) return mockFinalize(req)
  const { data } = await api.post<FinalizeResponse>('/admin/onboarding/finalize', req)
  return data
}
