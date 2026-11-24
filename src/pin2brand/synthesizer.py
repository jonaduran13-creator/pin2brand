"""Multimodal Visual Identity Compiler (Gemini, OpenAI, Anthropic, Ollama + Smart Visual Heuristic)."""

from __future__ import annotations

import base64
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

import httpx
from dotenv import load_dotenv

from .models import (
    BoardMathReport,
    BorderRadiusTokens,
    ColorSystem,
    ColorToken,
    ComponentGuidelines,
    ExtractedColorCluster,
    FrontendUIRules,
    GenerativeAIPrompts,
    PinColorSummary,
    PromptUseCaseTemplates,
    ReferencePin,
    ScrapedBoard,
    TypographyRule,
    TypographySystem,
    VisualIdentityManifest,
)
from .vision_math import hex_to_rgb, wcag_contrast_ratio

SYSTEM_PROMPT = """You are a Staff Design Systems Architect and Creative Director.
You are given:
1. A numbered Contact Sheet (contact_sheet.jpg) of Pinterest inspiration pins (#1..#N) with their mathematical HEX swatches.
2. High-resolution individual pins from the board to inspect fine textures, typography, photography lighting, and illustration styles.
3. The mathematical CIELAB K-Means color clusters, percentages, temperatures, texture grain score, and WCAG contrast metrics.
4. Pin titles and metadata.

Your job is to compile a cohesive, agent-ready Visual Identity Manifest (strict JSON matching the schema):
- COLOR SYSTEM: Ground your palette in the mathematical CIELAB HEX values provided! Assign them to semantic UI roles (background_primary, background_secondary, surface_card, text_primary, text_secondary, accent_primary, accent_secondary, semantic_warning, semantic_success). Ensure WCAG AA contrast (>= 4.5:1) between text and backgrounds. Define forbidden_colors that violate the board's vibe.
- TYPOGRAPHY: Infer the typography style seen in or matching the board's visual heritage, and map it to REAL, FREE Google Fonts. Provide a valid Google Fonts CSS2 URL importing all recommended families.
- FRONTEND UI RULES: Translate the visual mood into concrete CSS tokens (border_radius_tokens, border_style, exact box-shadow CSS, layout_grid_style, textures/grain/halftone effects) and explicit component_guidelines + anti_patterns so front-end coding agents avoid generic Tailwind defaults.
- GENERATIVE AI PROMPTS: Produce rich, copy-pasteable prompt prefixes, suffixes, negative prompts, Midjourney parameters, and 4 use-case templates tailored to the board's exact medium, lighting, color palette, and texture.
- REFERENCE PINS: Annotate the pins (#1..#N) with concise visual_tags and why_it_matters for agents."""

CAPTION_STOPWORDS = {
    "the", "and", "for", "with", "pin", "reference", "board", "design", "ideas",
    "de", "la", "el", "en", "para", "con", "los", "las", "del", "una", "uno",
    "logo", "branding", "style", "aesthetic", "inspiration", "photoshoot",
    "two", "three", "one", "four", "sitting", "standing", "holding", "looking",
    "top", "bottom", "table", "under", "over", "them", "their", "this", "that",
    "these", "those", "from", "into", "onto", "next", "near", "front", "back",
    "side", "view", "close", "closeup", "shot", "photo", "picture", "image",
    "showing", "shown", "seen", "made", "used", "using", "very", "some", "many",
    "more", "most", "other", "another", "each", "both", "wall", "floor", "ground",
    "room", "background", "white", "black", "blue", "red", "brown", "green",
    "yellow", "orange", "gray", "grey", "dark", "light", "small", "large", "big",
    "piece", "object", "item", "items", "objects", "set", "pair", "group",
}


def _select_diverse_sample_indices(report: BoardMathReport, limit: int = 6) -> list[int]:
    """Pick up to `limit` pin indices that maximize chromatic diversity across the board."""
    summaries = report.pin_summaries
    if len(summaries) <= limit:
        return [s.index for s in summaries]

    selected: list[int] = [summaries[0].index]
    selected_vecs = [hex_to_rgb(summaries[0].dominant_hex_colors[0])]

    while len(selected) < limit:
        best_idx = None
        best_dist = -1.0
        for s in summaries:
            if s.index in selected or not s.dominant_hex_colors:
                continue
            cand = hex_to_rgb(s.dominant_hex_colors[0])
            min_d = min(
                sum((cand[c] - sv[c]) ** 2 for c in range(3)) ** 0.5
                for sv in selected_vecs
            )
            if min_d > best_dist:
                best_dist = min_d
                best_idx = s.index
        if best_idx is None:
            break
        selected.append(best_idx)
        chosen = next(s for s in summaries if s.index == best_idx)
        selected_vecs.append(hex_to_rgb(chosen.dominant_hex_colors[0]))

    return selected


def _build_google_fonts_url(families: list[str]) -> str:
    unique: list[str] = []
    for fam in families:
        cleaned = fam.strip()
        if cleaned and cleaned not in unique:
            unique.append(cleaned)
    query = "&".join(f"family={quote_plus(f)}:wght@400;600;700;800" for f in unique)
    return f"https://fonts.googleapis.com/css2?{query}&display=swap"


def _ensure_contrast_pair(fg_hex: str, bg_hex: str, prefer_dark: bool = True) -> str:
    """Guarantee at least 4.5:1 WCAG contrast for foreground text against background."""
    fg_rgb = hex_to_rgb(fg_hex)
    bg_rgb = hex_to_rgb(bg_hex)
    if wcag_contrast_ratio(fg_rgb, bg_rgb) >= 4.5:
        return fg_hex
    fallback = "#1A1714" if prefer_dark else "#FAF7F2"
    if wcag_contrast_ratio(hex_to_rgb(fallback), bg_rgb) >= 4.5:
        return fallback
    return (
        "#000000"
        if wcag_contrast_ratio((0, 0, 0), bg_rgb) >= wcag_contrast_ratio((255, 255, 255), bg_rgb)
        else "#FFFFFF"
    )


def _cluster_to_token(
    cluster: ExtractedColorCluster,
    name: str,
    role: str,
) -> ColorToken:
    return ColorToken(
        hex=cluster.hex,
        name=name,
        role=role,
        usage_percentage=cluster.percentage,
        contrast_text_hex=cluster.best_contrast_text,
    )


def _pick_cluster(
    clusters: list[ExtractedColorCluster],
    predicate,
    fallback_idx: int,
) -> ExtractedColorCluster:
    matches = [c for c in clusters if predicate(c)]
    if matches:
        return matches[0]
    return clusters[min(fallback_idx, len(clusters) - 1)]


def _extract_smart_keywords(board: ScrapedBoard, report: BoardMathReport) -> list[str]:
    """Combine meaningful nouns from pin metadata with mathematical visual descriptors."""
    words: dict[str, int] = {}
    text_blob = " ".join([board.board_title] + [p.title + " " + p.description for p in board.pins])
    for tok in re.findall(r"[a-zA-ZáéíóúñÁÉÍÓÚÑ]{4,}", text_blob.lower()):
        if tok not in CAPTION_STOPWORDS and not tok.endswith("ing"):
            words[tok] = words.get(tok, 0) + 1
    ranked = [w for w, _ in sorted(words.items(), key=lambda kv: kv[1], reverse=True)[:4]]

    visual_descriptors: list[str] = []
    if report.earth_tone_ratio >= 25.0:
        visual_descriptors.extend(["terracotta-earth", "desert-craft"])
    if any(190.0 <= c.hue_degrees <= 255.0 and c.saturation >= 0.25 for c in report.global_clusters):
        visual_descriptors.append("cobalt-slate-contrast")
    if report.texture_grain_score >= 25.0:
        visual_descriptors.append("tactile-mineral-grain")
    elif report.surface_character == "graphic_flat":
        visual_descriptors.append("bold-screenprint")
    else:
        visual_descriptors.append("analog-warmth")

    combined: list[str] = []
    for kw in [*ranked, *visual_descriptors, report.overall_temperature, report.contrast_polarity]:
        if kw and kw not in combined:
            combined.append(kw)
    return combined[:8]


def _infer_pin_visual_tags(
    pin_title: str,
    pin_desc: str,
    summary: PinColorSummary | None,
) -> tuple[list[str], str]:
    """Generate per-pin visual tags and rationale from its color & texture math."""
    tags: list[str] = []
    blob = f"{pin_title} {pin_desc}".lower()

    if any(k in blob for k in ["wolf", "coyote", "fox", "animal", "dog"]):
        tags.append("folk-coyote-motif")
    if any(k in blob for k in ["cup", "mug", "pottery", "ceramic", "clay", "figurine"]):
        tags.append("handcrafted-ceramics")
    if any(k in blob for k in ["star", "starlight", "sky", "night", "mountain"]):
        tags.append("desert-starlight-symbolism")
    if any(k in blob for k in ["burger", "food", "bun", "sandwich", "fries"]):
        tags.append("hero-food-styling")

    if summary:
        if summary.texture_score >= 40.0:
            tags.append("raw-mineral-stone-texture")
        elif summary.texture_score >= 22.0:
            tags.append("tactile-surface-grain")
        else:
            tags.append("bold-flat-illustration")

        for hx in summary.dominant_hex_colors[:2]:
            r, g, b = hex_to_rgb(hx)
            if r > 150 and g < 110 and b < 90:
                tags.append("terracotta-red")
            elif b > r + 25 and b > 100:
                tags.append("cobalt-blue")
            elif r > 150 and g > 125 and b > 95:
                tags.append("sandstone-ochre")

    dedup_tags: list[str] = []
    for t in tags:
        if t not in dedup_tags:
            dedup_tags.append(t)
    if not dedup_tags:
        dedup_tags = ["chromatic-anchor", "brand-texture"]

    tex_note = (
        f"High tactile grain (score {summary.texture_score})"
        if summary and summary.texture_score >= 25.0
        else "Graphic form & silhouette reference"
    )
    palette_note = (
        ", ".join(summary.dominant_hex_colors) if summary and summary.dominant_hex_colors else "board palette"
    )
    rationale = f"{tex_note}; anchors {palette_note} in the visual system."
    return dedup_tags[:4], rationale


def _synthesize_heuristic(
    board: ScrapedBoard,
    report: BoardMathReport,
) -> VisualIdentityManifest:
    """Deterministic visual synthesizer grounded in CIELAB math, Laplacian texture, and metadata."""
    clusters = report.global_clusters
    light_candidates = sorted(
        [c for c in clusters if c.relative_luminance >= 0.45],
        key=lambda c: (c.relative_luminance, -c.saturation),
        reverse=True,
    )
    dark_candidates = sorted(
        [c for c in clusters if c.relative_luminance <= 0.18],
        key=lambda c: c.relative_luminance,
    )
    accent_candidates = sorted(
        [c for c in clusters if c.saturation >= 0.28 and 0.06 <= c.relative_luminance <= 0.75],
        key=lambda c: (c.saturation * 0.75 + (c.percentage / 100.0) * 0.25),
        reverse=True,
    )

    bg_light = light_candidates[0] if light_candidates else None
    bg_dark = dark_candidates[0] if dark_candidates else None

    is_dark_dominant = report.contrast_polarity == "dark_moody"
    if is_dark_dominant and bg_dark is not None:
        primary_bg_hex = bg_dark.hex
        primary_bg_pct = bg_dark.percentage
        secondary_bg_hex = bg_light.hex if bg_light else "#F4EFE6"
        secondary_bg_pct = bg_light.percentage if bg_light else 15.0
        surface_hex = "#262320"
        text_pri_hex = _ensure_contrast_pair(
            bg_light.hex if bg_light else "#F6F2EA", primary_bg_hex, prefer_dark=False
        )
        text_sec_hex = "#C4BBB0"
    else:
        primary_bg_hex = bg_light.hex if bg_light else "#F5F0E6"
        primary_bg_pct = bg_light.percentage if bg_light else 35.0
        secondary_bg_hex = bg_dark.hex if bg_dark else "#1C1917"
        secondary_bg_pct = bg_dark.percentage if bg_dark else 20.0
        surface_hex = "#FAF6EE" if primary_bg_hex.upper() != "#FAF6EE" else "#FFFFFF"
        text_pri_hex = _ensure_contrast_pair(
            bg_dark.hex if bg_dark else "#1C1917", primary_bg_hex, prefer_dark=True
        )
        text_sec_hex = "#57534E"

    accent_1 = (
        accent_candidates[0]
        if accent_candidates
        else _pick_cluster(clusters, lambda c: c.saturation > 0.2, 0)
    )
    accent_2 = (
        accent_candidates[1]
        if len(accent_candidates) > 1
        else _pick_cluster(clusters, lambda c: c.hex != accent_1.hex, 1)
    )

    blob = " ".join([board.board_title] + [p.title + " " + p.description for p in board.pins]).lower()

    # Parametric geometry derived from continuous visual metrics (saturation, grain, polarity)
    is_low_sat_minimal = report.average_saturation < 0.20 and report.texture_grain_score < 21.0
    is_high_chroma_bold = report.average_saturation >= 0.32 and report.contrast_polarity == "high_contrast"
    is_folk_desert_craft = (
        report.earth_tone_ratio >= 28.0
        and not is_low_sat_minimal
        and (
            report.texture_grain_score >= 22.0
            or any(k in blob for k in ["coyote", "wolf", "ceramic", "clay", "desert", "folk", "pottery", "starlight"])
        )
    )
    is_food_street = (
        not is_low_sat_minimal
        and any(
            k in blob for k in ["burger", "burguer", "diner", "food", "taco", "pizza", "fast food", "packaging", "retro"]
        )
    )
    is_editorial = is_low_sat_minimal or any(
        k in blob for k in ["editorial", "minimal", "serif", "luxury", "fashion", "magazine", "japanese", "nordic"]
    )

    # Continuous parametric border thickness, radius scale, and shadow offset
    border_px = 1 if is_low_sat_minimal else (3 if report.average_saturation >= 0.48 else 2)
    border_ink = accent_1.hex if (is_dark_dominant and report.earth_tone_ratio >= 25.0) else text_pri_hex
    border_style = f"{border_px}px solid {border_ink}"

    if is_low_sat_minimal:
        radii = BorderRadiusTokens(sm="0px", md="2px", lg="4px", pill="9999px")
        shadow_style = "none (crisp hairline framing & negative space)"
    elif report.surface_character == "graphic_flat" or is_high_chroma_bold:
        offset_px = 5 if report.average_saturation >= 0.42 else 4
        radii = BorderRadiusTokens(sm="2px", md="6px", lg="10px", pill="9999px")
        shadow_style = f"{offset_px}px {offset_px}px 0px {'#14110F' if is_dark_dominant else text_pri_hex}"
    elif report.contrast_polarity == "light_airy":
        radii = BorderRadiusTokens(sm="6px", md="12px", lg="18px", pill="9999px")
        shadow_style = f"0 6px 18px -4px rgba({accent_1.rgb[0]}, {accent_1.rgb[1]}, {accent_1.rgb[2]}, 0.18)"
    else:
        offset_px = 4 if report.texture_grain_score >= 24.0 else 3
        radii = BorderRadiusTokens(sm="2px", md="6px", lg="10px", pill="9999px")
        shadow_style = f"{offset_px}px {offset_px}px 0px {'#14110F' if is_dark_dominant else text_pri_hex}"

    if is_folk_desert_craft:
        archetype = (
            "Artisanal Desert Folk & Handcrafted Street-Food Identity"
            if is_food_street
            else "Artisanal Desert Folk / Terracotta & Cobalt Craft"
        )
        display_font = TypographyRule(
            family_recommended="Fraunces",
            google_fonts_fallbacks=["Alfa Slab One", "Bricolage Grotesque", "Syne"],
            weight="800",
            letter_spacing="-0.02em",
            text_transform="uppercase",
            styling_notes="Carved organic display serif with warm earthen authority and hand-printed character.",
        )
        section_font = TypographyRule(
            family_recommended="Bebas Neue",
            google_fonts_fallbacks=["Oswald", "Space Grotesk"],
            weight="400",
            letter_spacing="0.05em",
            text_transform="uppercase",
            styling_notes="Stamped woodblock-style condensed headers for sections, menu categories, and callouts.",
        )
        body_font = TypographyRule(
            family_recommended="Plus Jakarta Sans",
            google_fonts_fallbacks=["DM Sans", "Work Sans"],
            weight="500",
            letter_spacing="0em",
            text_transform="none",
            styling_notes="Warm humanoid geometric sans that remains crisp over stone, clay, and cream surfaces.",
        )
        mono_font = TypographyRule(
            family_recommended="Space Mono",
            google_fonts_fallbacks=["IBM Plex Mono"],
            weight="700",
            letter_spacing="0.05em",
            text_transform="uppercase",
            styling_notes="Craft batch stamps, coordinates, prices, and desert outpost tags.",
        )
        textures = [
            f"Raw mineral sandstone & unglazed clay texture (grain score {report.texture_grain_score})",
            f"Hand-painted terracotta ({accent_1.hex}) and cobalt ({accent_2.hex}) block-print motifs",
            "Linocut / screenprint edge irregularity and stamped badges",
        ]
        anti_patterns = [
            "Do NOT use glossy corporate SaaS gradients, neon purple/cyan, or glassmorphism",
            "Do NOT use sterile pure #FFFFFF backgrounds — always use warm sandstone/adobe cream or deep earth charcoal",
            "Do NOT use generic stock-photo icons; use bold folk-art silhouettes and stamp borders",
        ]
        style_prefix = (
            "Artisanal Southwest desert folk art direction, raw terracotta clay and cobalt pigment, "
            "hand-printed linocut & ceramic texture"
        )
        style_suffix = (
            f"anchored in {primary_bg_hex} earth, {accent_1.hex} burnt terracotta, and {accent_2.hex} cobalt slate, "
            "tactile sandstone grain, natural warm studio lighting"
        )
        neg_prompt = (
            "modern corporate SaaS UI, glossy plastic 3D render, cyberpunk neon, "
            "sterile white background, generic stock clipart"
        )
    elif is_editorial:
        archetype = (
            "Minimalist Tactile Editorial / Precision Craft"
            if is_low_sat_minimal
            else "Tactile Editorial / Contemporary Print Craft"
        )
        display_font = TypographyRule(
            family_recommended="Instrument Serif" if is_low_sat_minimal else "Fraunces",
            google_fonts_fallbacks=["Playfair Display", "Cormorant Garamond"],
            weight="400" if is_low_sat_minimal else "700",
            letter_spacing="-0.03em",
            text_transform="none",
            styling_notes="Expressive high-contrast serif with tight tracking and quiet authority.",
        )
        section_font = TypographyRule(
            family_recommended="Space Grotesk" if is_low_sat_minimal else "Syne",
            google_fonts_fallbacks=["Outfit", "DM Sans"],
            weight="600",
            letter_spacing="-0.01em",
            text_transform="none",
            styling_notes="Architectural modern display for section anchors.",
        )
        body_font = TypographyRule(
            family_recommended="DM Sans" if is_low_sat_minimal else "Inter",
            google_fonts_fallbacks=["Plus Jakarta Sans", "Work Sans"],
            weight="400",
            letter_spacing="0em",
            text_transform="none",
            styling_notes="Clean editorial body copy with generous 1.65 line-height.",
        )
        mono_font = TypographyRule(
            family_recommended="IBM Plex Mono",
            google_fonts_fallbacks=["Space Mono"],
            weight="500",
            letter_spacing="0.06em",
            text_transform="uppercase",
            styling_notes="Caption indices, specification numbers, and micro-labels.",
        )
        textures = [
            f"Matte uncoated paper surface (grain score {report.texture_grain_score})",
            "Fine editorial grid hairlines and generous negative space",
        ]
        anti_patterns = [
            "Do NOT overcrowd cards with heavy multi-color pills or cartoon shadows",
            "Do NOT use heavy slab-serifs that break the quiet editorial proportion",
        ]
        style_prefix = f"Contemporary minimalist editorial art direction, studio photography, {report.overall_temperature} tonal harmony"
        style_suffix = f"anchored by {primary_bg_hex} and {accent_1.hex}, soft directional light, tactile uncoated paper feel"
        neg_prompt = "cheap clipart, oversaturated HDR, neon glow, loud comic borders"
    elif is_food_street or (report.overall_temperature == "warm" and report.average_saturation >= 0.25):
        archetype = "Retro Street-Food Diner / Bold Analog Graphic Identity"
        display_font = TypographyRule(
            family_recommended="Alfa Slab One",
            google_fonts_fallbacks=["Fraunces", "Bebas Neue", "Anton"],
            weight="400",
            letter_spacing="-0.02em",
            text_transform="uppercase",
            styling_notes="Heavy display impact with tight leading (0.95) and crisp ink contrast.",
        )
        section_font = TypographyRule(
            family_recommended="Bebas Neue",
            google_fonts_fallbacks=["Oswald", "Anton"],
            weight="400",
            letter_spacing="0.04em",
            text_transform="uppercase",
            styling_notes="Condensed uppercase headers for menus, price callouts, and category dividers.",
        )
        body_font = TypographyRule(
            family_recommended="Plus Jakarta Sans",
            google_fonts_fallbacks=["DM Sans", "Inter"],
            weight="500",
            letter_spacing="0em",
            text_transform="none",
            styling_notes="Warm geometric sans for high legibility on textured or cream surfaces.",
        )
        mono_font = TypographyRule(
            family_recommended="Space Mono",
            google_fonts_fallbacks=["IBM Plex Mono", "JetBrains Mono"],
            weight="700",
            letter_spacing="0.05em",
            text_transform="uppercase",
            styling_notes="Receipt/ticket-style metadata, order numbers, timestamps, and badge tags.",
        )
        textures = [
            f"Subtle paper/film grain overlay (grain score {report.texture_grain_score})",
            "Halftone dot shading on hero illustrations",
            "Die-cut sticker badges and stamp seals",
        ]
        anti_patterns = [
            "Do NOT use generic purple/blue SaaS gradients or glassmorphism",
            "Do NOT use blurry soft drop shadows (use hard offset print shadows)",
            "Do NOT use sterile pure #FFFFFF/#000000 when warm cream/charcoal tokens are present",
        ]
        style_prefix = f"Analog retro street-food editorial aesthetic, bold screenprint graphic design, {report.overall_temperature} palette"
        style_suffix = f"palette of {primary_bg_hex}, {accent_1.hex}, and {accent_2.hex}, tactile paper grain, halftone print texture, crisp graphic contrast"
        neg_prompt = "generic corporate SaaS, neon cyberpunk, glossy plastic 3D render, sterile minimalist stock photo, blurry pastel gradient"
    else:
        archetype = "Neo-Graphic Visual System / Bold Tactile Brand"
        display_font = TypographyRule(
            family_recommended="Syne",
            google_fonts_fallbacks=["Bricolage Grotesque", "Space Grotesk"],
            weight="800",
            letter_spacing="-0.03em",
            text_transform="none",
            styling_notes="Bold geometric display headings with strong scale contrast against body.",
        )
        section_font = TypographyRule(
            family_recommended="Space Grotesk",
            google_fonts_fallbacks=["Outfit", "DM Sans"],
            weight="700",
            letter_spacing="-0.01em",
            text_transform="none",
            styling_notes="Structured section headers.",
        )
        body_font = TypographyRule(
            family_recommended="Plus Jakarta Sans",
            google_fonts_fallbacks=["Inter", "DM Sans"],
            weight="400",
            letter_spacing="0em",
            text_transform="none",
            styling_notes="Balanced contemporary sans-serif for UI copy.",
        )
        mono_font = TypographyRule(
            family_recommended="JetBrains Mono",
            google_fonts_fallbacks=["Space Mono"],
            weight="500",
            letter_spacing="0.04em",
            text_transform="uppercase",
            styling_notes="Technical metadata badges and micro-labels.",
        )
        textures = [f"Subtle surface grain (score {report.texture_grain_score})", "High-contrast surface layering"]
        anti_patterns = [
            "Do NOT fall back to default Tailwind indigo/slate SaaS templates",
            "Do NOT ignore the extracted accent hierarchy",
        ]
        style_prefix = f"Cohesive graphic brand identity, bold art direction, {report.overall_temperature} color palette"
        style_suffix = f"featuring {accent_1.hex} and {accent_2.hex} accents over {primary_bg_hex}, tactile print finish"
        neg_prompt = "generic stock template, muddy colors, low contrast, watermark"

    fonts_url = _build_google_fonts_url(
        [
            display_font.family_recommended,
            section_font.family_recommended,
            body_font.family_recommended,
            mono_font.family_recommended,
        ]
    )

    keywords = _extract_smart_keywords(board, report)

    color_system = ColorSystem(
        background_primary=ColorToken(
            hex=primary_bg_hex,
            name="Primary Canvas",
            role="Main page background and negative space",
            usage_percentage=round(primary_bg_pct, 2),
            contrast_text_hex=_ensure_contrast_pair(text_pri_hex, primary_bg_hex, not is_dark_dominant),
        ),
        background_secondary=ColorToken(
            hex=secondary_bg_hex,
            name="Contrast Band Canvas",
            role="High-contrast dark/inverted bands, footers, and feature callouts",
            usage_percentage=round(secondary_bg_pct, 2),
            contrast_text_hex=_ensure_contrast_pair(
                primary_bg_hex if not is_dark_dominant else text_pri_hex,
                secondary_bg_hex,
                is_dark_dominant,
            ),
        ),
        surface_card=ColorToken(
            hex=surface_hex,
            name="Elevated Surface",
            role="Cards, menu tiles, and interactive containers",
            usage_percentage=15.0,
            contrast_text_hex=_ensure_contrast_pair(text_pri_hex, surface_hex, not is_dark_dominant),
        ),
        text_primary=ColorToken(
            hex=text_pri_hex,
            name="Primary Ink",
            role="Headings, body copy, and crisp borders",
            usage_percentage=12.0,
            contrast_text_hex=primary_bg_hex,
        ),
        text_secondary=ColorToken(
            hex=text_sec_hex,
            name="Secondary Ink",
            role="Captions, metadata, and subdued labels",
            usage_percentage=6.0,
            contrast_text_hex=primary_bg_hex,
        ),
        accent_primary=_cluster_to_token(
            accent_1, "Hero Accent", "Primary CTAs, key brand marks, and focal highlights"
        ),
        accent_secondary=_cluster_to_token(
            accent_2, "Supporting Accent", "Badges, secondary tags, stickers, and hover states"
        ),
        semantic_warning=ColorToken(
            hex="#D97706",
            name="Warm Amber Alert",
            role="Warnings and limited-time callouts",
            usage_percentage=1.0,
            contrast_text_hex="#FFFFFF",
        ),
        semantic_success=ColorToken(
            hex="#15803D",
            name="Verified Green",
            role="Confirmations and active status tags",
            usage_percentage=1.0,
            contrast_text_hex="#FFFFFF",
        ),
        color_harmony_notes=(
            f"Mathematically derived via CIELAB K-Means across {len(board.pins)} pins. "
            f"Overall temperature is {report.overall_temperature} with {report.contrast_polarity} polarity, "
            f"earth-tone share {report.earth_tone_ratio}%, and texture grain score {report.texture_grain_score}."
        ),
        forbidden_colors=[
            "Generic SaaS indigo/violet (#6366F1, #8B5CF6)",
            "Unrelated neon cyan (#00FFFF) unless explicitly in accent tokens",
        ],
    )

    ui_rules = FrontendUIRules(
        aesthetic_archetype=archetype,
        border_radius_tokens=radii,
        border_style=border_style,
        shadow_style=shadow_style,
        layout_grid_style="Asymmetric editorial bento grid with bold bordered containers and tactile surface contrast.",
        texture_and_effects=textures,
        component_guidelines=ComponentGuidelines(
            buttons=f"Solid {accent_1.hex} fill with {accent_1.best_contrast_text} bold uppercase label, {border_style}, {shadow_style}; shift -2px/-2px on hover.",
            cards=f"Use {surface_hex} surface with {border_style}, radius {radii.md}, and {shadow_style}.",
            navigation=f"Sticky top bar on {primary_bg_hex} with bottom {border_style}, high-contrast brand mark on left and single bold CTA on right.",
            hero_section=f"Split or full-bleed showcase pairing display font ({display_font.family_recommended}) with high-res reference imagery and stamp badge.",
            badges=f"Pill ({radii.pill}) or sharp stamp tags in {accent_2.hex} with {accent_2.best_contrast_text} monospace text ({mono_font.family_recommended}).",
        ),
        anti_patterns=anti_patterns,
    )

    prompts = GenerativeAIPrompts(
        global_style_prefix=style_prefix,
        global_style_suffix=style_suffix,
        negative_prompt=neg_prompt,
        midjourney_parameters="--v 6.1 --stylize 250 --ar 4:5",
        use_case_templates=PromptUseCaseTemplates(
            hero_photography=f"{style_prefix}, signature hero shot on raw sandstone & handcrafted ceramic tableware, warm directional lighting, {style_suffix}",
            brand_mascot_illustration=f"{style_prefix}, folk-art mascot illustration, bold block-print terracotta and cobalt linework, distressed ink stamp feel, {style_suffix}",
            seamless_background_texture=f"Seamless tileable surface texture, raw adobe sandstone and unglazed terracotta clay grain in {primary_bg_hex} and {accent_1.hex}, macro top-down",
            ui_icon_sticker=f"Hand-stamped woodblock badge icon, thick {text_pri_hex} ink outline, {accent_1.hex} terracotta and {accent_2.hex} cobalt spot colors, isolated",
        ),
    )

    summary_map = {s.pin_id: s for s in report.pin_summaries}
    ref_pins: list[ReferencePin] = []
    for p in board.pins:
        p_sum = summary_map.get(p.pin_id)
        v_tags, rationale = _infer_pin_visual_tags(p.title, p.description, p_sum)
        rel_path = f"references/{Path(p.local_path).name}" if p.local_path else ""
        ref_pins.append(
            ReferencePin(
                id=p.pin_id,
                title=p.title,
                source_url=p.pin_url,
                local_path=rel_path,
                dominant_hex_colors=p_sum.dominant_hex_colors if p_sum else [],
                visual_tags=v_tags,
                why_it_matters=f"Pin #{p.index}: {rationale}",
            )
        )

    return VisualIdentityManifest(
        project_name=board.board_title,
        board_url=board.canonical_url,
        generated_at=datetime.now(timezone.utc).isoformat(),
        brand_essence_summary=(
            f"Visual identity compiled from {len(board.pins)} references in '{board.board_title}'. "
            f"Defined by {archetype.lower()}, {report.surface_character} surfaces (grain {report.texture_grain_score}), "
            f"and a {report.overall_temperature} CIELAB palette ({report.earth_tone_ratio}% earth tones)."
        ),
        mood_keywords=keywords,
        color_system=color_system,
        typography=TypographySystem(
            display_heading=display_font,
            section_heading=section_font,
            body_copy=body_font,
            monospace_accent=mono_font,
            google_fonts_import_url=fonts_url,
        ),
        frontend_ui_rules=ui_rules,
        generative_ai_prompts=prompts,
        reference_pins=ref_pins,
    )


def _build_llm_user_prompt(board: ScrapedBoard, report: BoardMathReport) -> str:
    cluster_lines = "\n".join(
        f"- {c.hex}: {c.percentage}% | role={c.suggested_role} | temp={c.temperature} | "
        f"lum={c.relative_luminance} | sat={c.saturation} | best_text={c.best_contrast_text} (WCAG {c.contrast_ratio_on_best}:1)"
        for c in report.global_clusters
    )
    pin_lines = "\n".join(
        f"- Pin #{p.index} (id={p.pin_id}): title='{p.title}' | desc='{p.description[:120]}' | local_path='{p.local_path}' | source_url='{p.pin_url}'"
        for p in board.pins
    )
    return (
        f"Board Title: {board.board_title}\n"
        f"Board URL: {board.canonical_url}\n"
        f"Generated Timestamp: {datetime.now(timezone.utc).isoformat()}\n"
        f"Overall Mathematical Temp: {report.overall_temperature} | Polarity: {report.contrast_polarity} | "
        f"Avg Sat: {report.average_saturation} | Texture Grain Score: {report.texture_grain_score} ({report.surface_character}) | "
        f"Earth-Tone Ratio: {report.earth_tone_ratio}%\n\n"
        f"Mathematical CIELAB Global Color Clusters:\n{cluster_lines}\n\n"
        f"Scraped Reference Pins ({len(board.pins)} total):\n{pin_lines}\n\n"
        "Analyze the contact sheet and individual high-res pins carefully and output the complete VisualIdentityManifest JSON."
    )


def _reconcile_manifest_pins(
    manifest: VisualIdentityManifest,
    board: ScrapedBoard,
    report: BoardMathReport,
) -> VisualIdentityManifest:
    summary_map = {s.pin_id: s for s in report.pin_summaries}
    llm_pin_map = {rp.id: rp for rp in manifest.reference_pins}
    reconciled_pins: list[ReferencePin] = []
    for p in board.pins:
        llm_rp = llm_pin_map.get(p.pin_id)
        p_sum = summary_map.get(p.pin_id)
        fallback_tags, fallback_why = _infer_pin_visual_tags(p.title, p.description, p_sum)
        rel_path = f"references/{Path(p.local_path).name}" if p.local_path else ""
        reconciled_pins.append(
            ReferencePin(
                id=p.pin_id,
                title=llm_rp.title if llm_rp and llm_rp.title else p.title,
                source_url=p.pin_url,
                local_path=rel_path,
                dominant_hex_colors=(
                    p_sum.dominant_hex_colors
                    if p_sum
                    else (llm_rp.dominant_hex_colors if llm_rp else [])
                ),
                visual_tags=llm_rp.visual_tags if llm_rp and llm_rp.visual_tags else fallback_tags,
                why_it_matters=(
                    llm_rp.why_it_matters
                    if llm_rp and llm_rp.why_it_matters
                    else f"Pin #{p.index}: {fallback_why}"
                ),
            )
        )
    manifest.reference_pins = reconciled_pins
    manifest.board_url = board.canonical_url
    return manifest


def _synthesize_with_gemini(
    board: ScrapedBoard,
    report: BoardMathReport,
    model_name: str,
    api_key: str,
) -> VisualIdentityManifest:
    """Invoke Gemini Vision with contact_sheet + 6 diverse images and strict Pydantic schema."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    contents: list[object] = []

    cs_path = Path(report.contact_sheet_path)
    if cs_path.exists():
        contents.append(
            types.Part.from_bytes(data=cs_path.read_bytes(), mime_type="image/jpeg")
        )

    sample_indices = set(_select_diverse_sample_indices(report, limit=6))
    for pin in board.pins:
        if pin.index in sample_indices and pin.local_path and Path(pin.local_path).exists():
            contents.append(
                types.Part.from_bytes(
                    data=Path(pin.local_path).read_bytes(), mime_type="image/jpeg"
                )
            )

    contents.append(_build_llm_user_prompt(board, report))

    response = client.models.generate_content(
        model=model_name,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=VisualIdentityManifest,
            temperature=0.35,
        ),
    )

    if response.parsed is not None and isinstance(response.parsed, VisualIdentityManifest):
        manifest = response.parsed
    else:
        manifest = VisualIdentityManifest.model_validate_json(response.text)

    return _reconcile_manifest_pins(manifest, board, report)


def _synthesize_with_openai(
    board: ScrapedBoard,
    report: BoardMathReport,
    model_name: str,
    api_key: str,
) -> VisualIdentityManifest:
    """Invoke OpenAI Vision API (e.g. gpt-4o / gpt-4.1-mini) via httpx."""
    cs_b64 = base64.b64encode(Path(report.contact_sheet_path).read_bytes()).decode("ascii")
    schema_json = json.dumps(VisualIdentityManifest.model_json_schema(), indent=2)
    prompt = (
        f"{_build_llm_user_prompt(board, report)}\n\n"
        f"Return ONLY valid JSON conforming strictly to this JSON Schema:\n{schema_json}"
    )
    resp = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model_name,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{cs_b64}"},
                        },
                    ],
                },
            ],
            "temperature": 0.3,
        },
        timeout=60.0,
    )
    resp.raise_for_status()
    raw_content = resp.json()["choices"][0]["message"]["content"]
    manifest = VisualIdentityManifest.model_validate_json(raw_content)
    return _reconcile_manifest_pins(manifest, board, report)


def _synthesize_with_ollama(
    board: ScrapedBoard,
    report: BoardMathReport,
    model_name: str,
) -> VisualIdentityManifest:
    """Invoke a local Ollama vision model (e.g. qwen2.5-vl or llama3.2-vision)."""
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    cs_b64 = base64.b64encode(Path(report.contact_sheet_path).read_bytes()).decode("ascii")
    prompt = _build_llm_user_prompt(board, report)
    resp = httpx.post(
        f"{host}/api/chat",
        json={
            "model": model_name,
            "stream": False,
            "format": VisualIdentityManifest.model_json_schema(),
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt, "images": [cs_b64]},
            ],
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    raw_content = resp.json()["message"]["content"]
    manifest = VisualIdentityManifest.model_validate_json(raw_content)
    return _reconcile_manifest_pins(manifest, board, report)


def synthesize_identity(
    board: ScrapedBoard,
    report: BoardMathReport,
    model_name: str = "gemini-2.5-flash",
    force_offline: bool = False,
    provider: str = "auto",
) -> tuple[VisualIdentityManifest, str]:
    """Synthesize VisualIdentityManifest via Gemini, OpenAI, Ollama, or deterministic visual fallback."""
    load_dotenv()
    if force_offline or provider == "offline":
        return _synthesize_heuristic(board, report), "heuristic_offline"

    gemini_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()

    chosen = provider.lower().strip()
    if chosen == "auto":
        if gemini_key:
            chosen = "gemini"
        elif openai_key:
            chosen = "openai"
        else:
            return _synthesize_heuristic(board, report), "heuristic_no_api_key"

    try:
        if chosen == "gemini":
            if not gemini_key:
                raise RuntimeError("GEMINI_API_KEY not set")
            return _synthesize_with_gemini(board, report, model_name, gemini_key), f"gemini_vision:{model_name}"
        if chosen == "openai":
            if not openai_key:
                raise RuntimeError("OPENAI_API_KEY not set")
            oa_model = model_name if not model_name.startswith("gemini") else "gpt-4o"
            return _synthesize_with_openai(board, report, oa_model, openai_key), f"openai_vision:{oa_model}"
        if chosen == "ollama":
            ol_model = model_name if not model_name.startswith("gemini") else "llama3.2-vision"
            return _synthesize_with_ollama(board, report, ol_model), f"ollama_vision:{ol_model}"
    except Exception as exc:
        manifest = _synthesize_heuristic(board, report)
        manifest.brand_essence_summary += f" (Fallback note: {chosen} unavailable: {exc})"
        return manifest, f"heuristic_fallback({type(exc).__name__})"

    return _synthesize_heuristic(board, report), "heuristic_no_api_key"
