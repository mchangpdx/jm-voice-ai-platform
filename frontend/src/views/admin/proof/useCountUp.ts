// Animate a number from 0 to target on mount. (마운트 시 0→target 카운트업 애니메이션)
import { useEffect, useRef, useState } from 'react'

export function useCountUp(target: number, durationMs = 900, decimals = 0): number {
  const [value, setValue] = useState(0)
  const startedAt = useRef<number | null>(null)
  const rafId = useRef<number | null>(null)

  useEffect(() => {
    startedAt.current = null
    if (rafId.current) cancelAnimationFrame(rafId.current)

    const step = (now: number) => {
      if (startedAt.current == null) startedAt.current = now
      const elapsed = now - startedAt.current
      const t = Math.min(1, elapsed / durationMs)
      // ease-out cubic
      const eased = 1 - Math.pow(1 - t, 3)
      const next = target * eased
      const rounded = decimals > 0
        ? Math.round(next * 10 ** decimals) / 10 ** decimals
        : Math.round(next)
      setValue(rounded)
      if (t < 1) rafId.current = requestAnimationFrame(step)
    }
    rafId.current = requestAnimationFrame(step)
    return () => { if (rafId.current) cancelAnimationFrame(rafId.current) }
  }, [target, durationMs, decimals])

  return value
}
