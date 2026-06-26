"""Tests for the HTML slide renderer (design-system path)."""

import tempfile
from pathlib import Path

import pytest

from app.config import Settings
from app.models.brand import BrandDNA
from app.models.outline import SlideOutline
from app.models.template import TemplateProfile
from app.services.html_rendering import HtmlRenderError, HtmlSlideRenderer, find_chrome
from app.services.html_rendering.templates import _fit, _lead_body, _normalize_items, render_slide_html
from app.services.html_rendering.design_system import resolve_modes, resolve_theme
from app.services.pptx_builder import PptxBuilder
from app.workers.node_runner import NodePptxGenRunner


def _outline(index, content):
    return SlideOutline(
        id=f"s{index}",
        job_id="job",
        slide_index=index,
        mode="flexible",
        label=content.get("action_title", ""),
        content_json=content,
        layout_json={"composition_family": content.get("composition_family", "")},
        created_at="t",
    )


def _sample_outlines():
    return [
        _outline(0, {
            "slide_type": "cover", "narrative_role": "cover",
            "composition_family": "editorial_cover",
            "action_title": "Bootstrapping Benchmarks",
            "subheading": "Executive briefing",
            "bullets": ["Model contract", "Harness interface", "Implicit ground truth"],
        }),
        _outline(1, {
            "narrative_role": "problem", "composition_family": "circular_trap",
            "action_title": "Synthetic benchmarks create circular validation loops",
            "subheading": "Why generated tests fall short",
            "exhibit_spec": {"type": "callouts", "points": [
                "Synthetic benchmarks can create circular validation loops without grounding.",
                "Source-grounded harnesses evaluate models against real evidence.",
                "Benchmark quality improves when cases come from real workflows.",
            ]},
        }),
        _outline(2, {
            "narrative_role": "evidence", "composition_family": "why_it_matters_cards",
            "action_title": "Four reasons the harness wins",
            "exhibit_spec": {"type": "icon_rows", "items": [
                "Data catalogs make discovery easier to scale across sources.",
                "Schema discovery determines how reliably agents find evidence.",
                "Confidence calibration matters because evidence varies in certainty.",
                "Governance keeps the benchmark auditable end to end.",
            ]},
        }),
        _outline(3, {
            "narrative_role": "closing", "composition_family": "path_forward_close",
            "action_title": "Adopt the governed benchmark framework",
            "exhibit_spec": {"type": "recommendation",
                             "recommendation": "Bootstrap ground truth from proprietary data.",
                             "next_steps": ["Turn data into reusable evidence.",
                                            "Match validation to evidence type."],
                             "decision_ask": "Approve the first governed pilot."},
        }),
    ]


def test_new_primitives_render_for_their_families():
    theme = resolve_theme(BrandDNA(layout_profile={"design_language": "modern_geometric"}))
    items = {"bullets": ["Alpha leads the way", "Beta follows behind", "Gamma trails last"]}
    cases = {
        "decision_matrix": 'class="matrix"',
        "lifecycle_timeline": 'class="timeline"',
        "architecture_layers": 'class="layers"',
        "reframe_comparison": 'class="columns',
    }
    for family, marker in cases.items():
        content = {"action_title": "T", "composition_family": family, **items}
        html = render_slide_html(_outline(0, content), theme, "light", 1, 5)
        assert marker in html, f"{family} did not render its primitive"


def test_choose_primitive_history_breaks_card_monotony():
    theme = resolve_theme(BrandDNA())
    history: list[str] = []
    content = {
        "action_title": "Why it matters",
        "composition_family": "why_it_matters_cards",
        "bullets": ["One reason holds", "Two reasons apply", "Three reasons remain"],
    }
    for i in range(6):
        render_slide_html(_outline(i, content), theme, "light", i, 6, history)
    # without rotation all six would be "cards"; the cap forces variety
    assert len(set(history)) >= 2


def test_design_language_preset_changes_css_geometry():
    from app.services.html_rendering.css import build_css

    editorial = build_css(resolve_theme(BrandDNA()))
    bold = build_css(resolve_theme(BrandDNA(layout_profile={"design_language": "bold_minimal"})))
    assert "border-radius: 16px" in editorial
    assert "border-radius: 4px" in bold  # bold_minimal card_radius
    assert editorial != bold


def test_lead_body_splits_subject_phrase():
    title, body = _lead_body("Synthetic benchmarks can create circular validation loops without grounding.")
    assert title == "Synthetic benchmarks"
    assert body.startswith("Can create")


def test_lead_body_idiomatic_verb_keeps_whole_sentence():
    # "in turn" must not be split into a dangling lead ("Three files, in")
    lead, body = _lead_body("Three files, in turn, feed into active_context.md and capture state.")
    assert lead == ""
    assert "in turn" in body.lower()


def test_lead_body_does_not_split_inside_parentheses():
    lead, body = _lead_body("Tests pass (or there are no tests) before the merge step.")
    assert lead == ""
    assert "(or there are no tests)" in body


def test_fit_trims_to_first_sentence_when_long():
    text = "First complete thought here is fine. A second sentence that overflows the card."
    assert _fit(text, 40) == "First complete thought here is fine."
    # short text is untouched
    assert _fit("Short body.", 40) == "Short body."


def test_lead_body_no_verb_keeps_sentence():
    title, body = _lead_body("Benchmarks everywhere")
    assert title == ""
    assert body == "Benchmarks everywhere"


def test_normalize_items_from_callouts():
    items = _normalize_items({"exhibit_spec": {"type": "callouts", "points": [
        "Data catalogs make discovery easier.", "Schema discovery determines reliability."]}})
    assert len(items) == 2
    assert items[0]["title"] == "Data catalogs"


def test_resolve_modes_rhythm():
    keyed = [("cover", "editorial_cover")] + [("evidence", "why_it_matters_cards")] * 3 + [("closing", "path_forward_close")]
    modes = resolve_modes(keyed)
    assert modes[0] == "dark"
    assert modes[-1] == "dark"
    # no run of 3+ darks
    assert "dark dark dark" not in " ".join(modes)


def test_build_html_structure():
    renderer = HtmlSlideRenderer()
    html = renderer.build_html(_sample_outlines(), BrandDNA())
    assert "<div class='deck'>" in html
    assert html.count('class="slide') == 4
    assert "slide dark cover" in html  # cover is dark
    assert "Bootstrapping Benchmarks" in html
    assert "Synthetic benchmarks" in html  # derived card lead present


def test_render_single_slide_does_not_raise():
    theme = resolve_theme(BrandDNA())
    for i, outline in enumerate(_sample_outlines()):
        html = render_slide_html(outline, theme, "light", i, 4)
        assert html.startswith("<section")


def test_pptx_builder_html_fallback_to_authored():
    settings = Settings()
    builder = PptxBuilder(NodePptxGenRunner(settings), renderer_engine="html")

    def boom(*a, **k):
        raise HtmlRenderError("simulated: no chrome")

    builder.html_renderer.render = boom
    tpl = TemplateProfile(id="__freeform__", name="Freeform", type="freeform",
                          brand=BrandDNA(), slides=[], source_file="", created_at="t", updated_at="t")
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "output.pptx"
        warnings = builder.build_deck(tpl, _sample_outlines(), out, Path(d))
        assert out.exists()
        assert any(w.get("field") == "render_engine" for w in warnings)


@pytest.mark.skipif(find_chrome() is None, reason="headless Chrome not available")
def test_full_html_render_produces_pptx():
    from pptx import Presentation

    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "output.pptx"
        warnings = HtmlSlideRenderer().render(_sample_outlines(), BrandDNA(), out)
        assert out.exists()
        assert len(Presentation(out.as_posix()).slides) == 4
        assert not [w for w in warnings if w.get("severity") == "error"]
