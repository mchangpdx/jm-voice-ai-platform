import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles/tokens.css'    // design tokens — load first so :root vars are available everywhere
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
