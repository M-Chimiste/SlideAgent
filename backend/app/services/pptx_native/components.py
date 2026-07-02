"""Native polish components — editable python-pptx shapes that reproduce the
HTML/CSS design system (rounded cards, soft shadows, gradient backgrounds, badges,
fit-aware text, motifs). All output is real, selectable, editable PowerPoint.
"""

from __future__ import annotations

from dataclasses import dataclass

from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml import parse_xml
from pptx.oxml.ns import nsdecls, qn
from pptx.util import Inches, Pt

from app.services.slide_design import fit
from app.services.slide_design.design_system import (
    Theme,
    _clean_hex,
    _rgb,
    darken,
)

from .geometry import Rect

_RGB = tuple[int, int, int]


# --------------------------------------------------------------------------- #
# Color resolution (handles hex + rgba(), blending alpha over a known bg)
# --------------------------------------------------------------------------- #
def _resolve(value: str, over: _RGB) -> _RGB:
    s = str(value or "").strip()
    if s.startswith("rgba") or s.startswith("rgb"):
        inner = s[s.find("(") + 1: s.find(")")]
        nums = [n.strip() for n in inner.split(",")]
        r, g, b = (int(float(nums[i])) for i in range(3))
        a = float(nums[3]) if len(nums) > 3 else 1.0
        if a < 1.0:
            r = round(r * a + over[0] * (1 - a))
            g = round(g * a + over[1] * (1 - a))
            b = round(b * a + over[2] * (1 - a))
        return (r, g, b)
    return _rgb(_clean_hex(s, "000000"))


def _color(value: str, over: _RGB) -> RGBColor:
    return RGBColor(*_resolve(value, over))


@dataclass
class Palette:
    mode: str
    bg: _RGB
    bg_stops: list[tuple[float, str]]   # (pos 0..1, hex) for the gradient
    headline: RGBColor
    body: RGBColor
    eyebrow: RGBColor
    teal: RGBColor
    gold: RGBColor
    card_bg: RGBColor
    card_border: RGBColor
    on_accent: RGBColor


def palette(theme: Theme, mode: str) -> Palette:
    if mode == "dark":
        base = _clean_hex(theme.dark_base or theme.ink, "14213D")
        bg = _rgb(base)
        stops = [(0.0, _clean_hex(theme.ink_grad, base)), (0.6, base), (1.0, _clean_hex(darken(f"#{base}", 0.18), base))]
    else:
        base = _clean_hex(theme.light, "EAEEF5")
        bg = _rgb(base)
        stops = [(0.0, _clean_hex(theme.light_grad, base)), (1.0, base)]
    return Palette(
        mode=mode,
        bg=bg,
        bg_stops=stops,
        headline=_color(theme.heading_color(mode), bg),
        body=_color(theme.body_color(mode), bg),
        eyebrow=_color(theme.eyebrow_color(mode), bg),
        teal=_color(theme.teal, bg),
        gold=_color(theme.gold, bg),
        card_bg=_color(theme.card_bg(mode), bg),
        card_border=_color(theme.card_border(mode), bg),
        on_accent=RGBColor(0xFF, 0xFF, 0xFF),
    )


# --------------------------------------------------------------------------- #
# Low-level OOXML helpers (gradient / shadow) — keep shapes editable
# --------------------------------------------------------------------------- #
def _spPr(shape):
    return shape._element.spPr


def _clear_fill(spPr) -> None:
    for tag in ("a:noFill", "a:solidFill", "a:gradFill", "a:blipFill", "a:pattFill", "a:grpFill"):
        for el in spPr.findall(qn(tag)):
            spPr.remove(el)


def apply_gradient(shape, stops: list[tuple[float, str]], css_angle: int) -> None:
    spPr = _spPr(shape)
    _clear_fill(spPr)
    gs = "".join(
        f'<a:gs pos="{int(max(0.0, min(1.0, pos)) * 100000)}"><a:srgbClr val="{_clean_hex(hexv, "000000")}"/></a:gs>'
        for pos, hexv in stops
    )
    ang = int(((css_angle - 90) % 360) * 60000)
    xml = (
        f'<a:gradFill {nsdecls("a")}><a:gsLst>{gs}</a:gsLst>'
        f'<a:lin ang="{ang}" scaled="1"/></a:gradFill>'
    )
    ln = spPr.find(qn("a:ln"))
    node = parse_xml(xml)
    if ln is not None:
        ln.addprevious(node)
    else:
        spPr.append(node)


def apply_shadow(shape, *, blur_pt=9.0, dist_pt=4.0, css_dir=90, color="14213D", alpha_pct=18) -> None:
    spPr = _spPr(shape)
    for el in spPr.findall(qn("a:effectLst")):
        spPr.remove(el)
    ang = int(((css_dir - 90) % 360) * 60000)
    xml = (
        f'<a:effectLst {nsdecls("a")}><a:outerShdw blurRad="{int(blur_pt * 12700)}" '
        f'dist="{int(dist_pt * 12700)}" dir="{ang}" rotWithShape="0">'
        f'<a:srgbClr val="{_clean_hex(color, "14213D")}"><a:alpha val="{int(alpha_pct * 1000)}"/></a:srgbClr>'
        f'</a:outerShdw></a:effectLst>'
    )
    spPr.append(parse_xml(xml))


def _no_shadow(shape) -> None:
    shape.shadow.inherit = False


# --------------------------------------------------------------------------- #
# Components
# --------------------------------------------------------------------------- #
def add_background(slide, theme: Theme, pal: Palette) -> None:
    rect = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0),
                                  Inches(13.333), Inches(7.5))
    rect.line.fill.background()
    _no_shadow(rect)
    if len(pal.bg_stops) >= 2:
        angle = theme.dark_angle if pal.mode == "dark" else theme.light_angle
        apply_gradient(rect, pal.bg_stops, angle)
    else:
        rect.fill.solid()
        rect.fill.fore_color.rgb = RGBColor(*pal.bg)
    # send to back
    spTree = slide.shapes._spTree
    spTree.remove(rect._element)
    spTree.insert(2, rect._element)


def add_card(slide, rect: Rect, theme: Theme, pal: Palette, *, radius_in: float | None = None,
             fill: RGBColor | None = None, shadow: bool = True):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(rect.x), Inches(rect.y), Inches(rect.w), Inches(rect.h)
    )
    r = radius_in if radius_in is not None else (theme.card_radius / 96.0)
    try:
        shape.adjustments[0] = max(0.0, min(0.5, r / max(0.01, min(rect.w, rect.h))))
    except Exception:
        pass
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill if fill is not None else pal.card_bg
    shape.line.color.rgb = pal.card_border
    shape.line.width = Pt(0.75)
    if shadow and pal.mode == "light":
        apply_shadow(shape, blur_pt=10, dist_pt=4, color="0F1E32", alpha_pct=12)
    else:
        _no_shadow(shape)
    return shape


def add_circle(slide, cx: float, cy: float, d: float, color: RGBColor):
    shape = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(cx - d / 2), Inches(cy - d / 2), Inches(d), Inches(d))
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    _no_shadow(shape)
    return shape


def add_icon_circle(slide, cx: float, cy: float, d: float, color: RGBColor, glyph: str,
                    *, text_color: RGBColor | None = None, icon_path=None):
    """Accent circle carrying a real icon (react-icons PNG) when available,
    else a meaning glyph or monogram — never an empty placeholder dot."""
    add_circle(slide, cx, cy, d, color)
    if icon_path is not None:
        s = d * 0.52
        try:
            slide.shapes.add_picture(str(icon_path), Inches(cx - s / 2), Inches(cy - s / 2),
                                     Inches(s), Inches(s))
            return
        except Exception:
            pass  # unreadable cache file -> glyph fallback below
    if not glyph:
        return
    box = slide.shapes.add_textbox(Inches(cx - d / 2), Inches(cy - d / 2), Inches(d), Inches(d))
    tf = box.text_frame
    tf.word_wrap = False
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    for margin in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
        setattr(tf, margin, 0)
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    run = p.add_run()
    run.text = glyph[:1]
    run.font.size = Pt(max(10, d * 72 * 0.44))
    run.font.bold = True
    run.font.color.rgb = text_color or RGBColor(0xFF, 0xFF, 0xFF)


def add_badge(slide, cx: float, cy: float, d: float, color: RGBColor, *, number: str | None = None,
              text_color: RGBColor | None = None):
    add_circle(slide, cx, cy, d, color)
    if number:
        box = slide.shapes.add_textbox(Inches(cx - d / 2), Inches(cy - d / 2), Inches(d), Inches(d))
        tf = box.text_frame
        tf.word_wrap = False
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        run = p.add_run()
        run.text = str(number)
        run.font.size = Pt(max(10, d * 72 * 0.42))
        run.font.bold = True
        run.font.color.rgb = text_color or RGBColor(0xFF, 0xFF, 0xFF)


@dataclass
class Para:
    text: str
    size_pt: float
    color: RGBColor
    bold: bool = False
    font: str | None = None
    italic: bool = False
    align: PP_ALIGN = PP_ALIGN.LEFT
    space_after_pt: float = 4.0
    line_spacing: float = 1.12


def add_paragraphs(slide, rect: Rect, paras: list[Para], *, anchor: MSO_ANCHOR = MSO_ANCHOR.TOP,
                   wrap: bool = True):
    box = slide.shapes.add_textbox(Inches(rect.x), Inches(rect.y), Inches(rect.w), Inches(rect.h))
    tf = box.text_frame
    tf.word_wrap = wrap
    tf.vertical_anchor = anchor
    for margin in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
        setattr(tf, margin, 0)
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = para.align
        p.line_spacing = para.line_spacing
        p.space_after = Pt(para.space_after_pt)
        run = p.add_run()
        run.text = para.text
        run.font.size = Pt(para.size_pt)
        run.font.bold = para.bold
        run.font.italic = para.italic
        run.font.color.rgb = para.color
        if para.font:
            run.font.name = para.font
    return box


def fit_size(text: str, rect: Rect, base_pt: float, *, min_pt: float = 9.0) -> float:
    """Shrink ``base_pt`` until ``text`` is estimated to fit ``rect`` (reuses the
    shared fit estimator), so native text never overflows its box."""
    size = base_pt
    width_pt = rect.w * 72
    height_pt = rect.h * 72
    while size > min_pt:
        if fit.estimate_lines([text], width_pt, size) <= fit.capacity_lines(height_pt, size) + 0.5:
            return round(size, 1)
        size -= 1
    return round(min_pt, 1)


def add_motif(slide, theme: Theme, slot: str, pal: Palette) -> None:
    # Decorative corner accent. All coordinates stay within the 13.333 x 7.5in
    # canvas — off-canvas shapes are flagged CRITICAL by the slide-bounds audit
    # and can render unpredictably across viewers/exports.
    if theme.motif == "none" or slot not in theme.motif_slots:
        return
    color = pal.gold
    if theme.motif == "rings":
        # concentric rings anchored to the top-right, sized so the largest stays
        # in-bounds and above the header band (title starts ~2.7in on cover/section).
        cx, cy = 11.95, 1.32
        for d in (2.5, 1.8, 1.15):
            ring = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(cx - d / 2), Inches(cy - d / 2), Inches(d), Inches(d))
            ring.fill.background()
            ring.line.color.rgb = color
            ring.line.width = Pt(1.0)
            _no_shadow(ring)
    elif theme.motif == "grid":
        for gx in range(8):
            for gy in range(4):
                add_circle(slide, 11.4 + gx * 0.22, 0.35 + gy * 0.22, 0.03, color)
    elif theme.motif == "diagonal":
        for i in range(6):
            ln = slide.shapes.add_connector(2, Inches(11.4 + i * 0.16), Inches(0.2), Inches(12.7 + i * 0.16), Inches(1.6))
            ln.line.color.rgb = color
            ln.line.width = Pt(0.75)
            _no_shadow(ln)
