# AGENTS.md — Visual Identity Contract (COYOTE BURGUER)

> **Compact Agent Directive:** Enforce these tokens on every front-end file. Do not use default Tailwind indigo/slate palettes.

## 1. Mandatory Tokens
- **Archetype:** `Artisanal Desert Folk & Handcrafted Street-Food Identity`
- **Canvas & Surfaces:**
  - Primary BG: `#31292A` (ink: `#F6F2EA`)
  - Contrast Band BG: `#C4B6A6` (ink: `#141210`)
  - Card Surface: `#262320` (ink: `#F6F2EA`)
- **Ink & Accents:**
  - Text Primary: `#F6F2EA` | Text Secondary: `#C4B6A6`
  - Primary CTA Accent: `#9B3721` (ink: `#FAF8F5`)
  - Supporting Badge Accent: `#C63E30` (ink: `#FAF8F5`)
- **Typography:**
  - Display: `'Fraunces'` (`800`, `uppercase`, tracking `-0.02em`)
  - Section: `'Bebas Neue'` (`400`, `uppercase`)
  - Body: `'Plus Jakarta Sans'` | Mono: `'Space Mono'`
  - Import URL: `https://fonts.googleapis.com/css2?family=Fraunces:wght@400;600;700;800&family=Bebas+Neue:wght@400;600;700;800&family=Plus+Jakarta+Sans:wght@400;600;700;800&family=Space+Mono:wght@400;600;700;800&display=swap`
- **Geometry:**
  - Border: `2px solid #9B3721`
  - Shadow: `4px 4px 0px #14110F`
  - Radii: `sm=2px`, `md=6px`, `lg=10px`, `pill=9999px`

## 2. Pre-Commit UI Verification Checklist
- [ ] Google Fonts `<link>` for `Fraunces` & `Plus Jakarta Sans` is loaded.
- [ ] `tokens.css` variables (or `tailwind.theme.json` tokens) are imported at root.
- [ ] All interactive buttons and cards use `border: 2px solid #9B3721` and `box-shadow: 4px 4px 0px #14110F`.
- [ ] Verified Violation-Free: Do NOT use glossy corporate SaaS gradients, neon purple/cyan, or glassmorphism
- [ ] Verified Violation-Free: Do NOT use sterile pure #FFFFFF backgrounds — always use warm sandstone/adobe cream or deep earth charcoal
- [ ] Verified Violation-Free: Do NOT use generic stock-photo icons; use bold folk-art silhouettes and stamp borders
