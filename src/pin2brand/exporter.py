"""Multi-agent artifact exporter (JSON, DESIGN_SYSTEM.md, AGENTS.md, Cursor .mdc, SKILL.md, W3C tokens, CSS, Tailwind, Prompts, HTML Preview)."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .models import VisualIdentityManifest

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _parse_css_shadow_to_w3c(shadow_str: str, fallback_color: str) -> dict[str, str]:
    """Convert a CSS box-shadow string into a W3C DTCG §9.6 structured shadow value object."""
    raw = shadow_str.strip()
    if not raw or raw.lower().startswith("none"):
        return {
            "color": "#00000000",
            "offsetX": "0px",
            "offsetY": "0px",
            "blur": "0px",
            "spread": "0px",
        }

    # Extract color token (hex or rgba/rgb)
    color_match = re.search(r"(#[0-9a-fA-F]{3,8}|rgba?\([^)]+\))", raw)
    color_val = color_match.group(1) if color_match else fallback_color
    without_color = raw.replace(color_val, "").strip() if color_match else raw

    lengths = re.findall(r"-?\d+(?:\.\d+)?(?:px|rem|em)?", without_color)
    norm_lengths = [
        (val if val.endswith(("px", "rem", "em")) else f"{val}px")
        for val in lengths
    ]
    offset_x = norm_lengths[0] if len(norm_lengths) >= 1 else "0px"
    offset_y = norm_lengths[1] if len(norm_lengths) >= 2 else "4px"
    blur = norm_lengths[2] if len(norm_lengths) >= 3 else "0px"
    spread = norm_lengths[3] if len(norm_lengths) >= 4 else "0px"

    return {
        "color": color_val,
        "offsetX": offset_x,
        "offsetY": offset_y,
        "blur": blur,
        "spread": spread,
    }


def _build_w3c_design_tokens(manifest: VisualIdentityManifest) -> dict:
    """Build W3C Design Tokens Community Group (DTCG) format JSON for Figma Tokens Studio & Style Dictionary."""
    cs = manifest.color_system
    ty = manifest.typography
    ui = manifest.frontend_ui_rules
    return {
        "$schema": "https://tr.designtokens.org/format/",
        "brand": {
            "meta": {
                "project": {"$value": manifest.project_name, "$type": "other"},
                "archetype": {"$value": ui.aesthetic_archetype, "$type": "other"},
                "source": {"$value": manifest.board_url, "$type": "other"},
            },
            "color": {
                "background": {
                    "primary": {"$value": cs.background_primary.hex, "$type": "color", "$description": cs.background_primary.role},
                    "secondary": {"$value": cs.background_secondary.hex, "$type": "color", "$description": cs.background_secondary.role},
                    "surface": {"$value": cs.surface_card.hex, "$type": "color", "$description": cs.surface_card.role},
                },
                "text": {
                    "primary": {"$value": cs.text_primary.hex, "$type": "color", "$description": cs.text_primary.role},
                    "secondary": {"$value": cs.text_secondary.hex, "$type": "color", "$description": cs.text_secondary.role},
                },
                "accent": {
                    "primary": {"$value": cs.accent_primary.hex, "$type": "color", "$description": cs.accent_primary.role},
                    "secondary": {"$value": cs.accent_secondary.hex, "$type": "color", "$description": cs.accent_secondary.role},
                },
                "semantic": {
                    "warning": {"$value": cs.semantic_warning.hex, "$type": "color"},
                    "success": {"$value": cs.semantic_success.hex, "$type": "color"},
                },
            },
            "typography": {
                "display": {
                    "fontFamily": {"$value": ty.display_heading.family_recommended, "$type": "fontFamily"},
                    "fontWeight": {"$value": ty.display_heading.weight, "$type": "fontWeight"},
                },
                "heading": {
                    "fontFamily": {"$value": ty.section_heading.family_recommended, "$type": "fontFamily"},
                    "fontWeight": {"$value": ty.section_heading.weight, "$type": "fontWeight"},
                },
                "body": {
                    "fontFamily": {"$value": ty.body_copy.family_recommended, "$type": "fontFamily"},
                    "fontWeight": {"$value": ty.body_copy.weight, "$type": "fontWeight"},
                },
                "mono": {
                    "fontFamily": {"$value": ty.monospace_accent.family_recommended, "$type": "fontFamily"},
                    "fontWeight": {"$value": ty.monospace_accent.weight, "$type": "fontWeight"},
                },
            },
            "radius": {
                "sm": {"$value": ui.border_radius_tokens.sm, "$type": "dimension"},
                "md": {"$value": ui.border_radius_tokens.md, "$type": "dimension"},
                "lg": {"$value": ui.border_radius_tokens.lg, "$type": "dimension"},
                "pill": {"$value": ui.border_radius_tokens.pill, "$type": "dimension"},
            },
            "border": {
                "default": {"$value": ui.border_style, "$type": "other"},
            },
            "shadow": {
                "default": {
                    "$value": _parse_css_shadow_to_w3c(ui.shadow_style, cs.text_primary.hex),
                    "$type": "shadow",
                    "$description": f"CSS box-shadow: {ui.shadow_style}",
                },
            },
        },
    }


def _build_simulator_copy(manifest: VisualIdentityManifest) -> dict:
    """Derive placeholder storefront/app/poster copy for the Studio simulator from the board itself.

    Nothing here is brand-specific: names, taglines and tags come from mood keywords,
    the archetype label and each reference pin's visual tags.
    """
    generic = {"warm", "cool", "neutral", "balanced", "high_contrast", "dark_moody", "light_airy"}
    kws = [k.replace("-", " ").replace("_", " ").strip() for k in manifest.mood_keywords]
    kws = [k for k in kws if k and k.replace(" ", "_") not in generic] or ["signature", "craft", "collection"]
    while len(kws) < 3:
        kws.append(kws[-1])

    pins = manifest.reference_pins
    items = []
    for i in range(3):
        pin = pins[i] if i < len(pins) else (pins[-1] if pins else None)
        tags = ", ".join(pin.visual_tags[:3]) if pin and pin.visual_tags else kws[i]
        items.append(
            {
                "tag": f"Selección #{i + 1:02d}",
                "name": f"{kws[i].upper()} SIGNATURE",
                "desc": f"Pieza de ejemplo inspirada en el Pin #{pin.id[-4:] if pin else i + 1}: {tags}.",
                "price": "$00.00",
            }
        )

    first_pin = pins[0] if pins else None
    return {
        "nav": ["COLECCIÓN", "HISTORIA", "CONTACTO"],
        "nav_cta": "EXPLORAR",
        "hero_pill": " • ".join(k.upper() for k in kws[:3]),
        "hero_title": manifest.project_name.upper(),
        "hero_copy": manifest.brand_essence_summary,
        "hero_cta": "Ver colección",
        "products": items,
        "item_cta": "Agregar",
        "checkout_cta": "Confirmar pedido",
        "order_id": "ORDEN #001",
        "loyalty_title": f"CLUB {manifest.project_name.upper()}",
        "loyalty_hint": "¡Completa tu colección para desbloquear la edición limitada!",
        "poster_tagline": " • ".join(k.upper() for k in kws[:3]),
        "ticket_sub": manifest.frontend_ui_rules.aesthetic_archetype.upper(),
        "motif_pin": "#1",
        "motif_tags": ", ".join(first_pin.visual_tags[:2]) if first_pin and first_pin.visual_tags else kws[0],
    }


def export_brand_kit(
    manifest: VisualIdentityManifest,
    output_dir: Path,
    contact_sheet_path: Path | None = None,
) -> dict[str, Path]:
    """Export all Pin2Brand multi-agent artifacts into `output_dir` and return their paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=False)
    html_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)

    # 1. visual-identity.json
    json_path = output_dir / "visual-identity.json"
    manifest_json_str = manifest.model_dump_json(indent=2)
    json_path.write_text(manifest_json_str, encoding="utf-8")

    # 2. DESIGN_SYSTEM.md (Full human + architect specification)
    design_tpl = env.get_template("DESIGN_SYSTEM.md.j2")
    design_md_content = design_tpl.render(manifest=manifest)
    design_md_path = output_dir / "DESIGN_SYSTEM.md"
    design_md_path.write_text(design_md_content, encoding="utf-8")

    # 3. AGENTS.md (Compact root directive & pre-commit checklist for coding agents)
    agents_tpl = env.get_template("AGENTS.md.j2")
    agents_md_content = agents_tpl.render(manifest=manifest)
    agents_md_path = output_dir / "AGENTS.md"
    agents_md_path.write_text(agents_md_content, encoding="utf-8")

    # 4. cursor-visual-identity.mdc (Cursor IDE rule with concrete JSX/TSX blueprints)
    cursor_tpl = env.get_template("cursor_rules.mdc.j2")
    cursor_mdc_content = cursor_tpl.render(manifest=manifest)
    cursor_mdc_path = output_dir / "cursor-visual-identity.mdc"
    cursor_mdc_path.write_text(cursor_mdc_content, encoding="utf-8")

    # 5. SKILL.md (4-step executable agent skill workflow)
    slug = re.sub(r"[^a-z0-9-]+", "-", manifest.project_name.lower()).strip("-") or "brand"
    skill_tpl = env.get_template("SKILL.md.j2")
    skill_md_content = skill_tpl.render(manifest=manifest, slug=slug)
    skill_md_path = output_dir / "SKILL.md"
    skill_md_path.write_text(skill_md_content, encoding="utf-8")

    # 6. tokens.w3c.json (W3C Design Tokens for Figma & Style Dictionary)
    w3c_json_str = json.dumps(_build_w3c_design_tokens(manifest), indent=2)
    w3c_path = output_dir / "tokens.w3c.json"
    w3c_path.write_text(w3c_json_str, encoding="utf-8")

    # 7. tokens.css & tailwind.theme.json
    css_tpl = env.get_template("tokens.css.j2")
    tokens_css = css_tpl.render(manifest=manifest)
    tokens_css_path = output_dir / "tokens.css"
    tokens_css_path.write_text(tokens_css, encoding="utf-8")

    tailwind_theme = {
        "colors": {
            "brand": {
                "bg-primary": manifest.color_system.background_primary.hex,
                "bg-secondary": manifest.color_system.background_secondary.hex,
                "surface": manifest.color_system.surface_card.hex,
                "text-primary": manifest.color_system.text_primary.hex,
                "text-secondary": manifest.color_system.text_secondary.hex,
                "accent-primary": manifest.color_system.accent_primary.hex,
                "accent-secondary": manifest.color_system.accent_secondary.hex,
                "warning": manifest.color_system.semantic_warning.hex,
                "success": manifest.color_system.semantic_success.hex,
            }
        },
        "fontFamily": {
            "display": [
                manifest.typography.display_heading.family_recommended,
                *manifest.typography.display_heading.google_fonts_fallbacks,
            ],
            "heading": [
                manifest.typography.section_heading.family_recommended,
                *manifest.typography.section_heading.google_fonts_fallbacks,
            ],
            "sans": [
                manifest.typography.body_copy.family_recommended,
                *manifest.typography.body_copy.google_fonts_fallbacks,
            ],
            "mono": [
                manifest.typography.monospace_accent.family_recommended,
                *manifest.typography.monospace_accent.google_fonts_fallbacks,
            ],
        },
        "borderRadius": manifest.frontend_ui_rules.border_radius_tokens.model_dump(),
        "boxShadow": {
            "brand": manifest.frontend_ui_rules.shadow_style,
        },
    }
    tailwind_json_str = json.dumps(tailwind_theme, indent=2)
    tailwind_path = output_dir / "tailwind.theme.json"
    tailwind_path.write_text(tailwind_json_str, encoding="utf-8")

    # 8. generative-prompts.json
    gen_prompts_payload = {
        "project_name": manifest.project_name,
        "aesthetic_archetype": manifest.frontend_ui_rules.aesthetic_archetype,
        "palette_hex": [
            manifest.color_system.background_primary.hex,
            manifest.color_system.background_secondary.hex,
            manifest.color_system.accent_primary.hex,
            manifest.color_system.accent_secondary.hex,
        ],
        "global_style_prefix": manifest.generative_ai_prompts.global_style_prefix,
        "global_style_suffix": manifest.generative_ai_prompts.global_style_suffix,
        "negative_prompt": manifest.generative_ai_prompts.negative_prompt,
        "midjourney": {
            "parameters": manifest.generative_ai_prompts.midjourney_parameters,
            "hero_command": (
                f"/imagine prompt: {manifest.generative_ai_prompts.use_case_templates.hero_photography} "
                f"{manifest.generative_ai_prompts.midjourney_parameters}"
            ),
            "mascot_command": (
                f"/imagine prompt: {manifest.generative_ai_prompts.use_case_templates.brand_mascot_illustration} "
                f"{manifest.generative_ai_prompts.midjourney_parameters}"
            ),
        },
        "flux_and_imagen_templates": manifest.generative_ai_prompts.use_case_templates.model_dump(),
        "style_reference_images": [
            {
                "id": rp.id,
                "title": rp.title,
                "local_path": rp.local_path,
                "dominant_hex_colors": rp.dominant_hex_colors,
                "visual_tags": rp.visual_tags,
            }
            for rp in manifest.reference_pins[:8]
        ],
        "contact_sheet_path": "contact_sheet.jpg" if contact_sheet_path else "",
    }
    prompts_json_str = json.dumps(gen_prompts_payload, indent=2)
    prompts_path = output_dir / "generative-prompts.json"
    prompts_path.write_text(prompts_json_str, encoding="utf-8")

    # 9. brand-preview.html
    color_tokens = [
        ("BG Primary", "--brand-bg-primary", "background_primary", manifest.color_system.background_primary),
        ("BG Secondary", "--brand-bg-secondary", "background_secondary", manifest.color_system.background_secondary),
        ("Surface Card", "--brand-surface-card", "surface_card", manifest.color_system.surface_card),
        ("Text Primary", "--brand-text-primary", "text_primary", manifest.color_system.text_primary),
        ("Text Secondary", "--brand-text-secondary", "text_secondary", manifest.color_system.text_secondary),
        ("Accent Primary", "--brand-accent-primary", "accent_primary", manifest.color_system.accent_primary),
        ("Accent Secondary", "--brand-accent-secondary", "accent_secondary", manifest.color_system.accent_secondary),
        ("Warning", "--brand-semantic-warning", "semantic_warning", manifest.color_system.semantic_warning),
        ("Success", "--brand-semantic-success", "semantic_success", manifest.color_system.semantic_success),
    ]
    # visual-identity.json is intentionally omitted: the page already embeds it once as `manifestData`.
    payload_versions = {
        "AGENTS.md": agents_md_content,
        "cursor-visual-identity.mdc": cursor_mdc_content,
        "SKILL.md": skill_md_content,
        "DESIGN_SYSTEM.md": design_md_content,
        "tokens.w3c.json": w3c_json_str,
        "tokens.css": tokens_css,
        "tailwind.theme.json": tailwind_json_str,
        "generative-prompts.json": prompts_json_str,
    }
    safe_payload_versions_json = json.dumps(payload_versions).replace("</", "<\\/")
    preview_tpl = html_env.get_template("brand_preview.html.j2")
    preview_path = output_dir / "brand-preview.html"
    safe_manifest_json = manifest_json_str.replace("</", "<\\/")
    preview_path.write_text(
        preview_tpl.render(
            manifest=manifest,
            sim=_build_simulator_copy(manifest),
            manifest_json=safe_manifest_json,
            payload_versions_json=safe_payload_versions_json,
            tokens_css=tokens_css,
            color_tokens=color_tokens,
        ),
        encoding="utf-8",
    )

    artifacts = {
        "visual_identity_json": json_path,
        "design_system_md": design_md_path,
        "agents_md": agents_md_path,
        "cursor_rules_mdc": cursor_mdc_path,
        "skill_md": skill_md_path,
        "w3c_tokens_json": w3c_path,
        "tokens_css": tokens_css_path,
        "tailwind_theme_json": tailwind_path,
        "generative_prompts_json": prompts_path,
        "brand_preview_html": preview_path,
    }
    if contact_sheet_path and contact_sheet_path.exists():
        artifacts["contact_sheet_jpg"] = contact_sheet_path
    return artifacts


async def run_pin2brand_pipeline(
    board_url: str,
    output_root: Path = Path("output"),
    max_pins: int = 24,
    model_name: str = "gemini-2.5-flash",
    force_offline: bool = False,
    provider: str = "auto",
    cookies_path: Path | None = None,
) -> dict:
    """Shared end-to-end pipeline used by both the CLI and the MCP server."""
    from .scraper import download_references, scrape_board
    from .synthesizer import synthesize_identity
    from .vision_math import analyze_board_visuals

    board = await scrape_board(
        board_url=board_url,
        max_pins=max_pins,
        cookies_path=cookies_path,
    )
    board_dir = output_root / board.board_slug
    references_dir = board_dir / "references"
    contact_sheet_path = board_dir / "contact_sheet.jpg"

    downloaded = await download_references(board, references_dir)
    if not downloaded:
        raise RuntimeError(f"Failed to download any valid images from {board.canonical_url}")

    math_report = await asyncio.to_thread(
        analyze_board_visuals,
        board_title=board.board_title,
        pins=downloaded,
        contact_sheet_path=contact_sheet_path,
    )
    manifest, synthesis_mode = await asyncio.to_thread(
        synthesize_identity,
        board=board,
        report=math_report,
        model_name=model_name,
        force_offline=force_offline,
        provider=provider,
    )
    artifacts = await asyncio.to_thread(
        export_brand_kit,
        manifest=manifest,
        output_dir=board_dir,
        contact_sheet_path=contact_sheet_path,
    )
    return {
        "board": board,
        "math_report": math_report,
        "manifest": manifest,
        "synthesis_mode": synthesis_mode,
        "output_dir": board_dir,
        "artifacts": artifacts,
    }
