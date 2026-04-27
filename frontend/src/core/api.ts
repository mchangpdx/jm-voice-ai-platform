// Axios instance with JWT auth interceptor (JWT 인증 인터셉터가 있는 Axios 인스턴스)
import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

// Request: attach token from localStorage (요청: localStorage에서 토큰 첨부)
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('jm_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Response: on 401, clear session and redirect to login
// (응답: 401 수신 시 세션 초기화 후 로그인 페이지로 리다이렉트)
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('jm_token')
      localStorage.removeItem('jm_store_name')
      localStorage.removeItem('jm_store_id')
      localStorage.removeItem('jm_role')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export default api
