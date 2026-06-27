from app.services.pptx_native.primitives import _short
from app.services.slide_design.content import (
    _fit,
    _lead_body,
    _normalize_items,
    _trim_dangling,
)
from app.services.slide_design.design_system import resolve_modes


def test_trim_dangling_drops_trailing_connective():
    assert _trim_dangling("Captures user problem, experience goals, a") == "Captures user problem, experience goals"
    assert _trim_dangling("Records architecture, patterns, and the") == "Records architecture, patterns"


def test_trim_dangling_preserves_finished_sentences():
    # a finished thought (incl. its terminal period) must be left untouched
    assert _trim_dangling("Project context persists.") == "Project context persists."
    assert _trim_dangling("A complete sentence here.") == "A complete sentence here."


def test_short_truncates_at_word_boundary_without_dangling():
    long = "ProductContext.md Captures user problem, experience goals, and project scope"
    out = _short(long, 60)
    assert len(out) <= 60
    assert " " in out and not long[: len(out)].endswith("a")  # not a mid-word cut
    assert out == "ProductContext.md Captures user problem, experience goals"


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


def test_lead_body_no_verb_keeps_sentence():
    title, body = _lead_body("Benchmarks everywhere")
    assert title == ""
    assert body == "Benchmarks everywhere"


def test_fit_trims_to_first_sentence_when_long():
    text = "First complete thought here is fine. A second sentence that overflows the card."
    assert _fit(text, 40) == "First complete thought here is fine."
    assert _fit("Short body.", 40) == "Short body."


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
    assert "dark dark dark" not in " ".join(modes)
