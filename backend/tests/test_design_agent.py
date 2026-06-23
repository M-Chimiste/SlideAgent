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
    assert revised.layout_json["layout"] == "checklist"
    assert revised.layout_json["visual_elements"] == ["checklist", "steps"]
    assert revised.layout_json["qa_repair"]["applied"] is True
    assert revised.content_json["exhibit_spec"]["type"] == "checklist"
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


def test_revise_for_qa_rewrites_exhibit_spec() -> None:
    outline = _outline(layout="two_column")
    outline.content_json["exhibit_spec"] = {
        "type": "checklist",
        "items": [
            {
                "action": " ".join(["Create a persistent memory bank"] * 12),
                "owner": "Engineering manager",
                "timing": "Week 1",
            }
        ],
    }
    issue = QAIssue(
        severity="WARNING",
        category="missing_exhibit",
        message="Non-cover slide is missing a primary exhibit spec.",
        slide_index=0,
    )

    revised = DesignAgent().revise_for_qa(outline, [issue])

    assert revised.content_json["exhibit_repair_applied"] is True
    assert len(revised.content_json["exhibit_spec"]["items"]) >= 1
    assert len(revised.content_json["exhibit_spec"]["items"][0]["action"]) <= 96


def test_apply_design_enforces_deck_level_layout_variety() -> None:
    outlines = [_outline(index=idx, layout="icon_grid") for idx in range(5)]

    designed = DesignAgent().apply_design(outlines)
    layouts = [outline.layout_json["layout"] for outline in designed]

    assert len(set(layouts)) >= 3
    assert not any(left == right for left, right in zip(layouts, layouts[1:]))


def test_apply_design_caps_repeated_heavy_layouts() -> None:
    heavy_layouts = [
        "framework_cycle",
        "framework_cycle",
        "framework_cycle",
        "dependency_map",
        "dependency_map",
        "code_panel",
        "code_panel",
        "table_reference",
        "table_reference",
    ]
    outlines = []
    for idx, layout in enumerate(heavy_layouts):
        outline = _outline(index=idx, layout=layout)
        outline.content_json["archetype"] = layout
        outline.content_json["action_title"] = f"Slide {idx} {layout}"
        outline.layout_json["archetype"] = layout
        outlines.append(outline)

    designed = DesignAgent().apply_design(outlines)
    layouts = [outline.layout_json["layout"] for outline in designed]

    for layout in {"framework_cycle", "dependency_map", "code_panel", "table_reference"}:
        assert layouts.count(layout) <= 1
    assert not any(left == right for left, right in zip(layouts, layouts[1:]))


def test_apply_design_caps_repeated_comparison_tables_with_distinct_treatment() -> None:
    outlines = []
    for idx in range(3):
        outline = _outline(index=idx, layout="comparison_table")
        outline.content_json["archetype"] = "comparison_table"
        outline.content_json["action_title"] = f"Compare current and target state {idx}"
        outline.content_json["content_blocks"] = [
            {
                "type": "table",
                "body": [
                    ["Dimension", "Current state", "Target state"],
                    ["Process", "Ad hoc", "Managed"],
                    ["Evidence", "Chats", "Artifacts"],
                ],
            }
        ]
        outline.layout_json["archetype"] = "comparison_table"
        outlines.append(outline)

    designed = DesignAgent().apply_design(outlines)
    layouts = [outline.layout_json["layout"] for outline in designed]

    assert layouts.count("comparison_table") == 1
    assert "process" in layouts
    assert not any(left == right for left, right in zip(layouts, layouts[1:]))


def test_apply_design_preserves_distinct_source_specific_dependency_maps() -> None:
    outlines = [
        _outline(index=0, layout="dependency_map"),
        _outline(index=1, layout="checklist"),
        _outline(index=2, layout="dependency_map"),
    ]
    for outline, title in zip(
        [outlines[0], outlines[2]],
        [
            "Map source dependencies before teams make the decision",
            "These files form a directed dependency graph",
        ],
    ):
        outline.label = title
        outline.content_json["title"] = title
        outline.content_json["action_title"] = title
        outline.content_json["archetype"] = "dependency_map"
        outline.content_json["exhibit_spec"] = {
            "type": "dependency_map",
            "left_node": "Source evidence",
            "middle_nodes": ["Context", "Rules", "Review"],
            "right_outcome": "Decision",
        }
        outline.layout_json["archetype"] = "dependency_map"

    designed = DesignAgent().apply_design(outlines)
    layouts = [outline.layout_json["layout"] for outline in designed]

    assert layouts == ["dependency_map", "checklist", "dependency_map"]


def test_apply_design_preserves_distinct_source_specific_cycle_layouts() -> None:
    outlines = [
        _outline(index=0, layout="framework_cycle"),
        _outline(index=1, layout="checklist"),
        _outline(index=2, layout="framework_cycle"),
    ]
    for outline, title in zip(
        [outlines[0], outlines[2]],
        [
            "Run the operating cycle with explicit review gates",
            "Specify the six-phase loop before delegating it to the agent",
        ],
    ):
        outline.label = title
        outline.content_json["title"] = title
        outline.content_json["action_title"] = title
        outline.content_json["archetype"] = "framework_cycle"
        outline.content_json["exhibit_spec"] = {
            "type": "cycle",
            "center_label": "Operating loop",
            "steps": [
                {"label": "Frame", "description": "Set the goal."},
                {"label": "Review", "description": "Check the work."},
            ],
        }
        outline.layout_json["archetype"] = "framework_cycle"

    designed = DesignAgent().apply_design(outlines)
    layouts = [outline.layout_json["layout"] for outline in designed]

    assert layouts == ["framework_cycle", "checklist", "framework_cycle"]


def test_apply_design_uses_checklist_as_adjacent_cycle_fallback() -> None:
    outlines = [_outline(index=idx, layout="framework_cycle") for idx in range(2)]
    for idx, outline in enumerate(outlines):
        title = [
            "Review the agentic cycle before trusting the generated output",
            "Specify the six-phase loop before delegating it to the agent",
        ][idx]
        outline.label = title
        outline.content_json["title"] = title
        outline.content_json["action_title"] = title
        outline.content_json["archetype"] = "framework_cycle"
        outline.content_json["exhibit_spec"] = {
            "type": "cycle",
            "center_label": "Operating loop",
            "steps": [
                {"label": "Frame", "description": "Set the goal."},
                {"label": "Review", "description": "Check the work."},
            ],
        }
        outline.layout_json["archetype"] = "framework_cycle"

    designed = DesignAgent().apply_design(outlines)
    layouts = [outline.layout_json["layout"] for outline in designed]

    assert layouts == ["framework_cycle", "checklist"]


def test_apply_design_caps_repeated_chart_layouts() -> None:
    outlines = []
    for idx in range(3):
        outline = _outline(index=idx, layout="chart")
        outline.content_json["metrics"] = [
            {"label": "Developers using AI", "value": 85, "unit": "%"},
            {"label": "AI-generated codebases", "value": 95, "unit": "%"},
        ]
        outline.content_json["archetype"] = "metric_chart"
        outline.layout_json["archetype"] = "metric_chart"
        outlines.append(outline)

    designed = DesignAgent().apply_design(outlines)
    layouts = [outline.layout_json["layout"] for outline in designed]

    assert layouts.count("chart") == 1
    assert len(set(layouts)) >= 2


def test_apply_design_preserves_explicit_mid_deck_section_divider() -> None:
    outlines = [_outline(index=idx, layout="two_column") for idx in range(6)]
    outlines[3].content_json["archetype"] = "section_divider"
    outlines[3].content_json["narrative_role"] = "framework"
    outlines[3].layout_json["layout"] = "section_divider"
    outlines[3].layout_json["archetype"] = "section_divider"

    designed = DesignAgent().apply_design(outlines)

    assert designed[3].layout_json["layout"] == "section_divider"
    assert designed[3].layout_json["visual_elements"] == ["section_marker", "typography"]


def test_apply_design_preserves_explicit_post_cover_executive_summary() -> None:
    outlines = [_outline(index=idx, layout="two_column") for idx in range(4)]
    outlines[0].content_json["archetype"] = "cover"
    outlines[0].layout_json["layout"] = "cover"
    outlines[0].layout_json["archetype"] = "cover"
    outlines[1].content_json["archetype"] = "executive_summary"
    outlines[1].content_json["narrative_role"] = "executive_summary"
    outlines[1].content_json["exhibit_spec"] = {
        "type": "executive_summary",
        "messages": [
            {"label": "Situation", "text": "AI coding is moving into production work."},
            {"label": "Complication", "text": "Context and review gaps reduce reliability."},
            {"label": "Resolution", "text": "Manage agents with context, rules, and QA."},
        ],
    }
    outlines[1].layout_json["layout"] = "executive_summary"
    outlines[1].layout_json["archetype"] = "executive_summary"

    designed = DesignAgent().apply_design(outlines)

    assert designed[1].layout_json["layout"] == "executive_summary"
    assert designed[1].layout_json["visual_elements"] == ["structured_text"]


def test_apply_design_routes_explicit_reference_archetype_to_code_panel() -> None:
    outlines = [_outline(index=idx, layout="two_column") for idx in range(4)]
    outlines[2].content_json["archetype"] = "reference"
    outlines[2].content_json["action_title"] = "Document the Memory Bank update protocol"
    outlines[2].content_json["bullets"] = [
        "Update activeContext.md after each meaningful change.",
        "Record decisions before starting the next session.",
        "Keep progress.md synchronized with implementation status.",
    ]
    outlines[2].layout_json["archetype"] = "reference"

    designed = DesignAgent().apply_design(outlines)

    assert designed[2].layout_json["layout"] == "code_panel"
    assert designed[2].layout_json["visual_elements"] == ["reference_panel", "code"]


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
