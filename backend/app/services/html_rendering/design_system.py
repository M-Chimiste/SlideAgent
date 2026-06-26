"""Design tokens and theme resolution for HTML-rendered slides.

Seeds a cohesive palette from ``BrandDNA`` (so brand mode is honored) while
falling back to a refined editorial house style — deep ink, cool teal, warm
gold, and cool-light surfaces — that matches the reference deck. Also owns the
deliberate dark/light *rhythm*: punctuation slides (cover, statements, quotes,
dividers, closing) go dark; working content slides go light, with smoothing so
the deck never stacks three darks in a row.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.brand import BrandDNA
from app.services.design_languages import LANGUAGES, get_language

# Roles/families that read best as full-bleed dark "punctuation" slides.
_DARK_FAMILIES = {
    "editorial_cover",
    "section_divider",
    "spotlight_quote",
    "statement_canvas",
    "path_forward_close",
    "metric_signal",
    "reframe_split",
    "circular_trap",
}
_DARK_ROLES = {"cover", "closing", "section", "divider", "decision", "problem"}


def _clean_hex(value: str | None, fallback: str) -> str:
    if not value or not isinstance(value, str):
        return fallback
    h = value.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return fallback
    try:
        int(h, 16)
    except ValueError:
        return fallback
    return h.upper()


def _rgb(h: str) -> tuple[int, int, int]:
    h = h.strip().lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hexstr(r: int, g: int, b: int) -> str:
    return "#%02X%02X%02X" % (
        max(0, min(255, int(r))),
        max(0, min(255, int(g))),
        max(0, min(255, int(b))),
    )


def _mix(h: str, target: tuple[int, int, int], amount: float) -> str:
    r, g, b = _rgb(h)
    tr, tg, tb = target
    return _hexstr(
        r + (tr - r) * amount,
        g + (tg - g) * amount,
        b + (tb - b) * amount,
    )


def lighten(h: str, amount: float) -> str:
    return _mix(h, (255, 255, 255), amount)


def darken(h: str, amount: float) -> str:
    return _mix(h, (0, 0, 0), amount)


def rgba(h: str, alpha: float) -> str:
    r, g, b = _rgb(h)
    return f"rgba({r},{g},{b},{alpha:g})"


def _luminance(h: str) -> float:
    r, g, b = (c / 255 for c in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def readable_on(h: str, dark: str = "#14213D", light: str = "#FFFFFF") -> str:
    return light if _luminance(h) < 0.55 else dark


def _is_vivid(h: str) -> bool:
    r, g, b = _rgb(h)
    mx, mn = max(r, g, b), min(r, g, b)
    if mx == 0:
        return False
    sat = (mx - mn) / mx
    return sat > 0.25 and 28 < _luminance(h) * 255 < 210


@dataclass
class Theme:
    # core hues
    ink: str          # deep dark surface base (navy/ink)
    ink_grad: str     # second stop for the dark gradient
    teal: str         # cool accent
    gold: str         # warm accent
    light: str        # light surface base
    light_grad: str   # second stop for the light gradient
    # text
    text_dark: str
    text_dark_muted: str
    text_light: str
    text_light_muted: str
    # cards
    card_light: str
    card_light_alt: str
    card_border_light: str
    card_dark: str
    card_border_dark: str
    # fonts
    serif: str
    sans: str
    mono: str
    # assets
    logo_path: str | None = None
    # design-language presets (defaults == editorial_serif / current house style)
    heading_scale: float = 1.0
    headline_weight: int = 600
    eyebrow_spacing: str = "0.20em"
    card_radius: int = 16
    card_padding: str = "26px 28px"
    card_gap: int = 22
    slide_padding: str = "70px 84px 60px"
    cover_padding: str = "70px 90px"
    dark_angle: int = 155
    light_angle: int = 165
    motif: str = "rings"
    motif_slots: tuple[str, ...] = ("cover", "closing")
    dark_base: str = ""  # explicit dark-gradient base (freeform); "" → derive from ink

    def background(self, mode: str) -> str:
        if mode == "dark":
            base = self.dark_base or self.ink
            return f"linear-gradient({self.dark_angle}deg, {self.ink_grad} 0%, {base} 60%, {darken(base, 0.18)} 100%)"
        return f"linear-gradient({self.light_angle}deg, {self.light_grad} 0%, {self.light} 100%)"

    def eyebrow_color(self, mode: str) -> str:
        return self.gold if mode == "dark" else self.teal

    def heading_color(self, mode: str) -> str:
        return self.text_light if mode == "dark" else self.text_dark

    def body_color(self, mode: str) -> str:
        return self.text_light_muted if mode == "dark" else self.text_dark_muted

    def card_bg(self, mode: str) -> str:
        return self.card_dark if mode == "dark" else self.card_light

    def card_border(self, mode: str) -> str:
        return self.card_border_dark if mode == "dark" else self.card_border_light


def resolve_theme(brand: BrandDNA) -> Theme:
    colors = brand.colors
    primary = _clean_hex(colors.primary, "14213D")
    accent = _clean_hex(colors.accent, "C8893B")
    secondary = _clean_hex(colors.secondary, "44506A")
    bg_light = _clean_hex(colors.background_light, "EAEEF5")

    # Resolve the design-language preset. Freeform decks stamp a language into
    # ``layout_profile``; brand templates carry none and fall to editorial_serif
    # so analyzed output stays byte-for-byte identical.
    profile = brand.layout_profile or {}
    lang_key = profile.get("design_language")
    has_design_language = bool(lang_key) and lang_key in LANGUAGES
    lang = get_language(lang_key)

    # Cool accent: freeform carries a generated secondary we trust; brand keeps
    # the vivid-or-house-teal guard so analyzed templates render stably.
    if has_design_language:
        teal = f"#{secondary}"
    else:
        teal = f"#{secondary}" if _is_vivid(secondary) else "#1F7A8C"
    gold = f"#{accent}"
    ink = f"#{primary}"

    # Dark gradient base: honor a freeform-supplied background_dark; otherwise
    # derive from the primary as before (dark_base="" → background() uses ink).
    bg_dark = _clean_hex(getattr(colors, "background_dark", None), "")
    dark_base = f"#{bg_dark}" if (has_design_language and bg_dark) else ""
    gradient_base = dark_base or ink

    # Lighten the light background a touch so white cards pop with shadow.
    light = f"#{bg_light}"
    light_grad = lighten(light, 0.45)

    heading_font = (brand.fonts.heading or "").strip()
    body_font = (brand.fonts.body or "").strip()
    if has_design_language:
        # Freeform: the design language owns typography.
        serif = lang.serif_fallback
        sans = lang.sans_fallback
    else:
        # Brand: honor the analyzed brand fonts, then fall back.
        serif = (f'"{heading_font}", ' if heading_font else "") + lang.serif_fallback
        sans = (f'"{body_font}", ' if body_font else "") + lang.sans_fallback

    return Theme(
        ink=ink,
        ink_grad=lighten(gradient_base, 0.06),
        teal=teal,
        gold=gold,
        light=light,
        light_grad=light_grad,
        text_dark=darken(ink, 0.05),
        text_dark_muted=rgba(darken(ink, 0.0), 0.62),
        text_light="#FFFFFF",
        text_light_muted="rgba(233,239,245,0.74)",
        card_light="#FFFFFF",
        card_light_alt=lighten(light, 0.55),
        card_border_light=rgba(ink, 0.10),
        card_dark=rgba("#FFFFFF", 0.055),
        card_border_dark="rgba(255,255,255,0.12)",
        serif=serif,
        sans=sans,
        mono=lang.mono,
        logo_path=(brand.logo.path if brand.logo else None),
        heading_scale=lang.heading_scale,
        headline_weight=lang.headline_weight,
        eyebrow_spacing=lang.eyebrow_spacing,
        card_radius=lang.card_radius,
        card_padding=lang.card_padding,
        card_gap=lang.card_gap,
        slide_padding=lang.slide_padding,
        cover_padding=lang.cover_padding,
        dark_angle=lang.dark_angle,
        light_angle=lang.light_angle,
        motif=lang.motif,
        motif_slots=lang.motif_slots,
        dark_base=dark_base,
    )


def slide_mode(role: str | None, family: str | None, index: int, total: int) -> str:
    """Base dark/light choice before deck-level smoothing."""
    fam = (family or "").lower()
    rl = (role or "").lower()
    if index == 0:
        return "dark"
    if index == total - 1:
        return "dark"
    if fam in _DARK_FAMILIES or rl in _DARK_ROLES:
        return "dark"
    return "light"


def resolve_modes(slides: list[tuple[str | None, str | None]]) -> list[str]:
    """Resolve per-slide dark/light modes with rhythm smoothing.

    Avoids 3+ consecutive darks and isolated single-light "flicker" between two
    darks, so the deck alternates with intent rather than at random.
    """
    total = len(slides)
    modes = [slide_mode(role, fam, i, total) for i, (role, fam) in enumerate(slides)]
    # break up runs of 3+ darks (keep the first; lighten the middle)
    run = 0
    for i, m in enumerate(modes):
        if m == "dark":
            run += 1
            if run >= 3 and i not in (0, total - 1):
                modes[i] = "light"
                run = 0
        else:
            run = 0
    return modes
