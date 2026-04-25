import { BrowserRouter, Routes, Route } from 'react-router-dom'

// Lazy-loaded vertical views will be added as Matrix UI is built
// (매트릭스 UI 구현 시 업종별 뷰를 lazy-load로 추가)
function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<div>JM Voice AI Platform — One Stop Total Solution</div>} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
