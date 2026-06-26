"""Freeform visual-system derivation.

Picks a topic-appropriate *design language* and generates a harmonious color
palette seeded from the deck's topic + the language's palette strategy. This is
the single source of freeform color/typography (replacing the old hand-tuned
five-palette keyword cascade), so two decks on different topics — or the same
topic under a different design language — look genuinely different.
"""

import colorsys

from app.models.brand import BrandDNA
from app.models.document import DocumentBundle
from app.services.design_languages import get_language, resolve_design_language

# Topic keyword -> base hue (degrees on the color wheel).
_TOPIC_HUE = [
    (("benchmark", "evaluation", "eval", "metric", "analytics", "measurement", "ground truth", "harness"), 205),
    (("agent", "code", "coding", "developer", "software", "repository", "api", "platform", "infrastructure"), 222),
    (("growth", "revenue", "market", "customer", "sales", "pipeline"), 150),
    (("risk", "security", "compliance", "governance", "threat"), 280),
    (("brand", "story", "campaign", "creative", "design", "culture", "magazine"), 24),
    (("health", "care", "clinical", "patient", "medical"), 178),
    (("finance", "capital", "invest", "fund", "budget"), 212),
    (("education", "learning", "research", "academic", "study"), 255),
    (("climate", "energy", "sustainab", "environment"), 135),
]
_DEFAULT_HUE = 210

# Representative fonts per design language for the authored (python-pptx)
# fallback path; the HTML path uses the design-language CSS stacks directly.
_FONT_FOR_LANGUAGE = {
    "editorial_serif": ("Georgia", "Aptos"),
    "warm_magazine": ("Georgia", "Aptos"),
    "modern_geometric": ("Aptos Display", "Aptos"),
    "bold_minimal": ("Aptos Display", "Aptos"),
    "technical_mono": ("Aptos Display", "Aptos"),
    "data_forward": ("Aptos Display", "Aptos"),
}


def derive_freeform_brand(
    bundle: DocumentBundle,
    instructions: str = "",
    design_language: str = "auto",
    presentation_style: str | None = None,
) -> BrandDNA:
    """Choose a design language + generate a topic-seeded palette for a freeform deck."""
    text = _theme_text(bundle, instructions)
    style_default = None
    if presentation_style:
        # Lazy import keeps this module usable before the styles registry lands.
        from app.services.presentation_styles import get_style

        style_default = get_style(presentation_style).default_design_language
    lang_key = resolve_design_language(design_language, style_default, text)
    lang = get_language(lang_key)

    base_hue = _hue_for(text)
    primary, secondary, accent, bg_light, bg_dark = _generate_palette(base_hue, lang.palette_strategy)
    heading, body = _FONT_FOR_LANGUAGE.get(lang_key, ("Aptos Display", "Aptos"))

    return BrandDNA(
        colors={
            "primary": primary,
            "secondary": secondary,
            "accent": accent,
            "background_dark": bg_dark,
            "background_light": bg_light,
            "text_dark": primary,
            "text_light": "FFFFFF",
        },
        fonts={"heading": heading, "body": body},
        design_notes=(
            f"Freeform theme — design language: {lang.label}; "
            f"palette seeded from topic hue {base_hue}deg ({lang.palette_strategy})."
        ),
        layout_profile={
            "design_language": lang_key,
            "palette_strategy": lang.palette_strategy,
            "palette": {
                "primary": primary,
                "secondary": secondary,
                "accent": accent,
                "background_light": bg_light,
                "background_dark": bg_dark,
            },
        },
    )


def _hue_for(text: str) -> int:
    for needles, hue in _TOPIC_HUE:
        if any(n in text for n in needles):
            return hue
    return _DEFAULT_HUE


def _hsl(hue: float, sat: float, light: float) -> str:
    r, g, b = colorsys.hls_to_rgb((hue % 360) / 360.0, light, sat)
    return "%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255))


def _generate_palette(base_hue: int, strategy: str) -> tuple[str, str, str, str, str]:
    """Return (primary, secondary, accent, background_light, background_dark)."""
    prim_s, prim_l = 0.42, 0.20
    sec_off, sec_s, sec_l = 10, 0.52, 0.42
    acc_hue, acc_s, acc_l = 40, 0.72, 0.52
    bg_light_l = 0.95
    bg_dark_s, bg_dark_l = 0.45, 0.10

    if strategy == "high_contrast":
        prim_s, prim_l = 0.50, 0.13
        sec_s = 0.62
        acc_hue, acc_s = 8, 0.78
        bg_dark_l = 0.08
    elif strategy == "warm":
        sec_off = -14
        acc_hue, acc_s = 28, 0.76
    elif strategy == "cool":
        sec_off = 16
        acc_hue = 42
    elif strategy == "duotone":
        acc_hue, acc_s, acc_l = base_hue + 30, 0.55, 0.50
    elif strategy == "editorial":
        prim_s, sec_s = 0.30, 0.34
        acc_hue, acc_s = 30, 0.55

    primary = _hsl(base_hue, prim_s, prim_l)
    secondary = _hsl(base_hue + sec_off, sec_s, sec_l)
    accent = _hsl(acc_hue, acc_s, acc_l)
    bg_light = _hsl(base_hue, 0.16, bg_light_l)
    bg_dark = _hsl(base_hue, bg_dark_s, bg_dark_l)
    return primary, secondary, accent, bg_light, bg_dark


def _theme_text(bundle: DocumentBundle, instructions: str) -> str:
    parts = [instructions, bundle.metadata.title or ""]
    parts.extend(section.title for section in bundle.sections[:20])
    parts.extend(section.content[:500] for section in bundle.sections[:8])
    parts.extend(metric.label for metric in bundle.metrics[:12])
    return " ".join(parts).lower()
