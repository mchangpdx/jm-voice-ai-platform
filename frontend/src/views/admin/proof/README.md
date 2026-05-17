# Architecture Proof — Section Registry

This page is composed of independent **sections** registered in `proofSections.tsx`.
Adding a new proof dimension to the page is **one array entry + one component file**.
The orchestrator (`ArchitectureProof.tsx`) and the TOC (`Toc.tsx`) pick up new
entries automatically.

## File layout

```
views/admin/
├── ArchitectureProof.tsx          # orchestrator (do not edit when adding sections)
├── ArchitectureProof.module.css   # all shared + section styles
├── proofConstants.ts              # data tables consumed by sections
├── proofSections.tsx              # ← the registry (edit here)
└── proof/
    ├── HeroKpi.tsx
    ├── RollupSection.tsx
    ├── ReuseSection.tsx
    ├── CostSection.tsx
    ├── ArchitectureSection.tsx
    ├── CompetitiveSection.tsx
    ├── RoiCalculator.tsx
    ├── LiveDemoCta.tsx
    ├── Toc.tsx
    ├── useCountUp.ts
    └── README.md                  ← this file
```

## How a section is registered

```ts
// proofSections.tsx
export interface ProofSection {
  id:      string                                   // anchor id + TOC key
  title:   string                                   // sidebar label + section <h2>
  emoji:   string                                   // single visual marker
  variant: 'hero' | 'panel' | 'cta'                 // CSS shell
  render:  (props: ProofSectionProps) => ReactElement
}

export const PROOF_SECTIONS: ProofSection[] = [
  { id: 'kpi',     title: 'Headline KPIs',     emoji: '🎯', variant: 'hero',  render: () => <HeroKpi /> },
  { id: 'rollup',  title: 'Vertical Roll-up',  emoji: '📊', variant: 'panel', render: (p) => <RollupSection {...p} /> },
  // ... add new entry here
]
```

### Variants

| Variant | When to use | CSS shell |
|---|---|---|
| `hero`  | First section, draws the eye. Owns its own background/gradient. No auto `<h2>` injected. | `.heroShell` (transparent — your component renders `.hero`) |
| `panel` | Standard content section (table, chart, form). Gets a white card with `<h2>` auto-injected. | `.section` |
| `cta`   | Call-to-action card (e.g. demo phone, signup). No auto `<h2>`. | `.ctaShell` (transparent) |

## Adding a new section — 5 steps

1. **Decide the dimension.** What proof are you adding? Examples: SLA uptime, multilingual coverage matrix, security posture, time-to-onboard percentile, customer logos.
2. **Add the data** to `proofConstants.ts` if it's reusable. Export typed constants like the existing `COMPETITIVE_CRITERIA` / `ARCHITECTURE_LAYERS` / `ROI_DEFAULTS`.
3. **Write the component** at `proof/YourSection.tsx`. Import styles from `'../ArchitectureProof.module.css'` and reuse existing classes where possible (`.sectionSub`, `.tableWrap`, `.chartFootnote`, etc.).
4. **Register it** by adding one entry to `PROOF_SECTIONS` in `proofSections.tsx`. Choose `variant` based on the table above.
5. **Verify**:
   - `npx tsc --noEmit` clean
   - `npx vite build` clean (your section appears in the bundle)
   - Devtools 320 / 768 / 1280 — section reflows correctly
   - TOC chip appears (mobile) and sidebar entry appears (desktop ≥1024)
   - Scroll-spy highlights your section when in view

That's it. No changes to `ArchitectureProof.tsx`, no router edits, no orchestrator surgery.

## Component template

```tsx
// proof/MyDimension.tsx
import styles from '../ArchitectureProof.module.css'

export default function MyDimension() {
  return (
    <>
      <p className={styles.sectionSub}>
        One-sentence framing of why this matters. Keep it under ~24 words.
      </p>

      {/* Your content — tables, charts, custom UI */}

      <p className={styles.chartFootnote}>
        Optional footnote — data source, caveats, last-updated date.
      </p>
    </>
  )
}
```

For sections that need overview data (Rollup uses it):

```tsx
export default function MyDimension({ stores, loading }: ProofSectionProps) {
  if (loading) return <div className={styles.empty}>Loading…</div>
  // ...
}
```

## Shared CSS classes worth knowing

| Class | Use |
|---|---|
| `.sectionSub` | Sub-heading paragraph under the auto-injected `<h2>` |
| `.empty` | Loading / no-data placeholder |
| `.tableWrap` | Wrap a `<table>` so it scrolls horizontally on phones |
| `.numCol` | Right-align + tabular-nums numeric columns |
| `.cardStack` + `.storeCard` | Phone-only card-stack equivalent of a table |
| `.hideOnPhone` / `.showOnPhone` | Toggle desktop table ↔ mobile cards |
| `.chartFootnote` | Small grey footer text under a chart |
| `.savingsCallout` | Green callout box for $ savings figures (see CostSection) |

## Mobile-first rule (project-wide)

Every section **must** work on phone (≤640px), tablet (641–1024px), and desktop
(>1024px). Per `[[feedback-mobile-responsive-mandatory]]`, this is checked on
every PR. Use the standard breakpoints; never introduce 480/720/768/900.

If your section has a wide visualization (table, chart, SVG):
- **Table**: wrap in `.tableWrap` (horizontal scroll) or render a card stack at ≤640.
- **Chart**: use Recharts `<ResponsiveContainer>` with `height` only (not width).
- **SVG**: use a viewBox + `width: 100%; height: auto` so it scales.
- **Form**: stack vertical at ≤640, full-width inputs with 16px font (iOS no-zoom + 44px touch target).

## TOC integration

You don't have to do anything. `Toc.tsx` reads `PROOF_SECTIONS` and:
- Renders a sticky vertical sidebar at ≥1024px (scroll-spy via IntersectionObserver).
- Renders a horizontal scroll-snap chip strip at <1024px.
- Highlights the currently visible section.

The chip/sidebar shows your `emoji` + `title`. Pick a single character emoji and a short title (≤ 22 chars).

## Anti-patterns

- ❌ **Don't import section components into `ArchitectureProof.tsx`.** That defeats the registry — it should never know which sections exist.
- ❌ **Don't put section-specific CSS in component files.** Add it to `ArchitectureProof.module.css` so all sections share the same class registry and breakpoints stay consistent.
- ❌ **Don't introduce new breakpoints.** 640 and 1024 are the standard. Very narrow phones (≤360) get a third breakpoint already; don't add more.
- ❌ **Don't auto-fetch data inside sections.** The orchestrator owns data fetching and passes via `ProofSectionProps`. If you need new data, expose it on the props interface and update the orchestrator once.

## Why this pattern

The original page hardcoded 4 sections in the orchestrator. Adding a fifth required:
- editing imports
- editing JSX
- adding a TOC entry by hand
- duplicating the section shell markup

After the registry refactor:
- 1 component file
- 1 registry entry

Trade-off: a tiny indirection (the registry layer) for permanent extensibility. The orchestrator now stays at ~60 lines forever, regardless of how many proof dimensions we add. Same pattern is a candidate for future pages (Store Overview, Agency Dashboard) — see Cat D in the frontend backlog.
