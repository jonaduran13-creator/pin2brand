"""Automated test suite for Pin2Brand (CIELAB color science, local folders, URL parser, synthesizer, and multi-agent exporters)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from pin2brand.exporter import run_pin2brand_pipeline
from pin2brand.scraper import parse_pinterest_board_url
from pin2brand.vision_math import (
    _lab_to_rgb,
    _rgb_to_lab,
    analyze_board_visuals,
    hex_to_rgb,
    rgb_to_hex,
    wcag_contrast_ratio,
)
import numpy as np


def test_parse_pinterest_board_url_variants() -> None:
    url, host, user, slug = parse_pinterest_board_url(
        "https://mx.pinterest.com/jonathanduransandoval/coyote-burguer/"
    )
    assert host == "mx.pinterest.com"
    assert user == "jonathanduransandoval"
    assert slug == "coyote-burguer"
    assert url == "https://mx.pinterest.com/jonathanduransandoval/coyote-burguer/"

    url2, _host2, user2, slug2 = parse_pinterest_board_url(
        "https://www.pinterest.com/user123/my-board.rss"
    )
    assert user2 == "user123"
    assert slug2 == "my-board"


def test_cielab_roundtrip_and_wcag() -> None:
    sample_rgb = np.array([[244, 239, 230], [177, 59, 41], [30, 27, 24]], dtype=np.uint8)
    lab = _rgb_to_lab(sample_rgb)
    reconstructed = _lab_to_rgb(lab)
    assert np.allclose(sample_rgb, reconstructed, atol=2)

    ratio = wcag_contrast_ratio(hex_to_rgb("#F4EFE6"), hex_to_rgb("#1E1B18"))
    assert ratio >= 12.0
    assert rgb_to_hex((177, 59, 41)) == "#B13B29"


def test_end_to_end_local_folder_pipeline(tmp_path: Path) -> None:
    """Verify full pipeline on a synthetic local moodboard folder (5 images -> 2-row contact sheet + 11 artifacts)."""
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

    assert result["board"].source_method == "local_folder"
    assert len(result["board"].pins) == 5

    artifacts = result["artifacts"]
    expected_keys = {
        "visual_identity_json",
        "design_system_md",
        "agents_md",
        "cursor_rules_mdc",
        "skill_md",
        "w3c_tokens_json",
        "tokens_css",
        "tailwind_theme_json",
        "generative_prompts_json",
        "brand_preview_html",
        "contact_sheet_jpg",
    }
    assert expected_keys.issubset(set(artifacts.keys()))
    for path in artifacts.values():
        assert path.exists() and path.stat().st_size > 100

    # Verify dynamic contact sheet height: 5 pins => 2 rows (< 1200px height, no 5-row 2000px dead space)
    with Image.open(artifacts["contact_sheet_jpg"]) as cs_img:
        assert cs_img.width == 1600
        assert cs_img.height < 1200

    # Verify W3C Design Tokens format
    w3c_data = json.loads(artifacts["w3c_tokens_json"].read_text(encoding="utf-8"))
    assert "$schema" in w3c_data
    assert w3c_data["brand"]["color"]["accent"]["primary"]["$type"] == "color"
