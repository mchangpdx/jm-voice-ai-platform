// 4-layer architecture diagram — inline responsive SVG.
// Each layer is clickable; selected layer surfaces its examples + role below.
// (4계층 도식 — SVG, 계층 클릭 시 상세 패널)
import { useState } from 'react'
import { ARCHITECTURE_LAYERS } from '../proofConstants'
import styles from '../ArchitectureProof.module.css'

const VB_W = 720
const VB_H = 360

export default function ArchitectureSection() {
  const [selectedId, setSelectedId] = useState<string>(ARCHITECTURE_LAYERS[1].id)   // default Layer 2
  const selected = ARCHITECTURE_LAYERS.find((l) => l.id === selectedId) ?? ARCHITECTURE_LAYERS[0]

  const boxW = 600
  const boxH = 56
  const gapY = 18
  const startY = 16
  const startX = (VB_W - boxW) / 2

  return (
    <>
      <p className={styles.sectionSub}>
        Every request flows top-to-bottom through these 4 layers. Layers 1–2 are vertical-agnostic;
        Layer 3 is the only place vertical-specific logic lives. Click a layer to inspect what's inside.
      </p>

      <div className={styles.archWrap}>
        <svg
          viewBox={`0 0 ${VB_W} ${VB_H}`}
          xmlns="http://www.w3.org/2000/svg"
          className={styles.archSvg}
          role="img"
          aria-label="4-layer architecture diagram"
        >
          <defs>
            <marker id="archArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#cbd5e1" />
            </marker>
          </defs>

          {ARCHITECTURE_LAYERS.map((l, idx) => {
            const y = startY + idx * (boxH + gapY)
            const isActive = l.id === selectedId
            return (
              <g key={l.id} className={styles.archLayer} onClick={() => setSelectedId(l.id)}>
                <rect
                  x={startX} y={y} width={boxW} height={boxH} rx={10}
                  fill={isActive ? l.color : '#ffffff'}
                  stroke={l.color}
                  strokeWidth={isActive ? 2 : 1.5}
                  opacity={isActive ? 1 : 0.92}
                />
                <text x={startX + 18} y={y + boxH / 2 + 5} fontSize={13} fontWeight={700} fill={isActive ? '#fff' : l.color}>
                  L{l.num}
                </text>
                <text x={startX + 56} y={y + boxH / 2 - 4} fontSize={14} fontWeight={700} fill={isActive ? '#fff' : '#0f172a'}>
                  {l.name}
                </text>
                <text x={startX + 56} y={y + boxH / 2 + 14} fontSize={11.5} fill={isActive ? 'rgba(255,255,255,0.85)' : '#64748b'}>
                  {l.role}
                </text>
                <text x={startX + boxW - 16} y={y + boxH / 2 + 5} fontSize={13} fontWeight={700}
                      textAnchor="end" fill={isActive ? '#fff' : l.color}>
                  {l.reusePct}%
                </text>

                {/* Down-arrow to next layer */}
                {idx < ARCHITECTURE_LAYERS.length - 1 && (
                  <line
                    x1={VB_W / 2} x2={VB_W / 2}
                    y1={y + boxH + 2} y2={y + boxH + gapY - 2}
                    stroke="#cbd5e1" strokeWidth={2} markerEnd="url(#archArrow)"
                  />
                )}
              </g>
            )
          })}
        </svg>

        {/* Selected layer detail */}
        <div className={styles.archDetail} style={{ borderColor: selected.color }}>
          <div className={styles.archDetailHeader}>
            <span className={styles.archDetailPill} style={{ background: selected.color }}>L{selected.num}</span>
            <span className={styles.archDetailName}>{selected.name}</span>
            <span className={styles.archDetailReuse}>{selected.reusePct}% reuse</span>
          </div>
          <p className={styles.archDetailRole}>{selected.role}</p>
          <div className={styles.archDetailExamples}>
            {selected.examples.map((e) => (
              <code key={e} className={styles.archDetailCode}>{e}</code>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}
