from app.services.slide_design import fit


def test_estimator_golden_values():
    # mirrors rendered_slide_audit._text_box_has_overflow_risk arithmetic
    assert fit.chars_per_line(300, 15.5) == 37
    assert fit.estimate_lines(["x" * 100], 300, 15.5) == 3
    assert round(fit.capacity_lines(100, 15.5), 2) == 5.47


def test_fits_true_for_short_false_for_overflow():
    assert fit.fits(["a short finished sentence."], width_pt=300, height_pt=100, font_pt=15.5)
    assert not fit.fits(["x" * 300], width_pt=300, height_pt=60, font_pt=15.5)


def test_capacities_seed_from_current_caps():
    cards = fit.capacity_for("cards")
    assert cards.max_items == fit.MAX_CARDS == 6
    assert cards.body.max_chars == 150
    assert cards.body.max_lines == 6
    rows = fit.capacity_for("rows")
    assert rows.max_items == fit.MAX_ROWS == 4
    assert rows.body.max_chars == 170


def test_capacity_for_unknown_returns_default():
    cap = fit.capacity_for("does-not-exist")
    assert cap.body.max_chars == 160  # _DEFAULT


def test_budget_for_scales_lead_by_heading_scale():
    base = fit.budget_for("cards", "editorial_serif")  # scale 1.0
    bold = fit.budget_for("cards", "bold_minimal")     # scale 1.14 -> tighter lead
    assert base.lead.max_chars == 50
    assert bold.lead.max_chars < base.lead.max_chars
    # body is scale-invariant in current css
    assert bold.body.max_chars == base.body.max_chars


def test_max_item_constants():
    assert fit.MAX_CARDS == 6
    assert fit.MAX_ROWS == 4
    assert fit.MAX_STEPS == 8


def test_authoring_chars_is_tighter_than_render_cap():
    body = fit.capacity_for("cards").body
    assert body.authoring_chars() < body.max_chars
