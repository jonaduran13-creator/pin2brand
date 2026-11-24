"""Mathematical color science (Pure NumPy CIELAB K-Means++ + WCAG + Texture Metrics) and Contact Sheet generator."""

from __future__ import annotations

import colorsys
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .models import (
    BoardMathReport,
    ExtractedColorCluster,
    PinColorSummary,
    ScrapedPin,
)

# D65 standard illuminant reference white
_D65_XN = 0.95047
_D65_YN = 1.00000
_D65_ZN = 1.08883


def _rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """Convert uint8/float RGB array (N, 3) in [0, 255] to CIELAB (N, 3)."""
    srgb = np.clip(rgb.astype(np.float64) / 255.0, 0.0, 1.0)
    mask = srgb > 0.04045
    lin = np.where(mask, ((srgb + 0.055) / 1.055) ** 2.4, srgb / 12.92)

    m = np.array(
        [
            [0.4124564, 0.3575761, 0.1804375],
            [0.2126729, 0.7151522, 0.0721750],
            [0.0193339, 0.1191920, 0.9503041],
        ]
    )
    xyz = lin @ m.T
    xyz_norm = xyz / np.array([_D65_XN, _D65_YN, _D65_ZN])

    eps = 216.0 / 24389.0
    kappa = 24389.0 / 27.0
    f = np.where(xyz_norm > eps, np.cbrt(xyz_norm), (kappa * xyz_norm + 16.0) / 116.0)

    L = 116.0 * f[:, 1] - 16.0
    a = 500.0 * (f[:, 0] - f[:, 1])
    b = 200.0 * (f[:, 1] - f[:, 2])
    return np.stack([L, a, b], axis=1)


def _lab_to_rgb(lab: np.ndarray) -> np.ndarray:
    """Convert CIELAB array (N, 3) back to clipped uint8 RGB (N, 3)."""
    L, a, b = lab[:, 0], lab[:, 1], lab[:, 2]
    fy = (L + 16.0) / 116.0
    fx = a / 500.0 + fy
    fz = fy - b / 200.0

    eps = 216.0 / 24389.0
    kappa = 24389.0 / 27.0

    xr = np.where(fx**3 > eps, fx**3, (116.0 * fx - 16.0) / kappa)
    yr = np.where(L > kappa * eps, ((L + 16.0) / 116.0) ** 3, L / kappa)
    zr = np.where(fz**3 > eps, fz**3, (116.0 * fz - 16.0) / kappa)

    xyz = np.stack([xr * _D65_XN, yr * _D65_YN, zr * _D65_ZN], axis=1)
    m_inv = np.array(
        [
            [3.2404542, -1.5371385, -0.4985314],
            [-0.9692660, 1.8760108, 0.0415560],
            [0.0556434, -0.2040259, 1.0572252],
        ]
    )
    lin = np.clip(xyz @ m_inv.T, 0.0, 1.0)
    srgb = np.where(lin > 0.0031308, 1.055 * (lin ** (1.0 / 2.4)) - 0.055, 12.92 * lin)
    return np.clip(np.round(srgb * 255.0), 0, 255).astype(np.uint8)


def _kmeans_plusplus_numpy(
    data: np.ndarray,
    k: int,
    n_init: int = 4,
    max_iter: int = 60,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray]:
    """Pure NumPy K-Means++ implementation (zero scipy/scikit-learn dependency).

    Returns (best_centers (k, D), best_labels (N,)).
    """
    n_samples, n_features = data.shape
    rng = np.random.default_rng(seed)
    best_inertia = float("inf")
    best_centers = np.zeros((k, n_features), dtype=np.float64)
    best_labels = np.zeros(n_samples, dtype=np.int64)
    data_norm_sq = np.sum(data**2, axis=1)

    for _ in range(n_init):
        # K-Means++ initialization
        centers = np.empty((k, n_features), dtype=np.float64)
        first_idx = int(rng.integers(0, n_samples))
        centers[0] = data[first_idx]
        closest_dist_sq = np.maximum(
            0.0, data_norm_sq + float(np.sum(centers[0] ** 2)) - 2.0 * (data @ centers[0])
        )

        for c_id in range(1, k):
            total_d = float(np.sum(closest_dist_sq))
            if total_d <= 1e-12:
                idx = int(rng.integers(0, n_samples))
            else:
                probs = closest_dist_sq / total_d
                idx = int(rng.choice(n_samples, p=probs))
            centers[c_id] = data[idx]
            new_dist_sq = np.maximum(
                0.0, data_norm_sq + float(np.sum(centers[c_id] ** 2)) - 2.0 * (data @ centers[c_id])
            )
            closest_dist_sq = np.minimum(closest_dist_sq, new_dist_sq)

        # Lloyd's iterations using BLAS matrix product ||x - c||^2 = ||x||^2 + ||c||^2 - 2 x.c^T
        labels = np.zeros(n_samples, dtype=np.int64)
        for _it in range(max_iter):
            centers_norm_sq = np.sum(centers**2, axis=1)
            dists_sq = np.maximum(
                0.0, data_norm_sq[:, None] + centers_norm_sq[None, :] - 2.0 * (data @ centers.T)
            )
            new_labels = np.argmin(dists_sq, axis=1)
            if np.array_equal(new_labels, labels) and _it > 0:
                break
            labels = new_labels
            for j in range(k):
                mask = labels == j
                if np.any(mask):
                    centers[j] = data[mask].mean(axis=0)
                else:
                    centers[j] = data[int(rng.integers(0, n_samples))]

        final_dists_sq = np.sum((data - centers[labels]) ** 2, axis=1)
        inertia = float(np.sum(final_dists_sq))
        if inertia < best_inertia:
            best_inertia = inertia
            best_centers = centers.copy()
            best_labels = labels.copy()

    return best_centers, best_labels


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    cleaned = hex_color.strip().lstrip("#")
    if len(cleaned) == 3:
        cleaned = "".join(c * 2 for c in cleaned)
    return (int(cleaned[0:2], 16), int(cleaned[2:4], 16), int(cleaned[4:6], 16))


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    """Compute WCAG 2.1 relative luminance in [0, 1]."""
    channels = []
    for c in rgb:
        s = c / 255.0
        channels.append(s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def wcag_contrast_ratio(rgb1: tuple[int, int, int], rgb2: tuple[int, int, int]) -> float:
    """Compute WCAG contrast ratio between two RGB colors (1.0 to 21.0)."""
    l1 = relative_luminance(rgb1)
    l2 = relative_luminance(rgb2)
    lighter, darker = max(l1, l2), min(l1, l2)
    return round((lighter + 0.05) / (darker + 0.05), 2)


def _classify_color(
    rgb: tuple[int, int, int],
    percentage: float,
) -> ExtractedColorCluster:
    r, g, b = rgb
    h, _l_hsl, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    hue_deg = round(h * 360.0, 1)
    lum = round(relative_luminance(rgb), 4)
    sat = round(s, 4)

    if sat < 0.12:
        temperature = "neutral"
    elif (hue_deg <= 75.0) or (hue_deg >= 300.0):
        temperature = "warm"
    else:
        temperature = "cool"

    if lum >= 0.62 and sat <= 0.45:
        suggested_role = "background_light"
    elif lum <= 0.14:
        suggested_role = "background_dark"
    elif sat >= 0.35 and 0.08 <= lum <= 0.72:
        suggested_role = "accent"
    else:
        suggested_role = "midtone"

    dark_ink = (20, 18, 16)
    light_ink = (250, 248, 245)
    c_dark = wcag_contrast_ratio(rgb, dark_ink)
    c_light = wcag_contrast_ratio(rgb, light_ink)
    if c_dark >= c_light:
        best_text = rgb_to_hex(dark_ink)
        best_ratio = c_dark
    else:
        best_text = rgb_to_hex(light_ink)
        best_ratio = c_light

    return ExtractedColorCluster(
        hex=rgb_to_hex(rgb),
        rgb=rgb,
        percentage=round(percentage, 2),
        relative_luminance=lum,
        saturation=sat,
        hue_degrees=hue_deg,
        temperature=temperature,
        suggested_role=suggested_role,
        best_contrast_text=best_text,
        contrast_ratio_on_best=best_ratio,
    )


def _sample_image_pixels_and_texture(image_path: Path, size: int = 150) -> tuple[np.ndarray, float]:
    """Return ((size*size, 3) uint8 RGB array, normalized discrete Laplacian texture score)."""
    with Image.open(image_path) as img:
        rgb_img = img.convert("RGB").resize((size, size), Image.Resampling.LANCZOS)
        arr = np.asarray(rgb_img, dtype=np.uint8)
        gray = (
            0.299 * arr[:, :, 0].astype(np.float64)
            + 0.587 * arr[:, :, 1].astype(np.float64)
            + 0.114 * arr[:, :, 2].astype(np.float64)
        )
        lap = (
            4.0 * gray[1:-1, 1:-1]
            - gray[:-2, 1:-1]
            - gray[2:, 1:-1]
            - gray[1:-1, :-2]
            - gray[1:-1, 2:]
        )
        texture_score = round(float(np.std(lap)), 2)
        return arr.reshape(-1, 3), texture_score


def _extract_k_colors_lab(
    pixels_rgb: np.ndarray,
    n_clusters: int,
    random_state: int = 42,
) -> list[tuple[tuple[int, int, int], float]]:
    """Run pure-NumPy K-Means++ in CIELAB space and return [(rgb_tuple, percentage), ...] sorted by share."""
    unique_count = len(np.unique(pixels_rgb, axis=0))
    k = max(1, min(n_clusters, unique_count))
    lab_pixels = _rgb_to_lab(pixels_rgb)
    centers_lab, labels = _kmeans_plusplus_numpy(
        lab_pixels, k=k, n_init=4, max_iter=60, seed=random_state
    )
    counts = np.bincount(labels, minlength=k).astype(np.float64)
    total = float(counts.sum()) or 1.0

    centroids_rgb = _lab_to_rgb(centers_lab)
    ranked = sorted(
        [
            (
                (int(centroids_rgb[i, 0]), int(centroids_rgb[i, 1]), int(centroids_rgb[i, 2])),
                (counts[i] / total) * 100.0,
            )
            for i in range(k)
        ],
        key=lambda item: item[1],
        reverse=True,
    )
    return ranked


def delta_e_cie76(rgb1: tuple[int, int, int], rgb2: tuple[int, int, int]) -> float:
    """Compute perceptual CIE76 Delta-E distance in CIELAB space between two RGB colors."""
    pair = np.array([rgb1, rgb2], dtype=np.uint8)
    lab = _rgb_to_lab(pair)
    return float(np.linalg.norm(lab[0] - lab[1]))


def _deduplicate_clusters(
    clusters: list[ExtractedColorCluster], min_delta_e: float = 8.5
) -> list[ExtractedColorCluster]:
    """Merge perceptually near-identical clusters using CIELAB Delta-E distance."""
    kept: list[ExtractedColorCluster] = []
    for c in clusters:
        merged = False
        for existing in kept:
            if delta_e_cie76(c.rgb, existing.rgb) < min_delta_e:
                existing.percentage = round(existing.percentage + c.percentage, 2)
                merged = True
                break
        if not merged:
            kept.append(c)
    return kept


def _load_font(size: int, bold: bool = False) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    candidates = (
        [
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/segoeuib.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
        if bold
        else [
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    )
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def generate_contact_sheet(
    board_title: str,
    pins: list[ScrapedPin],
    pin_summaries: list[PinColorSummary],
    global_clusters: list[ExtractedColorCluster],
    output_path: Path,
) -> Path:
    """Create a numbered 4-column visual contact sheet with dynamic row height and HEX swatches."""
    shown_pins = pins[:20]
    cols = 4
    rows = max(1, min(5, math.ceil(len(shown_pins) / cols)))

    canvas_w = 1600
    header_h = 145
    margin_x = 36
    gap_x = 24
    gap_y = 22
    top_y = header_h + 26
    bottom_margin = 28
    cell_h = 345
    canvas_h = top_y + rows * cell_h + (rows - 1) * gap_y + bottom_margin

    bg_color = (18, 18, 18)
    card_bg = (28, 28, 30)
    border_col = (48, 48, 52)
    text_light = (244, 241, 234)
    text_muted = (168, 164, 158)

    canvas = Image.new("RGB", (canvas_w, canvas_h), bg_color)
    draw = ImageDraw.Draw(canvas)

    font_title = _load_font(34, bold=True)
    font_sub = _load_font(18, bold=False)
    font_badge = _load_font(17, bold=True)
    font_hex = _load_font(14, bold=True)

    # Header bar
    draw.rectangle([0, 0, canvas_w, header_h], fill=(24, 24, 26))
    draw.line([0, header_h, canvas_w, header_h], fill=border_col, width=2)
    draw.text((40, 26), f"PIN2BRAND CONTACT SHEET  —  {board_title.upper()}", fill=text_light, font=font_title)
    draw.text(
        (40, 74),
        f"{len(shown_pins)} Reference Pins  |  CIELAB Mathematical Palette (Top Clusters)",
        fill=text_muted,
        font=font_sub,
    )

    swatch_x = 40
    swatch_y = 104
    for cluster in global_clusters[:10]:
        draw.rectangle([swatch_x, swatch_y, swatch_x + 28, swatch_y + 24], fill=cluster.rgb, outline=(70, 70, 75))
        draw.text((swatch_x + 34, swatch_y + 4), cluster.hex, fill=text_light, font=font_hex)
        swatch_x += 148

    cell_w = (canvas_w - 2 * margin_x - (cols - 1) * gap_x) // cols
    swatch_bar_h = 48
    thumb_h = cell_h - swatch_bar_h

    summary_map = {s.pin_id: s for s in pin_summaries}

    for idx, pin in enumerate(shown_pins):
        r = idx // cols
        c = idx % cols
        x0 = margin_x + c * (cell_w + gap_x)
        y0 = top_y + r * (cell_h + gap_y)

        draw.rounded_rectangle(
            [x0, y0, x0 + cell_w, y0 + cell_h],
            radius=8,
            fill=card_bg,
            outline=border_col,
            width=1,
        )

        if pin.local_path and Path(pin.local_path).exists():
            with Image.open(pin.local_path) as raw_img:
                fitted = ImageOps.fit(
                    raw_img.convert("RGB"),
                    (cell_w - 4, thumb_h - 4),
                    method=Image.Resampling.LANCZOS,
                )
                canvas.paste(fitted, (x0 + 2, y0 + 2))

        badge_label = f"#{pin.index}"
        badge_w = 46 if pin.index < 10 else 54
        draw.rounded_rectangle(
            [x0 + 10, y0 + 10, x0 + 10 + badge_w, y0 + 36],
            radius=6,
            fill=(15, 15, 15),
            outline=(244, 241, 234),
            width=2,
        )
        draw.text((x0 + 19, y0 + 13), badge_label, fill=(244, 241, 234), font=font_badge)

        pin_summary = summary_map.get(pin.pin_id)
        hexes = pin_summary.dominant_hex_colors[:3] if pin_summary else []
        sw_y = y0 + thumb_h + 8
        sw_step = (cell_w - 20) // 3
        for s_i, hx in enumerate(hexes):
            sx = x0 + 10 + s_i * sw_step
            rgb = hex_to_rgb(hx)
            draw.rectangle([sx, sw_y, sx + 22, sw_y + 22], fill=rgb, outline=(90, 90, 96))
            draw.text((sx + 27, sw_y + 4), hx, fill=text_light, font=font_hex)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="JPEG", quality=92)
    return output_path


def analyze_board_visuals(
    board_title: str,
    pins: list[ScrapedPin],
    contact_sheet_path: Path,
) -> BoardMathReport:
    """Compute CIELAB K-Means++ palettes, texture grain metrics, WCAG contrast, and contact sheet."""
    valid_pins = [p for p in pins if p.local_path and Path(p.local_path).exists()]
    if not valid_pins:
        raise ValueError("No downloaded local pin images available for visual analysis.")

    pin_summaries: list[PinColorSummary] = []
    global_pixel_samples: list[np.ndarray] = []
    texture_scores: list[float] = []

    rng = np.random.default_rng(42)
    for pin in valid_pins:
        pixels, tex_score = _sample_image_pixels_and_texture(Path(pin.local_path), size=150)
        texture_scores.append(tex_score)
        sample_idx = rng.choice(len(pixels), size=min(2000, len(pixels)), replace=False)
        global_pixel_samples.append(pixels[sample_idx])

        ranked = _extract_k_colors_lab(pixels, n_clusters=6)
        distinct_hexes: list[str] = []
        distinct_rgbs: list[tuple[int, int, int]] = []
        for rgb, _pct in ranked:
            if all(delta_e_cie76(rgb, prev_rgb) >= 8.5 for prev_rgb in distinct_rgbs):
                distinct_rgbs.append(rgb)
                distinct_hexes.append(rgb_to_hex(rgb))
            if len(distinct_hexes) >= 3:
                break
        if not distinct_hexes and ranked:
            distinct_hexes = [rgb_to_hex(ranked[0][0])]

        pin_summaries.append(
            PinColorSummary(
                pin_id=pin.pin_id,
                index=pin.index,
                local_path=f"references/{Path(pin.local_path).name}",
                dominant_hex_colors=distinct_hexes,
                texture_score=tex_score,
            )
        )

    all_samples = np.vstack(global_pixel_samples)
    global_ranked = _extract_k_colors_lab(all_samples, n_clusters=12)
    raw_clusters = [_classify_color(rgb, pct) for rgb, pct in global_ranked]
    global_clusters = _deduplicate_clusters(raw_clusters, min_delta_e=8.5)
    global_clusters.sort(key=lambda c: c.percentage, reverse=True)

    generate_contact_sheet(
        board_title=board_title,
        pins=valid_pins,
        pin_summaries=pin_summaries,
        global_clusters=global_clusters,
        output_path=contact_sheet_path,
    )

    warm_weight = sum(c.percentage for c in global_clusters if c.temperature == "warm")
    cool_weight = sum(c.percentage for c in global_clusters if c.temperature == "cool")
    if warm_weight > cool_weight * 1.2:
        overall_temp = "warm"
    elif cool_weight > warm_weight * 1.2:
        overall_temp = "cool"
    else:
        overall_temp = "balanced"

    avg_sat = round(
        sum(c.saturation * (c.percentage / 100.0) for c in global_clusters), 3
    )

    has_light = any(c.relative_luminance >= 0.60 for c in global_clusters)
    has_dark = any(c.relative_luminance <= 0.14 for c in global_clusters)
    avg_lum = sum(c.relative_luminance * (c.percentage / 100.0) for c in global_clusters)

    if has_light and has_dark:
        polarity = "high_contrast"
    elif avg_lum >= 0.50:
        polarity = "light_airy"
    elif avg_lum <= 0.25:
        polarity = "dark_moody"
    else:
        polarity = "balanced"

    avg_texture = round(float(np.mean(texture_scores)) if texture_scores else 0.0, 2)
    earth_share = round(
        sum(
            c.percentage
            for c in global_clusters
            if (4.0 <= c.hue_degrees <= 55.0) and (0.10 <= c.saturation <= 0.72) and (0.04 <= c.relative_luminance <= 0.68)
        ),
        2,
    )

    if avg_texture >= 24.0 or earth_share >= 35.0:
        surface_char = "tactile_organic"
    elif avg_texture <= 14.0:
        surface_char = "graphic_flat"
    else:
        surface_char = "photographic_rich"

    return BoardMathReport(
        global_clusters=global_clusters,
        pin_summaries=pin_summaries,
        contact_sheet_path=str(contact_sheet_path),
        overall_temperature=overall_temp,
        average_saturation=avg_sat,
        contrast_polarity=polarity,
        texture_grain_score=avg_texture,
        surface_character=surface_char,
        earth_tone_ratio=earth_share,
    )
