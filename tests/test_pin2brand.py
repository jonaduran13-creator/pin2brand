"""Automated test suite for Pin2Brand (Pure NumPy CIELAB K-Means++, parametric heuristics, portable paths, and distinct agent templates)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from pin2brand.exporter import run_pin2brand_pipeline
from pin2brand.scraper import parse_pinterest_board_url
from pin2brand.vision_math import (
    _kmeans_plusplus_numpy,
    _lab_to_rgb,
    _rgb_to_lab,
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


def test_pure_numpy_kmeans_and_cielab_wcag() -> None:
    sample_rgb = np.array([[244, 239, 230], [177, 59, 41], [30, 27, 24]], dtype=np.uint8)
    lab = _rgb_to_lab(sample_rgb)
    reconstructed = _lab_to_rgb(lab)
    assert np.allclose(sample_rgb, reconstructed, atol=2)

    # Verify pure NumPy K-Means++ separates 2 clear clusters
    cluster_a = np.tile(np.array([10.0, 0.0, 0.0]), (50, 1))
    cluster_b = np.tile(np.array([90.0, 20.0, 30.0]), (50, 1))
    data = np.vstack([cluster_a, cluster_b])
    centers, labels = _kmeans_plusplus_numpy(data, k=2, seed=42)
    assert centers.shape == (2, 3)
    assert len(set(labels.tolist())) == 2

    ratio = wcag_contrast_ratio(hex_to_rgb("#F4EFE6"), hex_to_rgb("#1E1B18"))
    assert ratio >= 12.0
    assert rgb_to_hex((177, 59, 41)) == "#B13B29"


def test_parametric_minimal_burger_overrides_title_keyword(tmp_path: Path) -> None:
    """Ensure a low-saturation smooth board named 'Japanese Burger' gets Minimalist Editorial rules, not 70s Diner."""
    src_folder = tmp_path / "minimalist-japanese-burger"
    src_folder.mkdir()

    # Smooth, low-saturation monochrome/warm-gray images
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
    assert manifest.typography.display_heading.family_recommended == "Instrument Serif"


def test_end_to_end_local_folder_portable_paths_and_distinct_templates(tmp_path: Path) -> None:
    """Verify full pipeline produces portable relative paths and genuinely distinct agent files."""
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
    # Verify portable relative paths (no absolute machine paths like C:\Users\...)
    manifest_raw = artifacts["visual_identity_json"].read_text(encoding="utf-8")
    prompts_raw = artifacts["generative_prompts_json"].read_text(encoding="utf-8")
    assert "C:\\\\" not in manifest_raw and "Users" not in manifest_raw
    assert "C:\\\\" not in prompts_raw and "Users" not in prompts_raw
    assert '"local_path": "references/pin_01.jpg"' in manifest_raw

    # Verify each agent file has a distinct purpose-built template (no Ctrl+C/Ctrl+V duplicates)
    design_md = artifacts["design_system_md"].read_text(encoding="utf-8")
    agents_md = artifacts["agents_md"].read_text(encoding="utf-8")
    cursor_mdc = artifacts["cursor_rules_mdc"].read_text(encoding="utf-8")
    skill_md = artifacts["skill_md"].read_text(encoding="utf-8")

    assert len({design_md, agents_md, cursor_mdc, skill_md}) == 4
    assert "Pre-Commit UI Verification Checklist" in agents_md
    assert "JSX / Tailwind Component Blueprints" in cursor_mdc
    assert "Skill Workflow:" in skill_md
