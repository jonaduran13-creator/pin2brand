"""Pydantic data models for Pin2Brand structured outputs and pipeline contracts."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ColorToken(BaseModel):
    """A single semantic color token with contrast pairing."""

    hex: str = Field(..., description="Hex color code, e.g. #F4EFE6")
    name: str = Field(..., description="Descriptive human name, e.g. Warm Aged Cream")
    role: str = Field(..., description="UI and branding usage role")
    usage_percentage: float = Field(
        ..., ge=0.0, le=100.0, description="Estimated share of visual area (0-100)"
    )
    contrast_text_hex: str = Field(
        ..., description="WCAG AA+ readable foreground text hex on this color"
    )


class ColorSystem(BaseModel):
    """Complete semantic color palette and harmony constraints."""

    background_primary: ColorToken
    background_secondary: ColorToken
    surface_card: ColorToken
    text_primary: ColorToken
    text_secondary: ColorToken
    accent_primary: ColorToken
    accent_secondary: ColorToken
    semantic_warning: ColorToken
    semantic_success: ColorToken
    color_harmony_notes: str = Field(
        ..., description="Guidance on temperature, pairing ratios, and surface contrast"
    )
    forbidden_colors: list[str] = Field(
        default_factory=list,
        description="Colors or hex patterns agents must avoid (e.g. pure #FFFFFF, neon purple)",
    )


class TypographyRule(BaseModel):
    """Typographic specification mapped to Google Fonts."""

    family_recommended: str = Field(..., description="Primary font family name")
    google_fonts_fallbacks: list[str] = Field(
        default_factory=list, description="Valid Google Fonts alternatives"
    )
    weight: str = Field(..., description="CSS font-weight value or range, e.g. '700' or '800'")
    letter_spacing: str = Field(..., description="CSS letter-spacing, e.g. '-0.02em'")
    text_transform: str = Field(..., description="CSS text-transform: uppercase | none | capitalize")
    styling_notes: str = Field(..., description="Usage, shadow, stroke, or pairing guidance")


class TypographySystem(BaseModel):
    """Full typographic hierarchy for front-end implementation."""

    display_heading: TypographyRule
    section_heading: TypographyRule
    body_copy: TypographyRule
    monospace_accent: TypographyRule
    google_fonts_import_url: str = Field(
        ..., description="Valid https://fonts.googleapis.com/css2?... URL importing all selected fonts"
    )


class BorderRadiusTokens(BaseModel):
    """Border radius scale for UI components."""

    sm: str = Field(..., description="Small radius, e.g. '2px'")
    md: str = Field(..., description="Medium radius, e.g. '4px'")
    lg: str = Field(..., description="Large radius, e.g. '8px'")
    pill: str = Field(..., description="Pill/badge radius, e.g. '9999px'")


class ComponentGuidelines(BaseModel):
    """Concrete implementation instructions for key front-end components."""

    buttons: str
    cards: str
    navigation: str
    hero_section: str
    badges: str


class FrontendUIRules(BaseModel):
    """Design system tokens and rules consumed by coding agents."""

    aesthetic_archetype: str = Field(
        ..., description="Short archetype label, e.g. 'Retro 70s Desert Diner / Neo-Brutalist Street Food'"
    )
    border_radius_tokens: BorderRadiusTokens
    border_style: str = Field(..., description="CSS border specification, e.g. '2px solid #1E1B18'")
    shadow_style: str = Field(..., description="CSS box-shadow specification")
    layout_grid_style: str = Field(..., description="Layout density, grid, and framing guidance")
    texture_and_effects: list[str] = Field(
        default_factory=list,
        description="Surface treatments like grain, halftone dots, stamps, or paper textures",
    )
    component_guidelines: ComponentGuidelines
    anti_patterns: list[str] = Field(
        default_factory=list,
        description="Explicit UI mistakes coding agents must avoid",
    )


class PromptUseCaseTemplates(BaseModel):
    """Ready-to-use prompt templates for image generation models."""

    hero_photography: str
    brand_mascot_illustration: str
    seamless_background_texture: str
    ui_icon_sticker: str


class GenerativeAIPrompts(BaseModel):
    """Prompt engineering kit for Midjourney, Flux, and Imagen."""

    global_style_prefix: str
    global_style_suffix: str
    negative_prompt: str
    midjourney_parameters: str
    use_case_templates: PromptUseCaseTemplates


class ReferencePin(BaseModel):
    """Annotated Pinterest reference pin included in the brand kit."""

    id: str
    title: str
    source_url: str
    local_path: str
    dominant_hex_colors: list[str] = Field(default_factory=list)
    visual_tags: list[str] = Field(default_factory=list)
    why_it_matters: str


class VisualIdentityManifest(BaseModel):
    """Master Visual Identity JSON schema exported by Pin2Brand."""

    project_name: str
    board_url: str
    generated_at: str
    brand_essence_summary: str
    mood_keywords: list[str]
    color_system: ColorSystem
    typography: TypographySystem
    frontend_ui_rules: FrontendUIRules
    generative_ai_prompts: GenerativeAIPrompts
    reference_pins: list[ReferencePin]


# --- Internal Pipeline Data Models ---


class ScrapedPin(BaseModel):
    """Raw pin metadata discovered by the Pinterest scraper."""

    pin_id: str
    index: int
    title: str
    description: str = ""
    pin_url: str
    image_url: str
    local_path: str = ""
    width: int = 0
    height: int = 0


class ScrapedBoard(BaseModel):
    """Result returned by the Pinterest scraper."""

    board_url: str
    canonical_url: str
    username: str
    board_slug: str
    board_title: str
    source_method: str
    pins: list[ScrapedPin] = Field(default_factory=list)


class ExtractedColorCluster(BaseModel):
    """Mathematical color cluster computed in CIELAB space."""

    hex: str
    rgb: tuple[int, int, int]
    percentage: float
    relative_luminance: float
    saturation: float
    hue_degrees: float
    temperature: str  # "warm" | "cool" | "neutral"
    suggested_role: str  # "background_light" | "background_dark" | "accent" | "midtone"
    best_contrast_text: str
    contrast_ratio_on_best: float


class PinColorSummary(BaseModel):
    """Per-pin mathematical color and texture summary."""

    pin_id: str
    index: int
    local_path: str
    dominant_hex_colors: list[str]
    texture_score: float = 0.0


class BoardMathReport(BaseModel):
    """Complete mathematical vision analysis for a Pinterest board."""

    global_clusters: list[ExtractedColorCluster]
    pin_summaries: list[PinColorSummary]
    contact_sheet_path: str
    overall_temperature: str
    average_saturation: float
    contrast_polarity: str  # "high_contrast" | "light_airy" | "dark_moody" | "balanced"
    texture_grain_score: float = 0.0
    surface_character: str = "tactile_organic"  # "tactile_organic" | "graphic_flat" | "photographic_rich"
    earth_tone_ratio: float = 0.0
