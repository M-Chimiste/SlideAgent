from pptx import Presentation

from app.models.brand import BrandDNA
from app.models.outline import SlideOutline
from app.services.pptx_native import geometry as geo
from app.services.pptx_native import primitives as prim
from app.services.pptx_native import theme as th
from app.services.pptx_native.renderer import NativePptxRenderer


def _brand(dl: str = "editorial_serif") -> BrandDNA:
    return BrandDNA(
        colors={"primary": "14213D", "secondary": "1F7A8C", "accent": "C8893B", "background_light": "EAEEF5"},
        fonts={"heading": "Aptos Display", "body": "Aptos"},
        layout_profile={"design_language": dl},
    )


def _outline(i: int, primitive: str, title: str, bullets: list[str]) -> SlideOutline:
    return SlideOutline(
        id=f"s{i}", job_id="j", created_at="t", slide_index=i, mode="flexible", label=title,
        content_json={
            "action_title": title, "pinned_primitive": primitive, "slide_type": primitive,
            "narrative_role": "evidence", "subheading": "context here", "bullets": bullets,
            "metrics": [{"value": "85%", "label": "adoption", "description": "of teams"}] if primitive in ("metrics", "big_stat") else [],
            "exhibit_spec": {"columns": ["A", "B"], "rows": [{"label": "x", "values": ["1"]}]} if primitive == "table" else {},
        },
        layout_json={},
    )


def test_px_to_inch_is_96_per_inch():
    assert geo.px(96) == 1.0
    assert geo.px(48) == 0.5


def test_parse_padding_shorthand():
    assert geo.parse_padding_px("70px 84px 60px") == (70, 84, 60, 84)
    assert geo.parse_padding_px("26px 28px") == (26, 28, 26, 28)
    assert geo.parse_padding_px("40px") == (40, 40, 40, 40)


def test_content_area_insets_by_padding():
    area = geo.content_area("70px 84px 60px")
    assert round(area.x, 3) == round(geo.px(84), 3)
    assert round(area.y, 3) == round(geo.px(70), 3)
    assert round(area.right, 3) == round(geo.SLIDE_W_IN - geo.px(84), 3)
    assert round(area.bottom, 3) == round(geo.SLIDE_H_IN - geo.px(60), 3)


def test_grid_reflows_by_count():
    area = geo.Rect(0, 0, 12, 6)
    one_row = geo.grid(3, 3, area, gap=0.2)
    assert len(one_row) == 3
    # equal widths, single row (same y)
    assert len({round(c.w, 4) for c in one_row}) == 1
    assert len({round(c.y, 4) for c in one_row}) == 1
    two_by_two = geo.grid(4, 2, area, gap=0.2)
    assert len(two_by_two) == 4
    assert len({round(c.y, 4) for c in two_by_two}) == 2  # two rows


def test_column_split_respects_ratios():
    area = geo.Rect(0, 0, 10, 6)
    cols = geo.column_split(area, [0.82, 1.18], gap=0.0)
    assert round(cols[1].w / cols[0].w, 2) == round(1.18 / 0.82, 2)
    assert round(cols[0].w + cols[1].w, 4) == 10.0


def test_stack_rows():
    area = geo.Rect(0, 0, 10, 6)
    rows = geo.stack(area, 4, gap=0.1)
    assert len(rows) == 4
    assert all(round(r.w, 4) == 10.0 for r in rows)
    assert rows[1].y > rows[0].y


def test_theme_pt_scales_display_by_heading_scale():
    assert th.pt(60) == 45.0           # 60px * 0.75
    assert th.pt(60, 1.14) == 51.3     # bold_minimal scale


def test_theme_helpers_resolve_from_design_language():
    # a freeform-style brand carrying a design language
    brand = BrandDNA(
        colors={"primary": "14213D", "secondary": "1F7A8C", "accent": "C8893B", "background_light": "EAEEF5"},
        fonts={"heading": "Newsreader", "body": "Inter"},
        layout_profile={"design_language": "bold_minimal"},
    )
    theme = th.resolve_theme(brand)
    assert theme.card_radius == 4  # bold_minimal
    area = th.slide_content_area(theme)
    assert area.w < geo.SLIDE_W_IN  # inset by slide padding
    assert th.card_gap_in(theme) > 0


def test_native_render_is_editable_no_images(tmp_path):
    outs = [
        _outline(0, "cover", "Beyond Vibe Coding", []),
        _outline(1, "cards", "Three failure modes", ["Hallucinations spike with ambiguity", "Silent integration breaks", "Developer becomes a PM"]),
        _outline(2, "statement", "Structured context is the antidote", ["Persistent memory beats history", "A rules file removes ambiguity"]),
        _outline(3, "rows", "The Memory Bank architecture", ["Files form a dependency graph", "Brief anchors scope", "Active context captures state"]),
        _outline(4, "quote", "It forces you to clarify your thinking", ["It forces you to clarify your own thinking before the model writes a line"]),
        _outline(5, "closing", "Commit to persistent context", ["Adopt a rules file", "Stand up a Memory Bank"]),
    ]
    out = tmp_path / "deck.pptx"
    warnings = NativePptxRenderer().render(outs, _brand(), out)
    assert warnings == []
    res = Presentation(out.as_posix())
    slides = list(res.slides)
    assert len(slides) == len(outs)
    for s in slides:
        # editable: real text frames, zero full-bleed pictures
        assert sum(1 for sh in s.shapes if sh.shape_type == 13) == 0
        assert any(sh.has_text_frame and sh.text_frame.text.strip() for sh in s.shapes)


def test_native_render_covers_every_primitive(tmp_path):
    outs = [_outline(i, p, f"{p} slide title", ["Point one is a finished thought", "Point two is also complete", "Point three rounds it out"])
            for i, p in enumerate(prim.BUILDERS)]
    out = tmp_path / "all.pptx"
    warnings = NativePptxRenderer().render(outs, _brand(), out)
    assert warnings == []  # every primitive builds without falling back
    assert len(list(Presentation(out.as_posix()).slides)) == len(prim.BUILDERS)


def test_design_language_changes_native_geometry(tmp_path):
    # bold_minimal (radius 4, scale 1.14) vs editorial_serif (radius 16) -> different theme tokens
    bold = th.resolve_theme(_brand("bold_minimal"))
    editorial = th.resolve_theme(_brand("editorial_serif"))
    assert bold.card_radius != editorial.card_radius
    assert th.pt(60, bold.heading_scale) > th.pt(60, editorial.heading_scale)
