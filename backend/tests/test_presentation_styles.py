from app.services.planning.constants import (
    PLANNER_SHOWCASE_ADDENDUM,
    PLANNER_SYSTEM_PROMPT,
    build_planner_system_prompt,
)
from app.services.presentation_styles import STYLES, get_style, infer_style


def test_consulting_prompt_is_byte_for_byte_unchanged() -> None:
    assert build_planner_system_prompt("balanced", "consulting") == PLANNER_SYSTEM_PROMPT
    assert build_planner_system_prompt("showcase", "consulting") == (
        f"{PLANNER_SYSTEM_PROMPT}\n{PLANNER_SHOWCASE_ADDENDUM}"
    )


def test_non_consulting_prompt_swaps_persona() -> None:
    prompt = build_planner_system_prompt("balanced", "investor_pitch")
    assert "investor pitch" in prompt
    assert "McKinsey" not in prompt
    # showcase rigor still appends for non-consulting styles
    assert PLANNER_SHOWCASE_ADDENDUM in build_planner_system_prompt("showcase", "investor_pitch")


def test_get_style_falls_back_to_consulting() -> None:
    assert get_style("nonsense").key == "consulting"
    assert get_style(None).key == "consulting"
    assert get_style("investor_pitch").key == "investor_pitch"


def test_infer_style_scores_keywords() -> None:
    assert infer_style("We are raising a seed round; here is our traction and valuation.") == "investor_pitch"
    assert infer_style("This lecture covers the course curriculum for students.") == "academic_lecture"
    assert infer_style("Quarterly business review: OKRs, KPIs, and progress vs plan.") == "status_report_qbr"
    # no signal -> default
    assert infer_style("") == "consulting"


def test_every_style_default_design_language_is_known() -> None:
    from app.services.design_languages import LANGUAGES

    for style in STYLES.values():
        assert style.default_design_language in LANGUAGES
        assert len(style.section_plan_labels) == 3
