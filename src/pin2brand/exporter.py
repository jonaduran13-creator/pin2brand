"""Multi-agent artifact exporter (JSON, DESIGN_SYSTEM.md, AGENTS.md, Cursor .mdc, SKILL.md, W3C tokens, CSS, Tailwind, Prompts, HTML Preview)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .models import VisualIdentityManifest

TEMPLATES_DIR = Path(__file__).parent / "templates"


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
                "default": {"$value": ui.shadow_style, "$type": "shadow"},
            },
        },
    }


def export_brand_kit(
    manifest: VisualIdentityManifest,
    output_dir: Path,
    contact_sheet_path: Path | None = None,
) -> dict[str, Path]:
    """Export all Pin2Brand multi-agent artifacts into `output_dir` and return their paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=False)

    # 1. visual-identity.json
    json_path = output_dir / "visual-identity.json"
    manifest_json_str = manifest.model_dump_json(indent=2)
    json_path.write_text(manifest_json_str, encoding="utf-8")

    # 2. DESIGN_SYSTEM.md
    design_tpl = env.get_template("DESIGN_SYSTEM.md.j2")
    design_md_content = design_tpl.render(manifest=manifest)
    design_md_path = output_dir / "DESIGN_SYSTEM.md"
    design_md_path.write_text(design_md_content, encoding="utf-8")

    # 3. AGENTS.md (Drop-in root instruction file for Antigravity, Claude Code, Codex, Windsurf)
    agents_md_path = output_dir / "AGENTS.md"
    agents_md_path.write_text(design_md_content, encoding="utf-8")

    # 4. cursor-visual-identity.mdc (Cursor IDE rule with YAML frontmatter)
    cursor_frontmatter = (
        "---\n"
        f"description: Visual Identity and UI Design System rules for {manifest.project_name} ({manifest.frontend_ui_rules.aesthetic_archetype})\n"
        'globs: ["**/*.tsx", "**/*.jsx", "**/*.css", "**/*.scss", "**/*.html", "**/*.vue", "**/*.svelte"]\n'
        "alwaysApply: true\n"
        "---\n\n"
    )
    cursor_mdc_path = output_dir / "cursor-visual-identity.mdc"
    cursor_mdc_path.write_text(cursor_frontmatter + design_md_content, encoding="utf-8")

    # 5. SKILL.md (Installable agent skill)
    slug = re.sub(r"[^a-z0-9-]+", "-", manifest.project_name.lower()).strip("-") or "brand"
    skill_frontmatter = (
        "---\n"
        f"name: {slug}-visual-identity\n"
        f"description: Enforces the {manifest.project_name} visual identity ({manifest.frontend_ui_rules.aesthetic_archetype}) extracted from Pinterest for front-end UI code and image generation.\n"
        "---\n\n"
    )
    skill_md_path = output_dir / "SKILL.md"
    skill_md_path.write_text(skill_frontmatter + design_md_content, encoding="utf-8")

    # 6. tokens.w3c.json (W3C Design Tokens for Figma & Style Dictionary)
    w3c_path = output_dir / "tokens.w3c.json"
    w3c_path.write_text(json.dumps(_build_w3c_design_tokens(manifest), indent=2), encoding="utf-8")

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
    tailwind_path = output_dir / "tailwind.theme.json"
    tailwind_path.write_text(json.dumps(tailwind_theme, indent=2), encoding="utf-8")

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
        "contact_sheet_path": str(contact_sheet_path) if contact_sheet_path else "",
    }
    prompts_path = output_dir / "generative-prompts.json"
    prompts_path.write_text(json.dumps(gen_prompts_payload, indent=2), encoding="utf-8")

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
    preview_tpl = env.get_template("brand_preview.html.j2")
    preview_path = output_dir / "brand-preview.html"
    preview_path.write_text(
        preview_tpl.render(
            manifest=manifest,
            manifest_json=manifest_json_str,
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

    math_report = analyze_board_visuals(
        board_title=board.board_title,
        pins=downloaded,
        contact_sheet_path=contact_sheet_path,
    )
    manifest, synthesis_mode = synthesize_identity(
        board=board,
        report=math_report,
        model_name=model_name,
        force_offline=force_offline,
        provider=provider,
    )
    artifacts = export_brand_kit(
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
