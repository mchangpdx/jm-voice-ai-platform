/// <reference types="vite/client" />

// CSS Modules type declaration — allows importing *.module.css files
// (CSS 모듈 타입 선언 — *.module.css 파일 임포트 허용)
declare module '*.module.css' {
  const classes: Record<string, string>
  export default classes
}
