"""Automated test suite for Pin2Brand (NumPy K-Means++, CIEDE2000, W3C DTCG §9.6, MCP security, and parametric heuristics)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from pin2brand.exporter import run_pin2brand_pipeline
from pin2brand.mcp_server import validate_mcp_request
from pin2brand.scraper import parse_pinterest_board_url
from pin2brand.synthesizer import _sanitize_css_declaration_value
from pin2brand.vision_math import (
    _kmeans_plusplus_numpy,
    _lab_to_rgb,
    _rgb_to_lab,
    delta_e_cie76,
    delta_e_ciede2000,
    hex_to_rgb,
    rgb_to_hex,
    wcag_contrast_ratio,
)


def test_parse_pinterest_board_url_variants() -> None:
    url, host, user, slug = parse_pinterest_board_url(
        "https://mx.pinterest.com/jonathanduransandoval/coyote-burguer/"
    )
    assert host == "mx.pinterest.com"
    assert user == "jonathanduransandoval"
    assert slug == "coyote-burguer"
    assert url == "https://mx.pinterest.com/jonathanduransandoval/coyote-burguer/"

    _url2, _host2, user2, slug2 = parse_pinterest_board_url(
        "https://www.pinterest.com/user123/my-board.rss"
    )
    assert user2 == "user123"
    assert slug2 == "my-board"


def test_pure_numpy_kmeans_ciede2000_and_wcag() -> None:
    sample_rgb = np.array([[244, 239, 230], [177, 59, 41], [30, 27, 24]], dtype=np.uint8)
    lab = _rgb_to_lab(sample_rgb)
    reconstructed = _lab_to_rgb(lab)
    assert np.allclose(sample_rgb, reconstructed, atol=2)

    # Verify CIEDE2000 properties: identity = 0, symmetry, and perceptual differentiation
    assert delta_e_ciede2000((177, 59, 41), (177, 59, 41)) == pytest.approx(0.0, abs=1e-6)
    d12 = delta_e_ciede2000((177, 59, 41), (104, 150, 216))
    d21 = delta_e_ciede2000((104, 150, 216), (177, 59, 41))
    assert d12 == pytest.approx(d21, abs=1e-6)
    assert d12 > 35.0

    # Verify pure NumPy BLAS K-Means++ separates 2 clear clusters
    cluster_a = np.tile(np.array([10.0, 0.0, 0.0]), (50, 1))
    cluster_b = np.tile(np.array([90.0, 20.0, 30.0]), (50, 1))
    data = np.vstack([cluster_a, cluster_b])
    centers, labels = _kmeans_plusplus_numpy(data, k=2, seed=42)
    assert centers.shape == (2, 3)
    assert len(set(labels.tolist())) == 2

    ratio = wcag_contrast_ratio(hex_to_rgb("#F4EFE6"), hex_to_rgb("#1E1B18"))
    assert ratio >= 12.0
    assert rgb_to_hex((177, 59, 41)) == "#B13B29"


def test_parametric_minimal_burger_and_valid_css_shadow(tmp_path: Path) -> None:
    """Ensure a low-saturation smooth board named 'Japanese Burger' gets Minimalist Editorial rules and valid CSS shadow."""
    src_folder = tmp_path / "minimalist-japanese-burger"
    src_folder.mkdir()

    for idx, gray_val in enumerate([238, 224, 210, 42], start=1):
        img = Image.new("RGB", (300, 300), (gray_val, gray_val, gray_val - 4))
        img.save(src_folder / f"minimal_{idx:02d}.jpg", format="JPEG")

    result = asyncio.run(
        run_pin2brand_pipeline(
            board_url=str(src_folder),
            output_root=tmp_path / "out_minimal",
            max_pins=10,
            force_offline=True,
        )
    )
    manifest = result["manifest"]
    assert "Minimalist" in manifest.frontend_ui_rules.aesthetic_archetype
    assert manifest.frontend_ui_rules.border_style.startswith("1px solid")
    assert manifest.frontend_ui_rules.shadow_style == "none"
    assert "(" not in manifest.frontend_ui_rules.shadow_style
    assert manifest.typography.display_heading.family_recommended == "Instrument Serif"

    assert _sanitize_css_declaration_value("4px 4px 0px #1E1B18 (Hard offset shadow)", "none") == "4px 4px 0px #1E1B18"
    assert _sanitize_css_declaration_value("0 6px 18px rgba(10, 20, 30, 0.2)", "none") == "0 6px 18px rgba(10, 20, 30, 0.2)"


def test_end_to_end_local_folder_w3c_dtcg_and_templates(tmp_path: Path) -> None:
    """Verify full pipeline produces portable paths, W3C DTCG §9.6 structured shadow, and distinct agent files."""
    src_folder = tmp_path / "desert-coyote-mood"
    src_folder.mkdir()

    palettes = [
        [(177, 59, 41), (212, 185, 155)],
        [(198, 62, 48), (106, 128, 138)],
        [(163, 151, 138), (205, 181, 155)],
        [(42, 40, 45), (92, 137, 202)],
        [(100, 99, 83), (177, 59, 41)],
    ]
    for idx, (col_a, col_b) in enumerate(palettes, start=1):
        img = Image.new("RGB", (320, 400), col_a)
        draw = ImageDraw.Draw(img)
        draw.rectangle([40, 40, 280, 360], fill=col_b)
        img.save(src_folder / f"sample_{idx:02d}.jpg", format="JPEG")

    out_root = tmp_path / "out"
    result = asyncio.run(
        run_pin2brand_pipeline(
            board_url=str(src_folder),
            output_root=out_root,
            max_pins=10,
            force_offline=True,
        )
    )

    artifacts = result["artifacts"]
    manifest_raw = artifacts["visual_identity_json"].read_text(encoding="utf-8")
    prompts_raw = artifacts["generative_prompts_json"].read_text(encoding="utf-8")
    assert "C:\\\\" not in manifest_raw and "Users" not in manifest_raw
    assert "C:\\\\" not in prompts_raw and "Users" not in prompts_raw
    assert '"local_path": "references/pin_01.jpg"' in manifest_raw

    # Verify W3C DTCG §9.6 structured shadow object
    w3c_data = json.loads(artifacts["w3c_tokens_json"].read_text(encoding="utf-8"))
    shadow_val = w3c_data["brand"]["shadow"]["default"]["$value"]
    assert isinstance(shadow_val, dict)
    assert {"color", "offsetX", "offsetY", "blur", "spread"} == set(shadow_val.keys())

    # Verify each agent file has a distinct purpose-built template
    design_md = artifacts["design_system_md"].read_text(encoding="utf-8")
    agents_md = artifacts["agents_md"].read_text(encoding="utf-8")
    cursor_mdc = artifacts["cursor_rules_mdc"].read_text(encoding="utf-8")
    skill_md = artifacts["skill_md"].read_text(encoding="utf-8")

    assert len({design_md, agents_md, cursor_mdc, skill_md}) == 4
    assert "Pre-Commit UI Verification Checklist" in agents_md
    assert "Token-Driven JSX / Tailwind Component Blueprints" in cursor_mdc
    assert "var(--brand-accent-primary)" in cursor_mdc
    assert "Skill Workflow:" in skill_md

    # Verify WCAG AA (>= 4.5:1) on all 9 color tokens AND text_primary vs text_secondary Delta-E
    cs = result["manifest"].color_system
    for tok in [
        cs.background_primary,
        cs.background_secondary,
        cs.surface_card,
        cs.text_primary,
        cs.text_secondary,
        cs.accent_primary,
        cs.accent_secondary,
        cs.semantic_warning,
        cs.semantic_success,
    ]:
        assert wcag_contrast_ratio(hex_to_rgb(tok.hex), hex_to_rgb(tok.contrast_text_hex)) >= 4.5

    assert delta_e_ciede2000(hex_to_rgb(cs.text_primary.hex), hex_to_rgb(cs.text_secondary.hex)) >= 10.0
    assert delta_e_ciede2000(hex_to_rgb(cs.accent_primary.hex), hex_to_rgb(cs.accent_secondary.hex)) >= 14.0

    html_raw = artifacts["brand_preview_html"].read_text(encoding="utf-8")
    assert "hydratePinCanvasesFromContactSheet" in html_raw
    assert "payloadVersions" in html_raw


def test_mcp_security_boundaries() -> None:
    """Ensure MCP server blocks arbitrary local directory scanning and path traversal."""
    with pytest.raises(ValueError, match="Local directory scanning via MCP is disabled"):
        validate_mcp_request("C:/Users/Public", "output")

    with pytest.raises(ValueError, match="MCP only permits Pinterest board URLs"):
        validate_mcp_request("https://evil.example.com/user/board/", "output")

    with pytest.raises(ValueError, match="Path traversal blocked"):
        validate_mcp_request(
            "https://mx.pinterest.com/jonathanduransandoval/coyote-burguer/",
            "../../outside_workspace",
        )

    safe_path = validate_mcp_request(
        "https://mx.pinterest.com/jonathanduransandoval/coyote-burguer/",
        "output",
    )
    assert safe_path.name == "output"
