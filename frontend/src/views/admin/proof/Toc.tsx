// Sticky table-of-contents — scroll-spy highlights the active section.
// Hidden on phones (uses a horizontal chip strip instead via parent CSS).
// (세션 TOC — 스크롤에 따라 활성 섹션 하이라이트, 모바일은 가로 chip로 대체)
import { useEffect, useState } from 'react'
import type { ProofSection } from '../proofSections'
import styles from '../ArchitectureProof.module.css'

export default function Toc({ sections }: { sections: ProofSection[] }) {
  const [activeId, setActiveId] = useState<string>(sections[0]?.id ?? '')

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        // Pick the section nearest to the top of the viewport that is intersecting.
        // (Viewport 상단에 가장 가까운 intersecting 섹션 선택)
        const visible = entries.filter((e) => e.isIntersecting)
        if (visible.length === 0) return
        const top = visible.sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0]
        const id = (top.target as HTMLElement).id
        if (id) setActiveId(id)
      },
      { rootMargin: '-80px 0px -55% 0px', threshold: 0 },
    )
    sections.forEach((s) => {
      const el = document.getElementById(s.id)
      if (el) observer.observe(el)
    })
    return () => observer.disconnect()
  }, [sections])

  const handleClick = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <>
      {/* Desktop / tablet sticky vertical TOC */}
      <nav className={styles.tocVertical} aria-label="Page sections">
        <div className={styles.tocLabel}>ON THIS PAGE</div>
        <ul className={styles.tocList}>
          {sections.map((s) => (
            <li key={s.id}>
              <button
                type="button"
                className={`${styles.tocItem} ${activeId === s.id ? styles.tocItemActive : ''}`}
                onClick={() => handleClick(s.id)}
              >
                <span className={styles.tocItemEmoji}>{s.emoji}</span>
                <span className={styles.tocItemLabel}>{s.title}</span>
              </button>
            </li>
          ))}
        </ul>
      </nav>

      {/* Mobile horizontal chip strip */}
      <nav className={styles.tocHorizontal} aria-label="Page sections (mobile)">
        {sections.map((s) => (
          <button
            key={s.id}
            type="button"
            className={`${styles.tocChip} ${activeId === s.id ? styles.tocChipActive : ''}`}
            onClick={() => handleClick(s.id)}
          >
            <span aria-hidden>{s.emoji}</span> {s.title}
          </button>
        ))}
      </nav>
    </>
  )
}
