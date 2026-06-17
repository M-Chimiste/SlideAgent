import zipfile
from io import BytesIO
from datetime import UTC, datetime
from pathlib import Path

from lxml import etree
from openpyxl import load_workbook
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Inches

from app.config import Settings
from app.clients.openai_compatible_client import OpenAICompatibleClient
from app.models.brand import BrandDNA
from app.models.document import DocumentBundle, DocumentMetadata, DocumentSection
from app.models.outline import SlideOutline
from app.models.template import SlideField, SlideSchema, SlideSpec, TemplateProfile
from app.services.content_planner import ContentPlanner
from app.services.pptx_builder import PptxBuilder
from app.services.strict_injector import StrictSlideInjector
from app.services.template_analyzer import TemplateAnalyzer


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _template(template_type: str = "freeform", source_file: str = "") -> TemplateProfile:
    return TemplateProfile(
        id=f"{template_type}-template",
        name=f"{template_type.title()} Template",
        type=template_type,
        brand=BrandDNA(),
        slides=[],
        source_file=source_file,
        created_at=_timestamp(),
        updated_at=_timestamp(),
    )


def _bundle(job_id: str = "job-1") -> DocumentBundle:
    return DocumentBundle(
        job_id=job_id,
        sections=[
            DocumentSection(
                title="Developer Productivity",
                level=1,
                content=(
                    "Engineering teams are using AI coding assistants broadly, "
                    "but review discipline and architecture judgment remain uneven."
                ),
                source_doc_id="doc-1",
            ),
            DocumentSection(
                title="Quality Risk",
                level=1,
                content=(
                    "Fast code generation can increase defects unless teams add "
                    "testing, architectural review, and acceptance criteria."
                ),
                source_doc_id="doc-1",
            ),
        ],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Beyond Vibe Coding"),
        content_inventory=[],
    )


def test_openai_compatible_client_extracts_json_from_fenced_response() -> None:
    response = """Here is the plan:
```json
{"deck_title":"Test","slides":[]}
```"""
    payload = OpenAICompatibleClient.extract_json(response)
    assert payload == {"deck_title": "Test", "slides": []}


def test_openai_compatible_client_sends_reasoning_effort(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "OK", "reasoning_content": ""}}]}

    class FakeHTTPClient:
        payload: dict | None = None

        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        def __enter__(self) -> "FakeHTTPClient":
            return self

        def __exit__(self, *args) -> None:
            return None

        def post(self, url: str, json: dict, headers: dict) -> FakeResponse:
            FakeHTTPClient.payload = json
            return FakeResponse()

    monkeypatch.setattr("app.clients.openai_compatible_client.httpx.Client", FakeHTTPClient)

    client = OpenAICompatibleClient(
        Settings(
            OPENAI_COMPATIBLE_BASE_URL="http://metis.local:1240/v1",
            OPENAI_COMPATIBLE_MODEL="qwen3.6-35b-a3b-mtp",
            OPENAI_COMPATIBLE_API_KEY="lm-studio",
            OPENAI_COMPATIBLE_REASONING_EFFORT="none",
            BEDROCK_VALIDATE=False,
        )
    )

    assert client.complete_text("", "Reply exactly with OK.", max_tokens=32, temperature=0) == "OK"
    assert FakeHTTPClient.payload is not None
    assert FakeHTTPClient.payload["reasoning_effort"] == "none"


def test_freeform_planner_creates_consulting_slide_specs() -> None:
    planner = ContentPlanner()
    outlines, warnings = planner.plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert len(outlines) >= 4
    assert outlines[0].content_json["action_title"]
    assert outlines[0].content_json["sources"]
    assert all(outline.layout_json["generation_mode"] == "freeform" for outline in outlines)
    assert not any("generic topic label" in warning["message"].lower() for warning in warnings)


def test_planner_reports_llm_fallback_when_configured_client_fails() -> None:
    class FailingLLM:
        def complete_json(self, **kwargs):
            raise TimeoutError("model timed out")

    planner = ContentPlanner(llm_client=FailingLLM())
    _, warnings = planner.plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert any(warning["field"] == "llm_planning" for warning in warnings)


def test_planner_repairs_compound_llm_action_titles() -> None:
    class CompoundTitleLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "content",
                        "action_title": (
                            "Identify context rot and hallucination as structural barriers "
                            "to scalable AI development."
                        ),
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Context loss and hallucinations reduce reliability."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the risk.",
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    planner = ContentPlanner(llm_client=CompoundTitleLLM())
    outlines, warnings = planner.plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert outlines[0].label == "Identify structural barriers to scalable AI development"
    assert not warnings


def test_planner_varies_generic_llm_slide_layouts() -> None:
    class GenericSlidesLLM:
        def complete_json(self, **kwargs):
            titles = [
                "Improve agentic delivery discipline across priority workflows",
                "Standardize context management across software delivery teams",
                "Reduce review gaps through explicit acceptance criteria",
                "Adopt persistent memory to improve agent reliability",
                "Secure production quality with structured oversight",
            ]
            slides = []
            for number, title in enumerate(titles, start=1):
                slides.append(
                    {
                        "slide_number": number,
                        "slide_type": "content",
                        "action_title": title,
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Teams need structure, context, and review discipline."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the implication.",
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                )
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": slides,
            }

    planner = ContentPlanner(llm_client=GenericSlidesLLM())
    outlines, warnings = planner.plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )
    layouts = [outline.layout_json["layout"] for outline in outlines]

    assert len(set(layouts)) >= 3
    assert not any(left == middle == right for left, middle, right in zip(layouts, layouts[1:], layouts[2:]))
    assert not warnings


def test_planner_routes_claude_style_archetypes_to_distinct_layouts() -> None:
    class ClaudeStyleLLM:
        def complete_json(self, **kwargs):
            titles = [
                ("anti_pattern", "Recognize three failure modes that break vibe coding"),
                ("framework", "Run the agentic cycle as a managed workflow"),
                ("content", "Implement the Memory Bank hierarchy for persistent context"),
                ("reference", "Codify rules files beside the codebase"),
                ("checklist", "Adopt the agentic workflow tomorrow"),
                ("quote", "Reframe the developer role from coder to AI manager"),
                ("executive_summary", "Define the Memory Bank architecture for immediate implementation"),
            ]
            slides = []
            for number, (slide_type, title) in enumerate(titles, start=1):
                slides.append(
                    {
                        "slide_number": number,
                        "slide_type": slide_type,
                        "action_title": title,
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": [
                                    "Persistent context changes the operating model.",
                                    "Structured review reduces fragile outputs.",
                                    "Managers need clear rules and memory.",
                                ],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the implication.",
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                )
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": slides,
            }

    outlines, warnings = ContentPlanner(llm_client=ClaudeStyleLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    layouts = [outline.layout_json["layout"] for outline in outlines]

    assert layouts == [
        "anti_patterns",
        "framework_cycle",
        "dependency_map",
        "code_panel",
        "checklist",
        "quote_sidebar",
        "dependency_map",
    ]
    assert not warnings


def test_planner_strips_diagram_description_placeholders_from_bullets() -> None:
    class DiagramDescriptionLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "content",
                        "action_title": "Map the External Brain architecture",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": [
                                    "[Diagram Description: Central Node with arrows] Project context persists.",
                                    "Rules files guide each AI session.",
                                ],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the implication.",
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, _warnings = ContentPlanner(llm_client=DiagramDescriptionLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    bullets = outlines[0].content_json["bullets"]

    assert bullets[0] == "Project context persists."
    assert not any("Diagram Description" in bullet for bullet in bullets)


def test_planner_summary_truncates_at_word_boundary() -> None:
    summary = ContentPlanner()._summarize(" ".join(["agentic"] * 40))

    assert summary.endswith("...")
    assert len(summary) <= 160
    assert summary.removesuffix("...").split()[-1] == "agentic"


def test_planner_marks_unsupported_numeric_claims_source_needed() -> None:
    class UnsupportedMetricLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "content",
                        "action_title": "Reduce escaped defects by 42%",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Teams reported 42% fewer defects after adoption."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the implication.",
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=UnsupportedMetricLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert "[source needed]" in outlines[0].content_json["sources"]
    assert outlines[0].content_json["content_blocks"][0]["body"][0].endswith(
        "[source needed]"
    )
    assert any(warning["field"] == "source_coverage" for warning in warnings)


def test_planner_allows_numeric_claims_present_in_source() -> None:
    class SupportedMetricLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "content",
                        "action_title": "Reduce escaped defects by 42%",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Teams reported 42% fewer defects after adoption."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the implication.",
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    bundle = _bundle()
    bundle.sections[0].content += " Teams reported 42% fewer escaped defects."
    outlines, warnings = ContentPlanner(llm_client=SupportedMetricLLM()).plan(
        _template("freeform"),
        bundle,
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert "[source needed]" not in outlines[0].content_json["sources"]
    assert "[source needed]" not in outlines[0].content_json["content_blocks"][0]["body"][0]
    assert not any(warning["field"] == "source_coverage" for warning in warnings)


def test_planner_normalizes_invented_source_labels() -> None:
    class InventedSourceLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "content",
                        "action_title": "Improve review discipline before scaling agents",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Teams need clearer review standards."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["McKinsey AI engineering survey 2026"],
                        "speaker_notes": "Explain the implication.",
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=InventedSourceLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert outlines[0].content_json["sources"] == ["Uploaded source"]
    assert any(warning["field"] == "source_label" for warning in warnings)
    assert "McKinsey" in warnings[0]["message"]


def test_planner_adds_source_label_when_llm_omits_sources() -> None:
    class MissingSourceLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "content",
                        "action_title": "Improve review discipline before scaling agents",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Teams need clearer review standards."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "speaker_notes": "Explain the implication.",
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=MissingSourceLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert outlines[0].content_json["sources"] == ["Uploaded source"]
    assert any(warning["field"] == "source_label" for warning in warnings)


def test_planner_rejects_uploaded_source_label_without_source_material() -> None:
    class UnsupportedSourceLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Prompt Only Deck",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "content",
                        "action_title": "Improve review discipline before scaling agents",
                        "subheading": "Prompt-only context",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Teams need clearer review standards."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the implication.",
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    bundle = DocumentBundle(
        job_id="job-1",
        sections=[],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(),
        content_inventory=[],
    )
    outlines, warnings = ContentPlanner(llm_client=UnsupportedSourceLLM()).plan(
        _template("freeform"),
        bundle,
        instructions="Create a prompt-only deck.",
        generation_mode="freeform",
    )

    assert outlines[0].content_json["sources"] == ["[source needed]"]
    assert any(warning["field"] == "source_label" for warning in warnings)


def test_planner_prompt_includes_allowed_numeric_tokens() -> None:
    class CapturingLLM:
        prompt = ""

        def complete_json(self, **kwargs):
            self.prompt = kwargs["user_prompt"]
            return None

    bundle = _bundle()
    bundle.sections[0].content += " Teams reported 42% fewer escaped defects."
    llm = CapturingLLM()
    ContentPlanner(llm_client=llm).plan(
        _template("freeform"),
        bundle,
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert "Allowed numeric tokens" in llm.prompt
    assert "42%" in llm.prompt
    assert "Sources may only be Uploaded source or [source needed]" in llm.prompt
    assert "Do not invent document names" in llm.prompt


def test_planner_extracts_chart_metrics_from_qwen_data_points() -> None:
    class ChartSpecLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "chart",
                        "action_title": "Quantify production readiness before scaling AI development",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Adoption is high enough to require operating discipline."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": {
                            "type": "bar_chart",
                            "data_points": [
                                {"label": "Developers", "value": 85, "unit": "%"},
                                {"label": "AI-generated code", "value": 95, "unit": "%"},
                            ],
                        },
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the implication.",
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    bundle = _bundle()
    bundle.sections[0].content += " Developers reached 85% adoption and 95% AI-generated code."
    outlines, warnings = ContentPlanner(llm_client=ChartSpecLLM()).plan(
        _template("freeform"),
        bundle,
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert outlines[0].layout_json["layout"] == "chart"
    assert outlines[0].content_json["metrics"] == [
        {"label": "Developers", "value": 85, "unit": "%"},
        {"label": "AI-generated code", "value": 95, "unit": "%"},
    ]
    assert not warnings


def test_planner_promotes_numeric_chart_slide_without_chart_spec() -> None:
    class NumericChartLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "chart",
                        "action_title": "Visualize AI adoption before scaling delivery",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": [
                                    "Developers using AI tools reached 85% by 2025.",
                                    "Minimum context tokens reached 32,000.",
                                ],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the implication.",
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    bundle = _bundle()
    bundle.sections[0].content += " Developers using AI tools reached 85% by 2025 with 32,000 context tokens."
    outlines, warnings = ContentPlanner(llm_client=NumericChartLLM()).plan(
        _template("freeform"),
        bundle,
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert outlines[0].layout_json["layout"] == "chart"
    assert outlines[0].content_json["metrics"][:2] == [
        {"label": "Developers using AI tools reached", "value": 85, "unit": "%"},
        {"label": "Minimum context tokens reached", "value": 32000, "unit": None},
    ]
    assert not warnings


def test_brand_builder_outputs_valid_pptx(tmp_path: Path) -> None:
    planner = ContentPlanner()
    outlines, _ = planner.plan(
        _template("brand"),
        _bundle(),
        instructions="Create a brand-aligned executive deck.",
        generation_mode="brand",
    )
    output_path = tmp_path / "brand-output.pptx"
    builder = PptxBuilder(node_runner=object())  # renderer path does not use Node

    warnings = builder.build_deck(_template("brand"), outlines, output_path, tmp_path)

    assert warnings == []
    assert output_path.exists()
    with zipfile.ZipFile(output_path, "r") as pptx_zip:
        assert pptx_zip.testzip() is None
        assert "[Content_Types].xml" in pptx_zip.namelist()
    rendered = Presentation(output_path.as_posix())
    assert len(rendered.slides) == len(outlines)


def test_strict_xml_injector_updates_text_without_python_pptx_write(tmp_path: Path) -> None:
    template_path, template, outline = _strict_fixture(tmp_path)
    output_path = tmp_path / "strict-output.pptx"

    warnings = StrictSlideInjector().inject(template_path, template, [outline], output_path)

    assert warnings == []
    rendered = Presentation(output_path.as_posix())
    texts = [shape.text for shape in rendered.slides[0].shapes if shape.has_text_frame]
    assert "Beyond Vibe Coding" in texts


def test_template_analyzer_extracts_strict_table_cell_fields(tmp_path: Path) -> None:
    template_path = tmp_path / "strict-table-template.pptx"
    _write_table_template(template_path)

    profile, _ = TemplateAnalyzer().analyze(
        template_path,
        template_name="Strict Table",
        template_type="strict",
        template_id="strict-table",
    )

    assert profile.slides[0].mode == "strict"
    assert profile.slides[0].slide_schema is not None
    locations = {field.location for field in profile.slides[0].slide_schema.fields}
    assert "table:DecisionTable:1:1" in locations


def test_strict_xml_injector_updates_table_cell_without_rebuilding_table(tmp_path: Path) -> None:
    template_path = tmp_path / "strict-table-template.pptx"
    _write_table_template(template_path)
    template = _template("strict", source_file=template_path.as_posix())
    template.slides = [
        SlideSpec(
            index=0,
            mode="strict",
            label="Decision Table",
            schema=SlideSchema(
                fields=[
                    SlideField(
                        id="decision_table_2_2",
                        type="text",
                        location="table:DecisionTable:1:1",
                        required=True,
                    )
                ]
            ),
        )
    ]
    outline = SlideOutline(
        id="outline-1",
        job_id="job-1",
        slide_index=0,
        mode="strict",
        label="Decision Table",
        content_json={"fields": {"decision_table_2_2": "Launch controlled pilot"}},
        layout_json={"layout": "strict", "visual_elements": []},
        created_at=_timestamp(),
    )
    output_path = tmp_path / "strict-table-output.pptx"

    warnings = StrictSlideInjector().inject(template_path, template, [outline], output_path)

    assert warnings == []
    rendered = Presentation(output_path.as_posix())
    table = next(shape.table for shape in rendered.slides[0].shapes if shape.has_table)
    assert table.cell(1, 1).text == "Launch controlled pilot"
    assert table.cell(0, 0).text == "Decision"
    assert table.cell(1, 0).text == "Recommendation"


def test_template_analyzer_extracts_strict_chart_fields(tmp_path: Path) -> None:
    template_path = tmp_path / "strict-chart-template.pptx"
    _write_chart_template(template_path)

    profile, _ = TemplateAnalyzer().analyze(
        template_path,
        template_name="Strict Chart",
        template_type="strict",
        template_id="strict-chart",
    )

    assert profile.slides[0].mode == "strict"
    assert profile.slides[0].slide_schema is not None
    locations = {field.location for field in profile.slides[0].slide_schema.fields}
    assert "chart:RevenueChart:series_name:0" in locations
    assert "chart:RevenueChart:category:1" in locations
    assert "chart:RevenueChart:value:0:1" in locations


def test_strict_xml_injector_updates_chart_cache_values(tmp_path: Path) -> None:
    template_path = tmp_path / "strict-chart-template.pptx"
    _write_chart_template(template_path)
    template = _template("strict", source_file=template_path.as_posix())
    template.slides = [
        SlideSpec(
            index=0,
            mode="strict",
            label="Revenue Chart",
            schema=SlideSchema(
                fields=[
                    SlideField(
                        id="revenue_chart_series_1_name",
                        type="text",
                        location="chart:RevenueChart:series_name:0",
                        required=True,
                    ),
                    SlideField(
                        id="revenue_chart_category_2",
                        type="text",
                        location="chart:RevenueChart:category:1",
                        required=True,
                    ),
                    SlideField(
                        id="revenue_chart_series_1_value_2",
                        type="number",
                        location="chart:RevenueChart:value:0:1",
                        required=True,
                    ),
                ]
            ),
        )
    ]
    outline = SlideOutline(
        id="outline-1",
        job_id="job-1",
        slide_index=0,
        mode="strict",
        label="Revenue Chart",
        content_json={
            "fields": {
                "revenue_chart_series_1_name": "Target",
                "revenue_chart_category_2": "Scaled pilots",
                "revenue_chart_series_1_value_2": 35,
            }
        },
        layout_json={"layout": "strict", "visual_elements": []},
        created_at=_timestamp(),
    )
    output_path = tmp_path / "strict-chart-output.pptx"

    warnings = StrictSlideInjector().inject(template_path, template, [outline], output_path)

    assert warnings == []
    chart_xml = _read_chart_xml(output_path)
    assert _chart_text(chart_xml, ".//c:ser/c:tx//c:v") == "Target"
    assert _chart_text(chart_xml, ".//c:ser/c:cat//c:pt[@idx='1']/c:v") == "Scaled pilots"
    assert _chart_text(chart_xml, ".//c:ser/c:val//c:pt[@idx='1']/c:v") == "35.0"
    workbook = _read_embedded_workbook(output_path)
    assert workbook["Sheet1"]["B1"].value == "Target"
    assert workbook["Sheet1"]["A3"].value == "Scaled pilots"
    assert workbook["Sheet1"]["B3"].value == 35


def test_strict_builder_outputs_valid_pptx(tmp_path: Path) -> None:
    template_path, template, outline = _strict_fixture(tmp_path)
    output_path = tmp_path / "strict-builder-output.pptx"
    builder = PptxBuilder(node_runner=object())

    warnings = builder.build_deck(template, [outline], output_path, tmp_path)

    assert warnings == []
    with zipfile.ZipFile(output_path, "r") as pptx_zip:
        assert pptx_zip.testzip() is None
    rendered = Presentation(output_path.as_posix())
    texts = [shape.text for shape in rendered.slides[0].shapes if shape.has_text_frame]
    assert "Beyond Vibe Coding" in texts


def test_strict_planner_semantically_maps_common_text_fields() -> None:
    template = _template("strict")
    template.slides = [
        SlideSpec(
            index=0,
            mode="strict",
            label="Strict Summary",
            schema=SlideSchema(
                fields=[
                    SlideField(
                        id="key_implication",
                        type="text",
                        location="shape:KeyImplication",
                        required=True,
                    )
                ]
            ),
        )
    ]

    outlines, warnings = ContentPlanner().plan(
        template,
        _bundle(),
        instructions="Populate strict fields.",
        generation_mode="strict",
    )

    assert warnings == []
    assert outlines[0].content_json["fields"]["key_implication"] != "[INSERT CONTENT HERE]"


def test_strict_planner_uses_insert_placeholder_for_unmapped_fields() -> None:
    template = _template("strict")
    template.slides = [
        SlideSpec(
            index=0,
            mode="strict",
            label="Strict Summary",
            schema=SlideSchema(
                fields=[
                    SlideField(
                        id="unmapped_required_field",
                        type="text",
                        location="shape:UnmappedField",
                        required=True,
                    )
                ]
            ),
        )
    ]

    outlines, warnings = ContentPlanner().plan(
        template,
        _bundle(),
        instructions="Populate strict fields.",
        generation_mode="strict",
    )

    assert outlines[0].content_json["fields"]["unmapped_required_field"] == "[INSERT CONTENT HERE]"
    assert warnings == [
        {
            "slide_index": 0,
            "field": "unmapped_required_field",
            "message": "Missing content for strict field.",
        }
    ]


def _strict_fixture(tmp_path: Path) -> tuple[Path, TemplateProfile, SlideOutline]:
    template_path = tmp_path / "strict-template.pptx"
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1))
    box.name = "ProjectTitle"
    box.text = "Old title"
    prs.save(template_path.as_posix())

    template = _template("strict", source_file=template_path.as_posix())
    template.slides = [
        SlideSpec(
            index=0,
            mode="strict",
            label="Title",
            schema=SlideSchema(
                fields=[
                    SlideField(
                        id="project_title",
                        type="text",
                        location="shape:ProjectTitle",
                        required=True,
                    )
                ]
            ),
        )
    ]
    outline = SlideOutline(
        id="outline-1",
        job_id="job-1",
        slide_index=0,
        mode="strict",
        label="Title",
        content_json={"fields": {"project_title": "Beyond Vibe Coding"}},
        layout_json={"layout": "strict", "visual_elements": []},
        created_at=_timestamp(),
    )
    return template_path, template, outline


def _write_table_template(path: Path) -> None:
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    table_shape = slide.shapes.add_table(
        2, 2, Inches(1), Inches(1), Inches(6), Inches(1.4)
    )
    table_shape.name = "DecisionTable"
    table = table_shape.table
    table.cell(0, 0).text = "Decision"
    table.cell(0, 1).text = "Owner"
    table.cell(1, 0).text = "Recommendation"
    table.cell(1, 1).text = "TBD"
    prs.save(path.as_posix())


def _write_chart_template(path: Path) -> None:
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    chart_data = CategoryChartData()
    chart_data.categories = ["Prototype", "Pilot"]
    chart_data.add_series("Current", [10, 20])
    chart_shape = slide.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED,
        Inches(1),
        Inches(1),
        Inches(6),
        Inches(4),
        chart_data,
    )
    chart_shape.name = "RevenueChart"
    prs.save(path.as_posix())


def _read_chart_xml(path: Path) -> etree._Element:
    with zipfile.ZipFile(path, "r") as pptx_zip:
        return etree.fromstring(pptx_zip.read("ppt/charts/chart1.xml"))


def _read_embedded_workbook(path: Path):
    with zipfile.ZipFile(path, "r") as pptx_zip:
        workbook_name = next(
            name for name in pptx_zip.namelist() if name.startswith("ppt/embeddings/")
        )
        return load_workbook(BytesIO(pptx_zip.read(workbook_name)))


def _chart_text(chart_xml: etree._Element, xpath: str) -> str:
    ns = {"c": "http://schemas.openxmlformats.org/drawingml/2006/chart"}
    node = chart_xml.find(xpath, namespaces=ns)
    assert node is not None
    return node.text
