from datetime import UTC, datetime

from app.models.brand import BrandDNA
from app.models.outline import SlideOutline
from app.models.template import SlideField, SlideSchema, SlideSpec, TemplateProfile
from app.services.authored_pptx_renderer import AuthoredPptxRenderer
from app.services.design_agent import DesignAgent
from app.services.generation_editing_contract import GenerationEditingContract
from app.services.orchestrator import JobOrchestrator


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _template(template_type: str = "freeform") -> TemplateProfile:
    slides = []
    if template_type != "freeform":
        slides = [
            SlideSpec(
                index=0,
                mode="flexible",
                label="Comparison frame",
                layout_name="Two Column Comparison",
                intent="compare current and target states",
                content_category="comparison",
                schema=SlideSchema(
                    fields=[
                        SlideField(
                            id="comparison_rows",
                            type="list",
                            location="body",
                            max_items=2,
                        )
                    ]
                ),
            ),
            SlideSpec(
                index=1,
                mode="flexible",
                label="Proof points",
                layout_name="Three Callouts",
                intent="show evidence points",
                content_category="evidence",
                schema=SlideSchema(
                    fields=[
                        SlideField(
                            id="proof_points",
                            type="list",
                            location="body",
                            max_items=3,
                        )
                    ]
                ),
            ),
        ]
    return TemplateProfile(
        id=f"{template_type}-template",
        name=f"{template_type.title()} Template",
        type=template_type,
        brand=BrandDNA(),
        slides=slides,
        source_file="",
        created_at=_timestamp(),
        updated_at=_timestamp(),
    )


def _outline(index: int, layout: str, title: str = "Evidence slide") -> SlideOutline:
    return SlideOutline(
        id=f"outline-{index}",
        job_id="contract-job",
        slide_index=index,
        mode="flexible",
        label=title,
        content_json={
            "action_title": title,
            "narrative_role": "evidence",
            "archetype": layout,
            "source_refs": ["doc-1:section:1"],
            "content_blocks": [{"type": "bullets", "body": ["First point", "Second point"]}],
            "exhibit_spec": {"type": "comparison_table" if layout == "comparison_table" else "callouts"},
        },
        layout_json={"layout": layout, "archetype": layout},
        created_at=_timestamp(),
    )


def _brand_template_with_slides(count: int) -> TemplateProfile:
    slides = [
        SlideSpec(
            index=i,
            mode="flexible",
            label=f"Frame {i}",
            layout_name="Comparison",
            intent="compare states",
            content_category="comparison",
        )
        for i in range(count)
    ]
    return TemplateProfile(
        id="brand-template",
        name="Brand Template",
        type="brand",
        brand=BrandDNA(),
        slides=slides,
        source_file="",
        created_at=_timestamp(),
        updated_at=_timestamp(),
    )


def test_template_slide_for_spreads_across_slides_with_usage_counts() -> None:
    template = _brand_template_with_slides(3)
    # A cover outline has no comparison/evidence category match -> fallback path.
    outline = _outline(0, "cover", "Welcome to the deck")
    outline.content_json["narrative_role"] = "cover"
    contract = GenerationEditingContract()

    baseline = contract.template_slide_for(outline, template, [outline])
    assert baseline is not None and baseline["method"] == "cyclic_fallback"
    assert baseline["index"] == 0  # slide_index 0 % 3

    # With slide 0 already heavily used, least-used selection avoids it.
    spread = contract.template_slide_for(outline, template, [outline], {0: 9})
    assert spread is not None and spread["index"] != 0


def test_editing_contract_flags_monotonous_card_layouts() -> None:
    outlines = [_outline(index, "icon_rows") for index in range(6)]

    contract = GenerationEditingContract().build(_template(), outlines)

    assert contract["artifact"] == "editing-contract"
    assert contract["status"] == "warning"
    requirement_ids = {
        item["id"]: item["status"] for item in contract["requirements"]
    }
    assert requirement_ids["varied_layout_mapping"] == "warning"
    assert requirement_ids["avoid_adjacent_repetition"] == "warning"
    assert requirement_ids["avoid_card_grid_default"] == "warning"


def test_editing_contract_flags_repeated_visible_composition_families() -> None:
    layouts = [
        "comparison_table",
        "checklist",
        "process",
        "quote_sidebar",
        "table_reference",
        "callouts",
        "icon_rows",
        "two_column",
    ]
    outlines = [_outline(index, layout) for index, layout in enumerate(layouts)]
    for outline in outlines:
        outline.layout_json["composition_family"] = "proof_strip"
        outline.content_json["composition_family"] = "proof_strip"

    contract = GenerationEditingContract().build(_template(), outlines)
    requirements = {
        item["id"]: item["status"] for item in contract["requirements"]
    }

    assert contract["unique_layout_count"] == 1
    assert contract["unique_composition_family_count"] == 1
    assert requirements["varied_composition_families"] == "warning"
    assert requirements["avoid_repeated_composition_family"] == "warning"
    assert requirements["avoid_card_composition_default"] == "warning"


def test_editing_contract_uses_visible_composition_for_layout_variety() -> None:
    families = [
        "editorial_spread",
        "architecture_layers",
        "lifecycle_timeline",
        "abstraction_split",
        "operating_map",
        "decision_ladder",
    ]
    outlines = [_outline(index, "callouts") for index in range(len(families))]
    for outline, family in zip(outlines, families):
        outline.layout_json["composition_family"] = family
        outline.content_json["composition_family"] = family

    contract = GenerationEditingContract().build(_template(), outlines)
    requirements = {
        item["id"]: item["status"] for item in contract["requirements"]
    }

    assert contract["unique_layout_count"] == len(families)
    assert requirements["varied_layout_mapping"] == "pass"
    assert requirements["avoid_adjacent_repetition"] == "pass"
    assert requirements["avoid_card_grid_default"] == "pass"


def test_authored_renderer_keeps_generic_decks_below_card_composition_budget() -> None:
    outlines = []
    for index in range(12):
        outline = _outline(index, "icon_rows", f"Evidence claim {index + 1}")
        outline.content_json["narrative_role"] = "support"
        outline.content_json["source_refs"] = []
        outlines.append(outline)

    authored = AuthoredPptxRenderer().author_outlines(outlines)
    contract = GenerationEditingContract().build(_template(), authored)
    requirements = {
        item["id"]: item["status"] for item in contract["requirements"]
    }

    assert contract["composition_card_ratio"] <= 0.42
    assert contract["unique_composition_family_count"] >= 7
    assert requirements["avoid_card_composition_default"] == "pass"


def test_editing_contract_maps_brand_slides_to_template_frames() -> None:
    outlines = [
        _outline(0, "comparison_table", "Compare current and target states"),
        _outline(1, "callouts", "Show proof points from evidence"),
    ]

    contract = GenerationEditingContract().build(_template("brand"), outlines)

    assert contract["template_mapped_count"] == 2
    assert contract["structural_operation_count"] == 2
    assert contract["structural_warning_count"] == 0
    assert contract["slides"][0]["template_slide"]["label"] == "Comparison frame"
    assert contract["slides"][1]["template_slide"]["label"] == "Proof points"
    assert [op["operation"] for op in contract["structural_plan"]["operations"]] == [
        "use_template_frame",
        "use_template_frame",
    ]
    requirement_status = {
        item["id"]: item["status"] for item in contract["requirements"]
    }
    assert requirement_status["template_mapping"] == "pass"
    assert requirement_status["complete_structure_before_content_edit"] == "pass"


def test_editing_contract_marks_weak_brand_template_mapping_for_review() -> None:
    template = _template("brand")
    template.slides[0].label = "Comparison heading only"
    template.slides[0].content_category = "content"
    template.slides[0].intent = "General content frame"
    template.slides[0].visual_guidance = "title and body slots"
    template.slides = [template.slides[0]]
    outline = _outline(0, "comparison_table", "Compare current and target states")

    contract = GenerationEditingContract().build(template, [outline])
    frame = contract["slides"][0]["template_slide"]
    structural = {
        item["id"]: item for item in contract["requirements"]
    }["complete_structure_before_content_edit"]

    assert frame["method"] == "low_confidence_match"
    assert frame["match_confidence"] == "low"
    assert frame["match_score"] > 0
    assert structural["status"] == "warning"
    assert "weak template mapping" in structural["evidence"]["warnings"][0]


def test_editing_contract_marks_cyclic_brand_template_fallback_for_review() -> None:
    template = _template("brand")
    template.slides[0].label = "Agenda"
    template.slides[0].layout_name = "Agenda"
    template.slides[0].content_category = "section_or_cover"
    template.slides[0].intent = "Opening agenda frame"
    template.slides[0].visual_guidance = "title only"
    template.slides = [template.slides[0]]
    outline = _outline(0, "comparison_table", "Compare current and target states")

    contract = GenerationEditingContract().build(template, [outline])
    frame = contract["slides"][0]["template_slide"]
    structural = {
        item["id"]: item for item in contract["requirements"]
    }["complete_structure_before_content_edit"]

    assert frame["method"] == "cyclic_fallback"
    assert frame["match_confidence"] == "fallback"
    assert frame["match_score"] == 0
    assert frame["closest_candidates"][0]["source_slide"] == 1
    assert structural["status"] == "warning"


def test_editing_contract_records_template_frame_alternatives_for_weak_match() -> None:
    template = _template("brand")
    template.slides[0].label = "Agenda"
    template.slides[0].content_category = "section_or_cover"
    template.slides[0].intent = "Opening agenda frame"
    template.slides[1].label = "Evidence wall"
    template.slides[1].content_category = "evidence_points"
    template.slides[1].intent = "Evidence frame for proof points"
    outline = _outline(0, "comparison_table", "Compare current and target states")

    contract = GenerationEditingContract().build(template, [outline])
    frame = contract["slides"][0]["template_slide"]

    assert frame["method"] == "low_confidence_match"
    assert frame["closest_candidates"]
    assert frame["closest_candidates"][0]["source_slide"] == 1
    assert frame["closest_candidates"][0]["match_score"] >= 0


def test_editing_contract_records_brand_structural_deletions_before_content_edit() -> None:
    outline = _outline(0, "comparison_table", "Compare current and target states")

    contract = GenerationEditingContract().build(_template("brand"), [outline])
    structural = contract["structural_plan"]
    requirement = {
        item["id"]: item for item in contract["requirements"]
    }["complete_structure_before_content_edit"]

    assert structural["status"] == "pass"
    assert structural["delete_unused_template_slide_indexes"] == [1]
    assert structural["operations"][0]["operation"] == "use_template_frame"
    assert structural["operations"][0]["before_content_edit"] is True
    assert requirement["status"] == "pass"
    assert requirement["evidence"]["delete_unused_template_slide_indexes"] == [1]


def test_brand_template_mapping_requires_analyzed_frames_only_for_source_decks() -> None:
    outline = _outline(0, "comparison_table", "Compare current and target states")
    native_brand = _template("brand").model_copy(update={"slides": [], "source_file": ""})
    source_brand = _template("brand").model_copy(
        update={"slides": [], "source_file": "/tmp/brand.pptx"}
    )

    native_contract = GenerationEditingContract().build(native_brand, [outline])
    source_contract = GenerationEditingContract().build(source_brand, [outline])

    native_requirement = {
        item["id"]: item for item in native_contract["requirements"]
    }["template_mapping"]
    source_requirement = {
        item["id"]: item for item in source_contract["requirements"]
    }["template_mapping"]
    assert native_requirement["status"] == "pass"
    assert source_requirement["status"] == "warning"
    assert "no analyzed slide frames" in source_requirement["message"]


def test_editing_contract_warnings_convert_to_pipeline_warnings() -> None:
    contract = GenerationEditingContract().build(
        _template(),
        [_outline(index, "icon_rows") for index in range(6)],
    )

    warnings = JobOrchestrator._editing_contract_warnings(None, contract)

    assert warnings
    assert {warning["field"] for warning in warnings} == {"editing_contract"}
    assert all(warning["severity"] == "WARNING" for warning in warnings)


def test_editing_contract_flags_concatenated_step_items() -> None:
    outline = _outline(0, "checklist")
    outline.content_json["content_blocks"] = [
        {
            "type": "bullets",
            "body": [
                "Step 1: Frame the request. Step 2: Review the output. Step 3: Update memory."
            ],
        }
    ]

    contract = GenerationEditingContract().build(_template(), [outline])
    requirement_status = {
        item["id"]: item for item in contract["requirements"]
    }

    assert requirement_status["separate_multi_item_content"]["status"] == "warning"
    assert requirement_status["separate_multi_item_content"]["evidence"][
        "risky_slide_indexes"
    ] == [0]


def test_editing_contract_flags_unicode_bullet_formatting() -> None:
    outline = _outline(0, "checklist")
    outline.content_json["content_blocks"] = [
        {
            "type": "bullets",
            "body": ["\u2022 Frame the request", "\u2022 Review the output"],
        }
    ]

    contract = GenerationEditingContract().build(_template(), [outline])
    requirement = {
        item["id"]: item for item in contract["requirements"]
    }["pptx_formatting_rules"]

    assert contract["formatting_warning_count"] == 1
    assert requirement["status"] == "warning"
    assert requirement["evidence"]["unicode_bullet_slide_indexes"] == [
        {"slide_index": 0, "unicode_bullet_count": 2}
    ]


def test_editing_contract_plans_template_slot_fit_actions() -> None:
    too_many_items = _outline(0, "comparison_table", "Compare four source items")
    too_many_items.content_json["content_blocks"] = [
        {
            "type": "bullets",
            "body": ["One", "Two", "Three", "Four"],
        }
    ]
    fewer_items = _outline(1, "callouts", "Show one proof point")
    fewer_items.content_json["content_blocks"] = [
        {"type": "bullets", "body": ["Only proof point"]}
    ]

    contract = GenerationEditingContract().build(
        _template("brand"),
        [too_many_items, fewer_items],
    )
    slot_plans = {
        slide["slide_index"]: slide["slot_plan"]
        for slide in contract["slides"]
    }
    requirement = {
        item["id"]: item for item in contract["requirements"]
    }["match_source_items_to_template_slots"]

    assert slot_plans[0]["action"] == "split_or_summarize_source_items"
    assert slot_plans[0]["overflow_count"] == 2
    assert slot_plans[1]["action"] == "delete_excess_template_elements"
    assert slot_plans[1]["excess_slot_count"] == 2
    assert requirement["status"] == "warning"
    assert {item["slide_index"] for item in requirement["evidence"]["slot_risks"]} == {0, 1}


def test_editing_contract_design_pass_splits_concatenated_step_items() -> None:
    outline = _outline(0, "checklist")
    outline.content_json["content_blocks"] = [
        {
            "type": "bullets",
            "body": "Step 1: Frame the request. Step 2: Review the output. Step 3: Update memory.",
        }
    ]

    remapped = DesignAgent().apply_editing_contract([outline])
    body = remapped[0].content_json["content_blocks"][0]["body"]
    contract = GenerationEditingContract().build(_template(), remapped)
    requirement_status = {
        item["id"]: item["status"] for item in contract["requirements"]
    }

    assert body == [
        "Step 1: Frame the request.",
        "Step 2: Review the output.",
        "Step 3: Update memory.",
    ]
    assert remapped[0].layout_json["editing_contract_repair"]["multi_item_split"] is True
    assert requirement_status["separate_multi_item_content"] == "pass"


def test_editing_contract_design_pass_sanitizes_unicode_bullets() -> None:
    outline = _outline(0, "checklist")
    outline.content_json["bullets"] = ["\u2022 Frame the request"]
    outline.content_json["content_blocks"] = [
        {
            "type": "bullets",
            "body": "\u2022 Frame the request\n\u2022 Review the output",
        }
    ]
    outline.content_json["exhibit_spec"] = {
        "type": "checklist",
        "items": ["\u2022 Update memory"],
    }

    remapped = DesignAgent().apply_editing_contract([outline])
    contract = GenerationEditingContract().build(_template(), remapped)
    body = remapped[0].content_json["content_blocks"][0]["body"]
    requirement_status = {
        item["id"]: item["status"] for item in contract["requirements"]
    }

    assert remapped[0].content_json["bullets"] == ["Frame the request"]
    assert body == ["Frame the request", "Review the output"]
    assert remapped[0].content_json["exhibit_spec"]["items"] == ["Update memory"]
    assert remapped[0].layout_json["editing_contract_repair"]["unicode_bullet_sanitized_count"] == 4
    assert contract["formatting_fix_count"] == 4
    assert contract["formatting_warning_count"] == 0
    assert contract["slides"][0]["formatting_plan"]["status"] == "fixed"
    assert requirement_status["pptx_formatting_rules"] == "pass"


def test_editing_contract_remap_corrects_card_heavy_plan() -> None:
    outlines = [_outline(index, "icon_rows") for index in range(8)]

    remapped = DesignAgent().apply_editing_contract(outlines)
    layouts = [outline.layout_json["layout"] for outline in remapped]
    contract = GenerationEditingContract().build(_template(), remapped)
    requirement_status = {
        item["id"]: item["status"] for item in contract["requirements"]
    }

    assert sum(layout in GenerationEditingContract.bullet_card_layouts for layout in layouts) <= 4
    assert not any(left == right for left, right in zip(layouts, layouts[1:]))
    assert len(set(layouts)) >= 4
    assert any(
        outline.layout_json.get("editing_contract_repair", {}).get("applied")
        for outline in remapped
    )
    assert requirement_status["avoid_card_grid_default"] == "pass"
    assert requirement_status["avoid_adjacent_repetition"] == "pass"
