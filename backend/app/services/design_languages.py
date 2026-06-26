"""Design-language presets for HTML-rendered slides.

Each preset re-parameterizes the *shared* stylesheet — display type scale,
geometry (radius/padding/gap), gradient angles, decorative motif, and font
stacks — so decks can look genuinely different without per-slide restyling.

``editorial_serif`` reproduces the original house style byte-for-byte and is the
default, so brand-mode output (which carries no design language) is unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DesignLanguage:
    key: str
    label: str
    # display type
    heading_scale: float          # multiplies the display type scale
    headline_weight: int          # .headline / .c-title weight
    eyebrow_spacing: str          # eyebrow letter-spacing
    # geometry
    card_radius: int              # px
    card_padding: str             # CSS padding for .card
    card_gap: int                 # px grid gap
    slide_padding: str            # CSS padding for .slide
    cover_padding: str            # CSS padding for .slide.cover
    # surfaces
    dark_angle: int               # dark gradient angle (deg)
    light_angle: int              # light gradient angle (deg)
    # decoration
    motif: str                    # "rings" | "grid" | "diagonal" | "none"
    motif_slots: tuple[str, ...]  # slots where the motif appears
    # typography (stacks appended after the brand-chosen font)
    serif_fallback: str
    sans_fallback: str
    mono: str
    # freeform palette generation seed
    palette_strategy: str         # "editorial" | "cool" | "warm" | "high_contrast" | "duotone"


# ``editorial_serif`` mirrors the current css.py / design_system.py literals
# exactly — this is the regression baseline and the default.
_EDITORIAL = DesignLanguage(
    key="editorial_serif",
    label="Editorial serif",
    heading_scale=1.0,
    headline_weight=600,
    eyebrow_spacing="0.20em",
    card_radius=16,
    card_padding="26px 28px",
    card_gap=22,
    slide_padding="70px 84px 60px",
    cover_padding="70px 90px",
    dark_angle=155,
    light_angle=165,
    motif="rings",
    motif_slots=("cover", "closing"),
    serif_fallback='"Newsreader", Georgia, "Times New Roman", serif',
    sans_fallback='"Hanken Grotesk", "Inter", -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif',
    mono='"IBM Plex Mono", "SF Mono", "Menlo", "Consolas", monospace',
    palette_strategy="editorial",
)

_MODERN = DesignLanguage(
    key="modern_geometric",
    label="Modern geometric",
    heading_scale=1.0,
    headline_weight=600,
    eyebrow_spacing="0.16em",
    card_radius=10,
    card_padding="24px 26px",
    card_gap=20,
    slide_padding="66px 80px 56px",
    cover_padding="66px 86px",
    dark_angle=120,
    light_angle=120,
    motif="grid",
    motif_slots=("cover", "closing", "section"),
    serif_fallback='"Poppins", "Montserrat", -apple-system, "Segoe UI", Arial, sans-serif',
    sans_fallback='"Inter", -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif',
    mono='"JetBrains Mono", "SF Mono", "Menlo", "Consolas", monospace',
    palette_strategy="cool",
)

_BOLD = DesignLanguage(
    key="bold_minimal",
    label="Bold minimal",
    heading_scale=1.14,
    headline_weight=700,
    eyebrow_spacing="0.28em",
    card_radius=4,
    card_padding="28px 30px",
    card_gap=18,
    slide_padding="74px 92px 60px",
    cover_padding="74px 96px",
    dark_angle=180,
    light_angle=180,
    motif="none",
    motif_slots=(),
    serif_fallback='"Archivo", "Helvetica Neue", -apple-system, "Segoe UI", Arial, sans-serif',
    sans_fallback='"Archivo", "Helvetica Neue", -apple-system, "Segoe UI", Arial, sans-serif',
    mono='"IBM Plex Mono", "SF Mono", "Menlo", "Consolas", monospace',
    palette_strategy="high_contrast",
)

_WARM = DesignLanguage(
    key="warm_magazine",
    label="Warm magazine",
    heading_scale=1.05,
    headline_weight=600,
    eyebrow_spacing="0.22em",
    card_radius=20,
    card_padding="28px 30px",
    card_gap=24,
    slide_padding="72px 88px 60px",
    cover_padding="72px 92px",
    dark_angle=150,
    light_angle=170,
    motif="diagonal",
    motif_slots=("cover", "closing", "statement"),
    serif_fallback='"Fraunces", "Playfair Display", Georgia, "Times New Roman", serif',
    sans_fallback='"Hanken Grotesk", "Inter", -apple-system, "Segoe UI", Arial, sans-serif',
    mono='"IBM Plex Mono", "SF Mono", "Menlo", "Consolas", monospace',
    palette_strategy="warm",
)

_TECH = DesignLanguage(
    key="technical_mono",
    label="Technical mono",
    heading_scale=0.96,
    headline_weight=600,
    eyebrow_spacing="0.18em",
    card_radius=6,
    card_padding="22px 24px",
    card_gap=18,
    slide_padding="64px 78px 54px",
    cover_padding="64px 84px",
    dark_angle=135,
    light_angle=135,
    motif="grid",
    motif_slots=("cover", "closing"),
    serif_fallback='"Space Grotesk", "Inter", -apple-system, "Segoe UI", Arial, sans-serif',
    sans_fallback='"Inter", -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif',
    mono='"JetBrains Mono", "IBM Plex Mono", "SF Mono", "Menlo", "Consolas", monospace',
    palette_strategy="duotone",
)

_DATA = DesignLanguage(
    key="data_forward",
    label="Data forward",
    heading_scale=0.98,
    headline_weight=600,
    eyebrow_spacing="0.14em",
    card_radius=12,
    card_padding="24px 26px",
    card_gap=20,
    slide_padding="66px 80px 56px",
    cover_padding="66px 86px",
    dark_angle=160,
    light_angle=160,
    motif="none",
    motif_slots=(),
    serif_fallback='"Inter", -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif',
    sans_fallback='"Inter", -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif',
    mono='"IBM Plex Mono", "SF Mono", "Menlo", "Consolas", monospace',
    palette_strategy="cool",
)

LANGUAGES: dict[str, DesignLanguage] = {
    dl.key: dl
    for dl in (_EDITORIAL, _MODERN, _BOLD, _WARM, _TECH, _DATA)
}
DEFAULT_LANGUAGE = "editorial_serif"
VALID_LANGUAGES = set(LANGUAGES) | {"auto"}

# Light topic → design-language nudges (only used when nothing more specific is set).
_TOPIC_LANGUAGE = [
    (("benchmark", "evaluation", "metric", "data", "analytics", "measurement", "kpi"), "data_forward"),
    (("agent", "code", "developer", "software", "api", "infrastructure", "platform"), "technical_mono"),
    (("brand", "story", "campaign", "creative", "magazine", "culture", "design"), "warm_magazine"),
    (("vision", "future", "bold", "launch", "manifesto", "keynote"), "bold_minimal"),
    (("product", "growth", "market", "strategy", "roadmap"), "modern_geometric"),
]


def get_language(key: str | None) -> DesignLanguage:
    return LANGUAGES.get((key or "").strip().lower(), LANGUAGES[DEFAULT_LANGUAGE])


def infer_design_language(text: str) -> str:
    lowered = (text or "").lower()
    for needles, lang in _TOPIC_LANGUAGE:
        if any(n in lowered for n in needles):
            return lang
    return DEFAULT_LANGUAGE


def resolve_design_language(
    explicit: str | None,
    style_default: str | None = None,
    topic_text: str = "",
) -> str:
    """Precedence: explicit selection > presentation-style default > topic nudge."""
    chosen = (explicit or "auto").strip().lower()
    if chosen != "auto" and chosen in LANGUAGES:
        return chosen
    if style_default and style_default in LANGUAGES:
        return style_default
    return infer_design_language(topic_text)
