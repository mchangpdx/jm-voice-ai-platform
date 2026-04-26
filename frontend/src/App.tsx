import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'

// Lazy-loaded vertical views added as Matrix UI is built
// (매트릭스 UI 구현 시 업종별 뷰를 lazy-load로 추가)
const FsrStoreDashboard = lazy(() => import('./views/fsr/store/Dashboard'))

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<div>JM Voice AI Platform — One Stop Total Solution</div>} />
        {/* FSR Store Operations Dashboard (FSR 스토어 운영 대시보드) */}
        <Route
          path="/fsr/store"
          element={
            <Suspense fallback={<div>Loading...</div>}>
              <FsrStoreDashboard />
            </Suspense>
          }
        />
      </Routes>
    </BrowserRouter>
  )
}

export default App
