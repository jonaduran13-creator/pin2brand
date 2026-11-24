---
name: coyote-burguer-visual-identity
description: Apply and audit the COYOTE BURGUER visual identity (Artisanal Desert Folk & Handcrafted Street-Food Identity) across front-end interfaces and generative AI prompts.
---

# Skill Workflow: `coyote-burguer-visual-identity`

Use this skill whenever building UI screens, brand assets, or image prompts for **COYOTE BURGUER**.

## Step 1: Wire Design Tokens First
1. Import `tokens.css` (or merge `tailwind.theme.json` / `tokens.w3c.json`) into the project stylesheet before writing components.
2. Inject the Google Fonts stylesheet into the document `<head>`:
   `https://fonts.googleapis.com/css2?family=Fraunces:wght@400;600;700;800&family=Bebas+Neue:wght@400;600;700;800&family=Plus+Jakarta+Sans:wght@400;600;700;800&family=Space+Mono:wght@400;600;700;800&display=swap`

## Step 2: Apply Archetype & Component Geometry
- **Archetype:** Artisanal Desert Folk & Handcrafted Street-Food Identity
- **Layout Grid:** Asymmetric editorial bento grid with bold bordered containers and tactile surface contrast.
- **Buttons:** Solid #B13B29 fill with #FAF8F5 bold uppercase label, 2px solid #B13B29, 4px 4px 0px #14110F; shift -2px/-2px on hover.
- **Cards:** Use #262320 surface with 2px solid #B13B29, radius 6px, and 4px 4px 0px #14110F.
- **Navigation:** Sticky top bar on #342A2A with bottom 2px solid #B13B29, high-contrast brand mark on left and single bold CTA on right.
- **Hero Section:** Split or full-bleed showcase pairing display font (Fraunces) with high-res reference imagery and stamp badge.
- **Badges:** Pill (9999px) or sharp stamp tags in #6896D8 with #141210 monospace text (Space Mono).

## Step 3: Generate Cohesive Visual Assets
When invoking an image generator (Midjourney, Flux, Imagen / Nano Banana), always wrap subject prompts with:
- **Prefix:** `Artisanal Southwest desert folk art direction, raw terracotta clay and cobalt pigment, hand-printed linocut & ceramic texture`
- **Suffix:** `anchored in #342A2A earth, #B13B29 burnt terracotta, and #6896D8 cobalt slate, tactile sandstone grain, natural warm studio lighting`
- **Negative Prompt:** `modern corporate SaaS UI, glossy plastic 3D render, cyberpunk neon, sterile white background, generic stock clipart`
- **Style Reference Images (`--sref`):** Use `contact_sheet.jpg` or `references/pin_01.jpg`.

## Step 4: Final Visual Audit
Before completing any UI task, verify:
1. Contrast matches WCAG AA (`#C4B5A6` on `#342A2A`).
2. Surface textures (`Raw mineral sandstone & unglazed clay texture (grain score 28.49); Hand-painted terracotta (#B13B29) and cobalt (#6896D8) block-print motifs; Linocut / screenprint edge irregularity and stamped badges`) are represented.
3. None of the forbidden patterns appear (`Do NOT use glossy corporate SaaS gradients, neon purple/cyan, or glassmorphism; Do NOT use sterile pure #FFFFFF backgrounds — always use warm sandstone/adobe cream or deep earth charcoal; Do NOT use generic stock-photo icons; use bold folk-art silhouettes and stamp borders`).