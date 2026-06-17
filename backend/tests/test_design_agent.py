from app.models.outline import SlideOutline
from app.models.qa import QAIssue
from app.services.design_agent import DesignAgent


def _outline(index: int = 0, layout: str = "two_column") -> SlideOutline:
    return SlideOutline(
        id=f"outline-{index}",
        job_id="job-1",
        slide_index=index,
        mode="flexible",
        label="Improve AI delivery discipline",
        content_json={
            "title": "Improve AI delivery discipline",
            "summary": " ".join(["Long summary"] * 30),
            "bullets": [
                " ".join([f"Detailed evidence point {idx}"] * 12)
                for idx in range(6)
            ],
            "content_blocks": [
                {
                    "type": "bullets",
                    "body": [
                        " ".join([f"Long generated body point {idx}"] * 12)
                        for idx in range(6)
                    ],
                }
            ],
            "sources": ["Uploaded source"],
        },
        layout_json={"layout": layout, "visual_elements": ["structured_text"]},
        created_at="2026-01-01T00:00:00Z",
    )


def test_revise_for_qa_condenses_text_wall_and_adds_visual_structure() -> None:
    outline = _outline()
    issue = QAIssue(
        severity="WARNING",
        category="text_wall",
        message="Slide reads as a text wall with poor scanability.",
        slide_index=0,
    )

    revised = DesignAgent().revise_for_qa(outline, [issue])

    assert revised is not outline
    assert revised.layout_json["layout"] == "icon_grid"
    assert revised.layout_json["visual_elements"] == ["icons", "shapes"]
    assert revised.layout_json["qa_repair"]["applied"] is True
    assert len(revised.content_json["bullets"]) == 4
    assert len(revised.content_json["bullets"][0]) <= 145
    assert len(outline.content_json["bullets"]) == 6


def test_revise_deck_for_qa_repairs_layout_repetition() -> None:
    outlines = [_outline(index=idx, layout="two_column") for idx in range(4)]
    issue = QAIssue(
        severity="WARNING",
        category="layout_variety",
        message="Deck uses too little layout variety.",
        slide_index=None,
    )

    revised = DesignAgent().revise_deck_for_qa(outlines, [issue])
    layouts = [outline.layout_json["layout"] for outline in revised]

    assert len(set(layouts)) > 1
    assert any(outline.layout_json.get("qa_repair") for outline in revised)


def test_apply_design_enforces_deck_level_layout_variety() -> None:
    outlines = [_outline(index=idx, layout="icon_grid") for idx in range(5)]

    designed = DesignAgent().apply_design(outlines)
    layouts = [outline.layout_json["layout"] for outline in designed]

    assert len(set(layouts)) >= 3
    assert not any(left == right for left, right in zip(layouts, layouts[1:]))


def test_layout_repair_does_not_use_executive_summary_as_generic_fallback() -> None:
    outline = _outline(layout="two_column")
    issue = QAIssue(
        severity="WARNING",
        category="layout",
        message="Repeated adjacent layouts may make the deck feel repetitive.",
        slide_index=0,
    )

    revised = DesignAgent().revise_for_qa(outline, [issue])

    assert revised.layout_json["layout"] != "executive_summary"
    assert revised.layout_json["layout"] != "section_divider"


def test_source_placeholder_is_not_a_design_repair_issue() -> None:
    issue = QAIssue(
        severity="WARNING",
        category="source_placeholder",
        message="Slide still contains a [source needed] placeholder.",
        slide_index=0,
    )

    assert DesignAgent().is_actionable_qa_issue(issue) is False


def test_approximate_preview_findings_are_not_auto_repaired() -> None:
    issue = QAIssue(
        severity="WARNING",
        category="text-wall",
        message="Approximate preview finding: Slide may be dense.",
        slide_index=0,
    )

    assert DesignAgent().is_actionable_qa_issue(issue) is False


def test_apply_design_selects_icons_from_card_content() -> None:
    outline = _outline()
    outline.content_json["title"] = "Improve AI delivery discipline"
    outline.content_json["summary"] = "Use operating discipline for agentic workflows."
    outline.content_json["bullets"] = [
        "Hallucination risk increases when context rots.",
        "AI adoption is high enough to require scale governance.",
        "The memory bank preserves data across sessions.",
    ]

    designed = DesignAgent().apply_design([outline])[0]

    assert designed.layout_json["icons"][:4] == [
        "FaExclamationTriangle",
        "FaChartLine",
        "FaDatabase",
        "FaDatabase",
    ]


def test_icon_selection_does_not_match_keywords_inside_words() -> None:
    agent = DesignAgent()

    assert agent._icon_for_text("Prototype phase requires operating discipline") != (
        "FaExclamationTriangle"
    )
    assert agent._icon_for_text("Context rot creates reliability risk") == (
        "FaDatabase"
    )


def test_failure_mode_icons_are_distinct() -> None:
    agent = DesignAgent()

    assert agent._icon_for_text("Context Rot: finite context windows degrade memory") == (
        "FaDatabase"
    )
    assert agent._icon_for_text("Hallucination Amplification: fabricated APIs") == (
        "FaExclamationTriangle"
    )
    assert agent._icon_for_text("Reproducibility Gap: decisions are not traceable") == (
        "FaShieldAlt"
    )
