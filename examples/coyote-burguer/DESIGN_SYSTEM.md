# DESIGN SYSTEM & AGENT VISUAL RULES: COYOTE BURGUER

> **Agent Instruction:** Read and enforce EVERY rule in this document before writing any HTML, CSS, React, or Tailwind code for this project. Do not fall back to generic SaaS defaults.

- **Aesthetic Archetype:** Artisanal Desert Folk & Handcrafted Street-Food Identity
- **Source Pinterest Board:** https://mx.pinterest.com/jonathanduransandoval/coyote-burguer/
- **Mood Keywords:** wolf, starlight, graphicdesign, coyote, terracotta-earth, desert-craft, cobalt-slate-contrast, tactile-mineral-grain
- **Summary:** Visual identity compiled from 5 references in 'COYOTE BURGUER'. Defined by artisanal desert folk & handcrafted street-food identity, tactile_organic surfaces (grain 28.49), and a warm CIELAB palette (53.32% earth tones).

---

## 1. Google Fonts Import (`<head>`)

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:wght@400;600;700;800&family=Bebas+Neue:wght@400;600;700;800&family=Plus+Jakarta+Sans:wght@400;600;700;800&family=Space+Mono:wght@400;600;700;800&display=swap" rel="stylesheet">
```

---

## 2. Color Tokens & Tailwind Mapping

| Semantic Role | HEX | CSS Variable | Suggested Tailwind Utility | Recommended Contrast Ink | Usage / Role |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Background Primary** | `#342A2A` | `--brand-bg-primary` | `bg-[#342A2A]` | `#F6F2EA` | Main page background and negative space |
| **Background Secondary** | `#C4B5A6` | `--brand-bg-secondary` | `bg-[#C4B5A6]` | `#141210` | High-contrast dark/inverted bands, footers, and feature callouts |
| **Surface Card** | `#262320` | `--brand-surface-card` | `bg-[#262320]` | `#F6F2EA` | Cards, menu tiles, and interactive containers |
| **Text Primary** | `#F6F2EA` | `--brand-text-primary` | `text-[#F6F2EA]` | `#342A2A` | Headings, body copy, and crisp borders |
| **Text Secondary** | `#C4B5A6` | `--brand-text-secondary` | `text-[#C4B5A6]` | `#342A2A` | Captions, metadata, and subdued labels |
| **Accent Primary** | `#B13B29` | `--brand-accent-primary` | `bg-[#B13B29]` | `#FAF8F5` | Primary CTAs, key brand marks, and focal highlights |
| **Accent Secondary** | `#6896D8` | `--brand-accent-secondary` | `bg-[#6896D8]` | `#141210` | Badges, secondary tags, stickers, and hover states |

**Harmony Notes:** Mathematically derived via CIELAB K-Means across 5 pins. Overall temperature is warm with dark_moody polarity, earth-tone share 53.32%, and texture grain score 28.49.

**Forbidden Colors:**
- Generic SaaS indigo/violet (#6366F1, #8B5CF6)
- Unrelated neon cyan (#00FFFF) unless explicitly in accent tokens


---

## 3. Typography Hierarchy

| Tier | Primary Font | Fallbacks | Weight | Tracking | Transform | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Display Hero** | `Fraunces` | Alfa Slab One, Bricolage Grotesque, Syne | `800` | `-0.02em` | `uppercase` | Carved organic display serif with warm earthen authority and hand-printed character. |
| **Section Heading** | `Bebas Neue` | Oswald, Space Grotesk | `400` | `0.05em` | `uppercase` | Stamped woodblock-style condensed headers for sections, menu categories, and callouts. |
| **Body Copy** | `Plus Jakarta Sans` | DM Sans, Work Sans | `500` | `0em` | `none` | Warm humanoid geometric sans that remains crisp over stone, clay, and cream surfaces. |
| **Monospace Accent** | `Space Mono` | IBM Plex Mono | `700` | `0.05em` | `uppercase` | Craft batch stamps, coordinates, prices, and desert outpost tags. |

---

## 4. Surface, Geometry & Component Rules

- **Border Style:** `2px solid #B13B29`
- **Shadow Style:** `4px 4px 0px #14110F`
- **Radii:** `sm=2px`, `md=6px`, `lg=10px`, `pill=9999px`
- **Layout Grid:** Asymmetric editorial bento grid with bold bordered containers and tactile surface contrast.

**Textures & Effects:**
- Raw mineral sandstone & unglazed clay texture (grain score 28.49)
- Hand-painted terracotta (#B13B29) and cobalt (#6896D8) block-print motifs
- Linocut / screenprint edge irregularity and stamped badges


### Component Specs
- **Buttons:** Solid #B13B29 fill with #FAF8F5 bold uppercase label, 2px solid #B13B29, 4px 4px 0px #14110F; shift -2px/-2px on hover.
- **Cards:** Use #262320 surface with 2px solid #B13B29, radius 6px, and 4px 4px 0px #14110F.
- **Navigation:** Sticky top bar on #342A2A with bottom 2px solid #B13B29, high-contrast brand mark on left and single bold CTA on right.
- **Hero Section:** Split or full-bleed showcase pairing display font (Fraunces) with high-res reference imagery and stamp badge.
- **Badges:** Pill (9999px) or sharp stamp tags in #6896D8 with #141210 monospace text (Space Mono).

---

## 5. PROHIBIDO (Agent Anti-Patterns)

- **NEVER:** Do NOT use glossy corporate SaaS gradients, neon purple/cyan, or glassmorphism
- **NEVER:** Do NOT use sterile pure #FFFFFF backgrounds — always use warm sandstone/adobe cream or deep earth charcoal
- **NEVER:** Do NOT use generic stock-photo icons; use bold folk-art silhouettes and stamp borders


---

## 6. Visual References & Image Prompts

- **Contact Sheet:** `contact_sheet.jpg`
- **Generative Style Prefix:** `Artisanal Southwest desert folk art direction, raw terracotta clay and cobalt pigment, hand-printed linocut & ceramic texture`
- **Generative Style Suffix:** `anchored in #342A2A earth, #B13B29 burnt terracotta, and #6896D8 cobalt slate, tactile sandstone grain, natural warm studio lighting`
- **Negative Prompt:** `modern corporate SaaS UI, glossy plastic 3D render, cyberpunk neon, sterile white background, generic stock clipart`