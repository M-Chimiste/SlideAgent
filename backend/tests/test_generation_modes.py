import json
import re
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
from app.models.document import DocumentBundle, DocumentMetadata, DocumentMetric, DocumentSection
from app.models.generation import ContentBlock, DeckBlueprint, DeckSpec, GeneratedSlideSpec
from app.models.outline import SlideOutline
from app.models.planning import StoryMap
from app.models.template import SlideField, SlideSchema, SlideSpec, TemplateProfile
from app.services.content_planner import ContentPlanner
from app.services.document_ingester import DocumentIngester
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


def _rich_bundle(job_id: str = "job-rich") -> DocumentBundle:
    sections = [
        DocumentSection(
            title=f"Chapter {idx}: Agentic Engineering Practice",
            level=1,
            content=(
                "Vibe coding works for early exploration, but teams need persistent "
                "context, explicit acceptance criteria, source-backed review, and "
                "repeatable workflow memory before using AI agents on production code. "
                "The operating model should define ownership, rules, review gates, "
                "and update triggers so the next session inherits the right context."
            ),
            source_doc_id="beyond-vibe",
        )
        for idx in range(1, 10)
    ]
    return DocumentBundle(
        job_id=job_id,
        sections=sections,
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Beyond Vibe Coding"),
        content_inventory=[
            "Memory bank hierarchy",
            "Rules files",
            "Review gates",
            "Decision log",
        ],
    )


def test_openai_compatible_client_extracts_json_from_fenced_response() -> None:
    response = """Here is the plan:
```json
{"deck_title":"Test","slides":[]}
```"""
    payload = OpenAICompatibleClient.extract_json(response)
    assert payload == {"deck_title": "Test", "slides": []}


def test_planner_repairs_dangling_sentence_fragments() -> None:
    planner = ContentPlanner()

    cleaned = planner._phrase(
        "The following architecture is adapted from the Cline Memory Bank methodology, "
        "which has emerged as a",
        "",
    )

    assert cleaned == "The following architecture is adapted from the Cline Memory Bank methodology"
    assert not cleaned.endswith("as a")
    assert planner._truncate_title(
        "The Memory Bank architecture provides the AI with everything needed to work effectively without prior"
    ).endswith("without") is False
    assert planner._truncate_title(
        "The Memory Bank consists of six core files arranged in a dependency hierarchy for optimal"
    ).endswith("optimal") is False
    assert (
        planner._truncate_title(
            "Commit to the Agentic Coding framework to ensure reliable"
        )
        == "Commit to the Agentic Coding framework"
    )
    assert (
        planner._truncate_title(
            "Commit to Agentic Coding to ensure reliable, traceable"
        )
        == "Commit to Agentic Coding"
    )


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
    assert FakeHTTPClient.payload["messages"][0]["content"].endswith("/no_think")


def test_openai_compatible_client_retries_non_json_response(monkeypatch) -> None:
    class FakeResponse:
        def __init__(self, content: str) -> None:
            self.content = content

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": self.content}}]}

    class FakeHTTPClient:
        payloads: list[dict] = []

        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        def __enter__(self) -> "FakeHTTPClient":
            return self

        def __exit__(self, *args) -> None:
            return None

        def post(self, url: str, json: dict, headers: dict) -> FakeResponse:
            self.payloads.append(json)
            if len(self.payloads) == 1:
                return FakeResponse("I cannot comply with JSON.")
            return FakeResponse('{"deck_title":"Recovered","slides":[]}')

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

    payload = client.complete_json("Return JSON.", "Create a deck.", max_tokens=32)

    assert payload == {"deck_title": "Recovered", "slides": []}
    assert len(FakeHTTPClient.payloads) == 2
    assert "previous response was not parseable" in FakeHTTPClient.payloads[1]["messages"][1]["content"]


def test_openai_compatible_client_extracts_list_content_text() -> None:
    text = OpenAICompatibleClient._extract_message_text(
        {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "text", "text": '{"deck_title":"A"'},
                            {"type": "text", "text": ',"slides":[]}'},
                        ]
                    }
                }
            ]
        }
    )

    assert text == '{"deck_title":"A"\n,"slides":[]}'


def test_openai_compatible_client_extracts_reasoning_content_when_content_empty() -> None:
    text = OpenAICompatibleClient._extract_message_text(
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": '{"deck_title":"A","slides":[]}',
                    }
                }
            ]
        }
    )

    assert text == '{"deck_title":"A","slides":[]}'


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


def test_source_rich_fallback_uses_adaptive_blueprint_and_archetypes() -> None:
    outlines, warnings = ContentPlanner().plan(
        _template("freeform"),
        _rich_bundle(),
        instructions="Create a consulting deck about moving beyond vibe coding.",
        generation_mode="freeform",
        quality_profile="showcase",
        length_strategy="auto",
    )

    archetypes = [outline.content_json["archetype"] for outline in outlines]
    titles = [outline.content_json["action_title"] for outline in outlines]

    assert 12 <= len(outlines) <= 16
    assert len(set(archetypes)) >= 7
    assert len(set(titles)) == len(titles)
    assert outlines[0].content_json["narrative_role"] == "cover"
    assert outlines[0].layout_json["layout"] == "cover"
    assert all(outline.content_json.get("exhibit_spec") for outline in outlines)
    assert any(archetype == "comparison_table" for archetype in archetypes)
    assert any(archetype == "code_panel" for archetype in archetypes)
    assert any(archetype == "matrix_2x2" for archetype in archetypes)
    assert any(archetype == "callouts" for archetype in archetypes)
    assert any(archetype == "icon_rows" for archetype in archetypes)
    assert sum(
        archetype in {"dependency_map", "framework_cycle", "code_panel", "table_reference"}
        for archetype in archetypes
    ) <= 5
    assert any(
        warning["field"] == "llm_planning"
        and "not configured" in warning["message"]
        for warning in warnings
    )


def test_source_rich_expanded_blueprint_matches_reference_deck_length() -> None:
    planner = ContentPlanner()
    blueprint = planner._build_blueprint(
        _rich_bundle(),
        "Create a consulting deck about moving beyond vibe coding.",
        "freeform",
        quality_profile="fast",
        length_strategy="expanded",
    )

    assert blueprint.target_slide_count == 18
    assert len(blueprint.archetype_sequence) == 18
    assert len(set(blueprint.archetype_sequence)) >= 14


def test_fallback_executive_summary_includes_metric_proof_points() -> None:
    bundle = _bundle()
    bundle.metrics = [
        DocumentMetric(
            label="Developers regularly using AI tools",
            value=85,
            unit="%",
            source_doc_id="doc-1",
        ),
        DocumentMetric(
            label="AI-generated codebases",
            value=95,
            unit="%",
            source_doc_id="doc-1",
        ),
    ]
    bundle.sections[0].content += " Developers regularly using AI tools reached 85%."
    bundle.sections[0].content += " AI-generated codebases reached 95%."

    outlines, _warnings = ContentPlanner().plan(
        _template("freeform"),
        bundle,
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
        quality_profile="showcase",
        length_strategy="expanded",
    )

    executive = next(
        outline
        for outline in outlines
        if outline.layout_json["layout"] == "executive_summary"
    )
    proof_points = executive.content_json["exhibit_spec"]["proof_points"]

    assert {point["label"] for point in proof_points} >= {
        "Developers regularly using AI tools",
        "AI-generated codebases",
    }


def test_planner_enriches_legacy_llm_specs_with_exhibit_metadata() -> None:
    class LegacySpecLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "checklist",
                        "action_title": "Adopt the transition through a short checklist",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Create memory files", "Define review gates", "Run pilot"],
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

    outlines, warnings = ContentPlanner(llm_client=LegacySpecLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert outlines[0].content_json["archetype"] == "checklist"
    assert outlines[0].content_json["narrative_role"] == "implementation"
    assert outlines[0].content_json["exhibit_spec"]["type"] == "checklist"
    assert outlines[0].layout_json["archetype"] == "checklist"
    assert not warnings


def test_planner_upgrades_generic_memory_bank_reference_tables() -> None:
    class GenericReferenceLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "reference",
                        "action_title": "Structure the Memory Bank with Core Files",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "table",
                                "body": [
                                    ["Item", "Implication"],
                                    ["Organize files", "Use a memory-bank directory."],
                                ],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the reference artifacts.",
                        "archetype": "table_reference",
                        "narrative_role": "reference",
                        "exhibit_spec": {
                            "type": "reference_table",
                            "columns": ["Item", "Implication"],
                            "rows": [["Organize files", "Use a memory-bank directory."]],
                        },
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=GenericReferenceLLM()).plan(
        _template("freeform"),
        _rich_bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    exhibit = outlines[0].content_json["exhibit_spec"]

    assert warnings == []
    assert outlines[0].layout_json["layout"] == "table_reference"
    assert exhibit["columns"] == ["File", "Role", "Update trigger"]
    assert any(row[0] == "projectbrief.md" for row in exhibit["rows"])


def test_planner_ignores_table_width_metadata_for_numeric_grounding() -> None:
    class ColumnMetadataLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "comparison",
                        "action_title": "Contrast vibe coding with managed agentic engineering",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["The old model relies on memory; the new model uses structure."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the comparison.",
                        "archetype": "comparison_table",
                        "narrative_role": "evidence",
                        "exhibit_spec": {
                            "type": "comparison_table",
                            "columns": [
                                {"name": "Aspect", "width": "20%"},
                                {"name": "Vibe coding", "width": "40%"},
                                {"name": "Managed agentic work", "width": "40%"},
                            ],
                            "rows": [
                                {
                                    "label": "Context",
                                    "values": ["Chat history", "Persistent memory"],
                                }
                            ],
                        },
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=ColumnMetadataLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    content = outlines[0].content_json

    assert not any(warning["field"] == "source_coverage" for warning in warnings)
    assert content["sources"] == ["Uploaded source"]
    assert "[source needed]" not in str(content["exhibit_spec"])


def test_planner_builds_contextual_code_panel_specs() -> None:
    section = DocumentSection(
        title="3.3 When and How to Update",
        level=2,
        content=(
            "Update memory after meaningful changes so context does not go stale "
            "during the workflow."
        ),
        source_doc_id="beyond-vibe",
    )

    exhibit = ContentPlanner()._exhibit_for_archetype(
        "code_panel",
        section,
        [section],
        [],
    )

    assert exhibit["title"] == "memory-bank/update-protocol.md"
    assert "activeContext.md" in exhibit["lines"][0]
    assert "progress.md" in " ".join(exhibit["lines"])

    reference_exhibit = ContentPlanner()._exhibit_for_archetype(
        "reference",
        DocumentSection(
            title="3. The Memory Bank",
            level=1,
            content="The memory bank acts as persistent context for future sessions.",
            source_doc_id="beyond-vibe",
        ),
        [section],
        [],
    )

    assert reference_exhibit["type"] == "code_panel"
    assert reference_exhibit["title"] == "memory-bank/README.md"

    cycle_exhibit = ContentPlanner()._exhibit_for_archetype(
        "reference",
        DocumentSection(
            title="4.1 The Six-Phase Loop",
            level=2,
            content="The agentic cycle uses phases to frame, prime, generate, review, and reset.",
            source_doc_id="beyond-vibe",
        ),
        [section],
        [],
    )

    assert cycle_exhibit["title"] == "agentic-cycle.md"
    assert "Prime the agent" in cycle_exhibit["lines"][1]

    manager_exhibit = ContentPlanner()._exhibit_for_archetype(
        "code_panel",
        DocumentSection(
            title="2.1 The Developer as Product Manager",
            level=2,
            content="The developer manages an AI employee by assigning scoped work.",
            source_doc_id="beyond-vibe",
        ),
        [section],
        [],
    )

    assert manager_exhibit["title"] == "agent-brief.md"
    assert "assigning work" in manager_exhibit["lines"][0]


def test_section_title_cleanup_removes_multi_level_numbers() -> None:
    planner = ContentPlanner()

    assert planner._clean_section_title("3.1 The Core Files") == "The Core Files"
    assert planner._clean_section_title("8.3 The Accept-All Reflex") == "The Accept-All Reflex"
    assert (
        planner._clean_section_title("4.1 The Agentic Cycle: A Workflow for Reliability")
        == "The Agentic Cycle"
    )


def test_update_section_title_rewrites_without_multiple_messages() -> None:
    title = ContentPlanner()._action_title(
        "3.3 When and How to Update",
        "Update memory after meaningful changes so context does not go stale.",
    )

    assert title == "Update memory after meaningful changes"
    assert " and " not in title.lower()


def test_themed_title_frames_prioritize_specific_cues_before_memory() -> None:
    planner = ContentPlanner()

    assert planner._themed_action_title(
        "context rot",
        "context rot occurs when finite windows erase project memory",
    ) == "Eliminate context rot before it undermines reliability"
    assert planner._themed_action_title(
        "the agentic cycle",
        "the workflow uses a repeatable cycle and reset phase",
    ) == "Run the agentic cycle as a repeatable operating loop"
    assert planner._themed_action_title(
        "markdown-driven development",
        "markdown rules preserve constraints as context changes",
    ) == "Codify markdown-driven development into rules the team can reuse"


def test_fallback_section_selection_uses_blueprint_source_map() -> None:
    sections = [
        DocumentSection(title="Overview", level=1, content="Intro", source_doc_id="doc"),
        DocumentSection(
            title="3.3 When and How to Update",
            level=2,
            content="Update memory after meaningful changes.",
            source_doc_id="doc",
        ),
    ]
    blueprint = DeckBlueprint(
        deck_title="Beyond Vibe Coding",
        audience="Engineering leaders",
        core_thesis="Persistent context makes AI work reliable.",
        target_slide_count=2,
        story_beats=[{"label": "Open"}, {"label": "Reference"}],
        section_plan=[{"label": "Open"}, {"label": "Reference"}],
        archetype_sequence=["cover", "code_panel"],
        source_coverage_map={"2": ["doc:When and How to Update"]},
    )

    section = ContentPlanner()._section_for_blueprint_slot(1, sections, blueprint)

    assert section.title == "3.3 When and How to Update"


def test_blueprint_source_map_spans_long_documents() -> None:
    planner = ContentPlanner()
    bundle = DocumentBundle(
        job_id="long-doc",
        sections=[
            DocumentSection(
                title=f"Chapter {index}",
                level=1,
                content=f"Evidence from chapter {index}.",
                source_doc_id="doc",
            )
            for index in range(1, 31)
        ],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Long Document"),
        content_inventory=[],
    )

    source_map = planner._source_coverage_map(bundle, target_slide_count=5)

    assert "Chapter 1" in source_map["1"][0]
    assert "Chapter 30" in source_map["5"][0]
    assert len({refs[0] for refs in source_map.values()}) == 5


def test_blueprint_source_map_represents_multiple_documents() -> None:
    planner = ContentPlanner()
    bundle = DocumentBundle(
        job_id="multi-doc",
        sections=[
            DocumentSection(
                title=f"Alpha {index}",
                level=1,
                content=f"Alpha document section {index}.",
                source_doc_id="alpha",
            )
            for index in range(1, 6)
        ]
        + [
            DocumentSection(
                title=f"Beta {index}",
                level=1,
                content=f"Beta document section {index}.",
                source_doc_id="beta",
            )
            for index in range(1, 6)
        ],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Multi Document"),
        content_inventory=[],
    )

    source_map = planner._source_coverage_map(bundle, target_slide_count=4)
    refs = [refs[0] for refs in source_map.values()]

    assert any(ref.startswith("alpha:") for ref in refs)
    assert any(ref.startswith("beta:") for ref in refs)


def test_planner_source_packet_includes_whole_document_outline() -> None:
    planner = ContentPlanner()
    bundle = DocumentBundle(
        job_id="long-doc",
        sections=[
            DocumentSection(
                title=f"Chapter {index}",
                level=1,
                content=(
                    f"Evidence from chapter {index}. "
                    f"Decision implication {index} should inform the story."
                ),
                source_doc_id="doc",
            )
            for index in range(1, 31)
        ],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Long Document"),
        content_inventory=[],
    )
    blueprint = DeckBlueprint(
        deck_title="Long Document",
        audience="Engineering leaders",
        core_thesis="The whole document should inform the deck.",
        target_slide_count=5,
        story_beats=[],
        section_plan=[],
        archetype_sequence=[
            "cover",
            "executive_summary",
            "comparison_table",
            "checklist",
            "closing_recommendation",
        ],
        source_coverage_map=planner._source_coverage_map(bundle, target_slide_count=5),
    )

    packet = planner._planner_source_packet(bundle, blueprint, "balanced")

    outline_titles = [
        section["title"] for section in packet["document_outline"]["sections"]
    ]
    detailed_titles = [section["title"] for section in packet["sections"]]
    assert packet["document_outline"]["section_count"] == 30
    assert "Chapter 30" in outline_titles
    assert "Chapter 30" in detailed_titles


def test_planner_source_packet_caps_huge_document_outline() -> None:
    planner = ContentPlanner()
    bundle = DocumentBundle(
        job_id="huge-doc",
        sections=[
            DocumentSection(
                title=f"Chapter {index}",
                level=1,
                content=(
                    f"Evidence from chapter {index}. "
                    f"Decision implication {index} should inform the story."
                ),
                source_doc_id="doc",
            )
            for index in range(1, 151)
        ],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Huge Document"),
        content_inventory=[],
    )
    blueprint = DeckBlueprint(
        deck_title="Huge Document",
        audience="Engineering leaders",
        core_thesis="The full document should inform the deck.",
        target_slide_count=12,
        story_beats=[],
        section_plan=[],
        archetype_sequence=["cover"] * 12,
        source_coverage_map=planner._source_coverage_map(bundle, target_slide_count=12),
    )

    packet = planner._planner_source_packet(bundle, blueprint, "balanced")
    outline_titles = [
        section["title"] for section in packet["document_outline"]["sections"]
    ]

    assert packet["document_outline"]["section_count"] == 150
    assert packet["document_outline"]["included_section_count"] == 80
    assert packet["document_outline"]["omitted_section_count"] == 70
    assert packet["document_outline"]["coverage"] == "representative"
    assert "Chapter 150" in outline_titles


def test_source_compression_spans_long_documents_and_estimates_tokens() -> None:
    planner = ContentPlanner()
    bundle = DocumentBundle(
        job_id="long-compression",
        sections=[
            DocumentSection(
                title=f"Chapter {index}",
                level=1,
                content=f"Evidence from chapter {index}. Risk and recommendation {index}.",
                source_doc_id="doc",
            )
            for index in range(1, 31)
        ],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Long Compression"),
        content_inventory=[],
    )

    compression = planner._build_source_compression(bundle, "balanced")
    titles = [unit.title for unit in compression.evidence_units]

    assert compression.section_count == 30
    assert compression.coverage == "full"
    assert compression.estimated_tokens > 0
    assert "Chapter 1" in titles
    assert "Chapter 30" in titles
    assert compression.tensions


def test_source_compression_represents_multiple_documents() -> None:
    planner = ContentPlanner()
    bundle = DocumentBundle(
        job_id="multi-compression",
        sections=[
            DocumentSection(
                title="Alpha opening",
                level=1,
                content="Alpha evidence creates the initial problem.",
                source_doc_id="alpha",
            ),
            DocumentSection(
                title="Beta opening",
                level=1,
                content="Beta evidence defines the recommendation.",
                source_doc_id="beta",
            ),
        ],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Multi Compression"),
        content_inventory=[],
    )

    compression = planner._build_source_compression(bundle, "fast")

    assert {entry["source_doc_id"] for entry in compression.document_manifest} == {
        "alpha",
        "beta",
    }
    assert {unit.source_doc_id for unit in compression.evidence_units} == {
        "alpha",
        "beta",
    }


def test_story_map_uses_llm_and_fallback_when_deck_planning_fails() -> None:
    class StoryMapLLM:
        def __init__(self) -> None:
            self.prompts = []

        def complete_json(self, **kwargs):
            self.prompts.append(kwargs["user_prompt"])
            if "Create a consulting story map" in kwargs["user_prompt"]:
                return {
                    "thesis": "Persistent context improves delivery.",
                    "narrative_arc": "Situation -> Complication -> Resolution",
                    "recommendation": "Adopt source-backed review.",
                    "beats": [
                        {
                            "beat_number": 1,
                            "role": "cover",
                            "claim": "Translate persistent context into a delivery decision",
                            "source_refs": ["doc-1:Developer Productivity"],
                            "preferred_exhibit": "cover",
                            "rationale": "Set the thesis.",
                        },
                        {
                            "beat_number": 2,
                            "role": "evidence",
                            "claim": "Use source-backed review to reduce delivery risk",
                            "source_refs": ["doc-1:Quality Risk"],
                            "preferred_exhibit": "callouts",
                            "rationale": "Support the decision.",
                        },
                    ],
                }
            return None

    llm = StoryMapLLM()
    planner = ContentPlanner(llm_client=llm)
    outlines, warnings = planner.plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
        quality_profile="fast",
    )

    assert outlines
    assert planner.last_planning_artifacts["story-map"]["status"] == "llm"
    assert any("Story map:" in prompt for prompt in llm.prompts)
    assert any(warning["field"] == "llm_planning" for warning in warnings)


def test_story_map_falls_back_on_malformed_llm_response() -> None:
    class MalformedStoryMapLLM:
        def complete_json(self, **kwargs):
            if "Create a consulting story map" in kwargs["user_prompt"]:
                return {"beats": []}
            return None

    planner = ContentPlanner(llm_client=MalformedStoryMapLLM())
    outlines, _warnings = planner.plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
        quality_profile="fast",
    )

    assert outlines
    story_map = planner.last_planning_artifacts["story-map"]
    assert story_map["status"] == "fallback"
    assert "contained no beats" in story_map["fallback_reason"]


def test_qwen_planner_uses_deterministic_story_map_to_avoid_extra_llm_call() -> None:
    class QwenDeckLLM:
        model = "qwen3.6-35b-a3b-mtp"

        def __init__(self) -> None:
            self.prompts = []

        def complete_json(self, **kwargs):
            self.prompts.append(kwargs["user_prompt"])
            assert "Create a consulting story map" not in kwargs["user_prompt"]
            target = int(re.search(r"Create a (\d+)-slide", kwargs["user_prompt"]).group(1))
            slides = [
                {
                    "slide_number": 1,
                    "slide_type": "cover",
                    "action_title": "Translate AI delivery into an executive operating decision",
                    "subheading": "Persistent context improves delivery reliability.",
                    "content_blocks": [
                        {
                            "type": "bullets",
                            "body": ["Persistent context improves delivery reliability."],
                            "annotations": [],
                            "callouts": [],
                        }
                    ],
                    "chart_spec": None,
                    "sources": ["Uploaded source"],
                    "speaker_notes": "Set the thesis.",
                    "archetype": "cover",
                    "narrative_role": "cover",
                    "exhibit_spec": {"type": "cover"},
                    "source_refs": ["doc-1:Developer Productivity"],
                    "qa": {
                        "consulting_status": "pending",
                        "visual_status": "pending",
                        "issues": [],
                    },
                }
            ]
            workflow_names = [
                "priority intake",
                "architecture review",
                "acceptance testing",
                "release readiness",
                "handoff governance",
                "memory refresh",
                "quality review",
                "decision logging",
                "operating cadence",
                "risk triage",
            ]
            for number in range(2, target + 1):
                workflow = workflow_names[(number - 2) % len(workflow_names)]
                slides.append(
                    {
                        "slide_number": number,
                        "slide_type": "content",
                        "action_title": f"Use source-backed review to reduce {workflow} risk",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Testing and acceptance criteria reduce quality risk."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the implication.",
                        "archetype": "callouts",
                        "narrative_role": "evidence",
                        "exhibit_spec": {
                            "type": "callouts",
                            "points": ["Testing and acceptance criteria reduce quality risk."],
                        },
                        "source_refs": ["doc-1:Quality Risk"],
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

    llm = QwenDeckLLM()
    planner = ContentPlanner(llm_client=llm)
    outlines, warnings = planner.plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
        quality_profile="fast",
    )

    assert outlines
    assert len(llm.prompts) == 1
    story_map = planner.last_planning_artifacts["story-map"]
    assert story_map["status"] == "fallback"
    assert "local Qwen planner" in story_map["fallback_reason"]
    assert not any(warning["field"] == "llm_planning" for warning in warnings)


def test_llm_deck_payload_must_match_blueprint_slide_count() -> None:
    blueprint = DeckBlueprint(
        deck_title="Beyond Vibe Coding",
        audience="Engineering leaders",
        core_thesis="Persistent context improves delivery.",
        target_slide_count=4,
        archetype_sequence=["cover", "executive_summary", "comparison_table", "closing_recommendation"],
        source_coverage_map={},
    )
    payload = {
        "deck_title": "Beyond Vibe Coding",
        "audience": "Engineering leaders",
        "goal": "Improve AI-assisted delivery quality",
        "narrative_arc": "Situation -> Complication -> Resolution",
        "slides": [
            {
                "slide_number": 1,
                "slide_type": "cover",
                "action_title": "Translate AI delivery into an executive operating decision",
                "subheading": "Persistent context improves delivery reliability.",
                "content_blocks": [
                    {
                        "type": "bullets",
                        "body": ["Persistent context improves delivery reliability."],
                    }
                ],
                "sources": ["Uploaded source"],
                "archetype": "cover",
                "narrative_role": "cover",
            }
        ],
    }
    planner = ContentPlanner()

    deck = planner._validate_deck_payload(payload, blueprint)

    assert deck is None
    assert "exactly 4 slides" in (planner._last_planning_error or "")


def test_exhibit_selector_promotes_metric_claim_to_chart() -> None:
    planner = ContentPlanner()
    bundle = _bundle()
    bundle.metrics = [
        DocumentMetric(
            label="Developers using AI",
            value=85,
            unit="%",
            source_doc_id="doc-1",
        ),
        DocumentMetric(
            label="AI-generated code",
            value=95,
            unit="%",
            source_doc_id="doc-1",
        ),
        DocumentMetric(
            label="Context window",
            value=200000,
            unit="tokens",
            source_doc_id="doc-1",
        ),
    ]
    slide = GeneratedSlideSpec(
        slide_number=1,
        slide_type="content",
        action_title="Quantify AI adoption before scaling delivery",
        content_blocks=[ContentBlock(type="bullets", body=["AI adoption reached 85%."])],
        sources=["Uploaded source"],
        source_refs=["doc-1:Developer Productivity"],
        archetype="two_column",
        exhibit_spec={"type": "two_column", "points": ["AI adoption reached 85%."]},
    )
    deck = DeckSpec(deck_title="Selector", slides=[slide])

    planner._apply_exhibit_selection(deck, bundle)

    assert deck.slides[0].archetype == "metric_chart"
    assert deck.slides[0].chart_spec["type"] == "bar"


def test_spec_gate_repairs_duplicate_and_over_budget_slide_specs() -> None:
    planner = ContentPlanner()
    bundle = _bundle()
    blueprint = planner._build_blueprint(
        bundle,
        "Create a deck.",
        "freeform",
        quality_profile="balanced",
        length_strategy="auto",
    )
    compression = planner._build_source_compression(bundle, "balanced")
    story_map = StoryMap(
        status="fallback",
        thesis="Improve delivery quality.",
        recommendation="Adopt source-backed review.",
        beats=[],
    )
    duplicate_body = [" ".join(["Repeated evidence point"] * 20) for _ in range(8)]
    slides = [
        GeneratedSlideSpec(
            slide_number=1,
            slide_type="content",
            action_title="Overview",
            content_blocks=[ContentBlock(type="bullets", body=duplicate_body)],
            sources=["Uploaded source"],
            source_refs=["doc-1:Developer Productivity"],
            archetype="two_column",
            exhibit_spec={"type": "two_column", "points": duplicate_body},
        ),
        GeneratedSlideSpec(
            slide_number=2,
            slide_type="content",
            action_title="Overview",
            content_blocks=[ContentBlock(type="bullets", body=duplicate_body)],
            sources=["Uploaded source"],
            source_refs=["doc-1:Developer Productivity"],
            archetype="two_column",
            exhibit_spec={"type": "two_column", "points": duplicate_body},
        ),
    ]
    deck = DeckSpec(deck_title="Gate", slides=slides, blueprint=blueprint)

    report = planner._run_spec_gate(deck, bundle, compression, story_map)

    categories = {issue.category for issue in report.issues}
    assert "action_title" in categories
    assert "content_budget" in categories
    assert "duplicate_slide" in categories
    assert report.repaired_count >= 3
    assert deck.slides[1].source_refs != ["doc-1:Developer Productivity"]
    assert len(deck.slides[0].content_blocks[0].body) <= 5


def test_spec_gate_removes_supported_model_source_placeholder() -> None:
    planner = ContentPlanner()
    bundle = _bundle()
    bundle.sections[0].content += " Teams reported 42% fewer escaped defects."
    blueprint = planner._build_blueprint(
        bundle,
        "Create a deck.",
        "freeform",
        quality_profile="fast",
        length_strategy="concise",
    )
    compression = planner._build_source_compression(bundle, "fast")
    story_map = StoryMap(
        status="fallback",
        thesis="Improve delivery quality.",
        recommendation="Adopt source-backed review.",
        beats=[],
    )
    deck = DeckSpec(
        deck_title="Gate",
        slides=[
            GeneratedSlideSpec(
                slide_number=1,
                slide_type="content",
                action_title="Reduce escaped defects by 42%",
                content_blocks=[
                    ContentBlock(
                        type="bullets",
                        body=["Teams reported 42% fewer defects after adoption. [source needed]"],
                    )
                ],
                sources=["Uploaded source", "[source needed]"],
                source_refs=["doc-1:Developer Productivity", "[source needed]"],
                archetype="two_column",
                exhibit_spec={
                    "type": "two_column",
                    "points": ["Teams reported 42% fewer defects after adoption. [source needed]"],
                },
            )
        ],
        blueprint=blueprint,
    )

    report = planner._run_spec_gate(deck, bundle, compression, story_map)

    assert "[source needed]" not in deck.slides[0].content_blocks[0].body[0]
    assert "[source needed]" not in str(deck.slides[0].exhibit_spec)
    assert deck.slides[0].sources == ["Uploaded source"]
    assert deck.slides[0].source_refs == ["doc-1:Developer Productivity"]
    assert any(
        repair.action == "remove_supported_source_placeholder"
        for repair in report.repairs
    )
    assert report.unresolved_count == 0


def test_spec_gate_removes_nonnumeric_source_placeholder_when_slide_is_grounded() -> None:
    planner = ContentPlanner()
    bundle = _bundle()
    blueprint = planner._build_blueprint(
        bundle,
        "Create a deck.",
        "freeform",
        quality_profile="fast",
        length_strategy="concise",
    )
    compression = planner._build_source_compression(bundle, "fast")
    story_map = StoryMap(
        status="fallback",
        thesis="Improve delivery quality.",
        recommendation="Adopt source-backed review.",
        beats=[],
    )
    deck = DeckSpec(
        deck_title="Gate",
        slides=[
            GeneratedSlideSpec(
                slide_number=1,
                slide_type="content",
                action_title="Persistent context reduces delivery ambiguity [source needed]",
                content_blocks=[
                    ContentBlock(
                        type="bullets",
                        body=["Persistent context keeps review decisions traceable. [source needed]"],
                    )
                ],
                sources=["Uploaded source", "[source needed]"],
                source_refs=["doc-1:Developer Productivity", "[source needed]"],
                archetype="two_column",
                exhibit_spec={
                    "type": "two_column",
                    "points": [
                        "Persistent context keeps review decisions traceable. [source needed]"
                    ],
                },
            )
        ],
        blueprint=blueprint,
    )

    report = planner._run_spec_gate(deck, bundle, compression, story_map)

    assert "[source needed]" not in deck.slides[0].action_title
    assert "[source needed]" not in deck.slides[0].content_blocks[0].body[0]
    assert "[source needed]" not in str(deck.slides[0].exhibit_spec)
    assert deck.slides[0].source_refs == ["doc-1:Developer Productivity"]
    assert report.unresolved_count == 0


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

    assert any(
        warning["field"] == "llm_planning" and "TimeoutError" in warning["message"]
        for warning in warnings
    )


def test_planner_ignores_malformed_llm_blueprint_metadata() -> None:
    class MalformedBlueprintLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "blueprint": {
                    "deck_title": "Beyond Vibe Coding",
                    "audience": "Engineering leaders",
                    "core_thesis": "Persistent context improves reliability.",
                    "target_slide_count": 1,
                    "story_beats": ["A malformed but harmless beat"],
                    "section_plan": [],
                    "archetype_sequence": ["cover"],
                    "source_coverage_map": {},
                },
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "cover",
                        "action_title": "Adopt Agentic Coding to Manage AI Reliability",
                        "subheading": "A practical operating model",
                        "content_blocks": [
                            {
                                "type": "text",
                                "body": ["Persistent context makes AI work reliable."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Open the deck.",
                        "archetype": "cover",
                        "narrative_role": "cover",
                        "exhibit_spec": {"type": "cover"},
                        "design_intent": "dark editorial cover",
                        "source_refs": ["Uploaded source"],
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=MalformedBlueprintLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert len(outlines) == 1
    assert outlines[0].label == "Beyond Vibe Coding"
    assert outlines[0].content_json["deck_title"] == "Beyond Vibe Coding"
    assert not any(warning["field"] == "llm_planning" for warning in warnings)


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


def test_planner_repairs_qwen_cover_title_concatenation() -> None:
    planner = ContentPlanner()
    deck = DeckSpec(
        deck_title="Beyond Vibe Coding",
        slides=[
            GeneratedSlideSpec(
                slide_number=1,
                slide_type="cover",
                action_title=(
                    "Beyond Vibe Coding a Framework for Agentic Software "
                    "Development How to stop chatting with AI"
                ),
                archetype="cover",
                narrative_role="cover",
            )
        ],
    )

    planner._repair_model_titles(deck)

    assert deck.slides[0].action_title == "Beyond Vibe Coding"


def test_planner_repairs_reviewer_mode_title_artifact() -> None:
    planner = ContentPlanner()
    deck = DeckSpec(
        deck_title="Beyond Vibe Coding",
        slides=[
            GeneratedSlideSpec(
                slide_number=1,
                slide_type="quote",
                action_title=(
                    "Review reviewer mode the developers new core competency "
                    "before trusting the generated output"
                ),
                content_blocks=[
                    ContentBlock(
                        type="bullets",
                        body=["Reviewer mode requires checking outputs against the plan."],
                    )
                ],
                archetype="quote_sidebar",
                narrative_role="decision",
            )
        ],
    )

    planner._repair_model_titles(deck)

    assert deck.slides[0].action_title == "Use reviewer mode as the default quality gate"


def test_planner_repairs_generic_model_action_titles() -> None:
    class GenericTitleLLM:
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
                        "action_title": "Define Specifications",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": [
                                    "Acceptance criteria should constrain generation before agents build."
                                ],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the operating rule.",
                        "archetype": "checklist",
                        "narrative_role": "implementation",
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=GenericTitleLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert outlines[0].label == "Define acceptance criteria before execution begins"
    assert not warnings


def test_planner_repairs_repeated_action_titles_without_slide_suffix() -> None:
    class RepeatedTitleLLM:
        def complete_json(self, **kwargs):
            slides = []
            for idx, archetype in enumerate(["code_panel", "checklist"], start=1):
                slides.append(
                    {
                        "slide_number": idx,
                        "slide_type": "reference" if archetype == "code_panel" else "checklist",
                        "action_title": "Define acceptance criteria before execution begins",
                        "subheading": "Evidence from Quality Risk",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Acceptance criteria make generated work reviewable."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the operating discipline.",
                        "archetype": archetype,
                        "narrative_role": "implementation",
                        "exhibit_spec": {"type": archetype, "items": []},
                        "design_intent": "acceptance criteria operating rules",
                        "source_refs": ["Uploaded source"],
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

    outlines, warnings = ContentPlanner(llm_client=RepeatedTitleLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    titles = [outline.label for outline in outlines]
    assert len(titles) == len(set(titles))
    assert all("for slide" not in title.lower() for title in titles)
    assert titles[1] == "Convert acceptance criteria into pre-execution review gates"
    assert not warnings


def test_planner_removes_ellipsis_from_repaired_action_titles() -> None:
    class EllipsisTitleLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "reference",
                        "action_title": "Standardize a structured set of markdown files... as a reusable reference",
                        "subheading": "Evidence from a structured set of markdown files that preserve context",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Memory files preserve decisions across sessions."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the reference.",
                        "archetype": "table_reference",
                        "narrative_role": "reference",
                        "exhibit_spec": {"type": "reference_table", "rows": []},
                        "design_intent": "compact reference table",
                        "source_refs": ["Uploaded source"],
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=EllipsisTitleLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert "..." not in outlines[0].label
    assert "…" not in outlines[0].label
    assert not warnings


def test_planner_repairs_reference_to_titles_for_code_panels() -> None:
    class ReferenceTitleLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "reference",
                        "action_title": "Turn reference to the six-phase loop",
                        "subheading": "Evidence from agentic cycle",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["The cycle uses frame, prime, generate, review, and reset phases."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the cycle reference.",
                        "archetype": "code_panel",
                        "narrative_role": "reference",
                        "exhibit_spec": {
                            "type": "code_panel",
                            "lines": ["Frame the request", "Review the output"],
                        },
                        "design_intent": "reference the six-phase loop",
                        "source_refs": ["Uploaded source"],
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=ReferenceTitleLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert outlines[0].label == "Codify the operating cycle as reusable rules"
    assert not warnings


def test_planner_repairs_detail_titles_for_code_panels() -> None:
    class DetailTitleLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "reference",
                        "action_title": (
                            "Detail the six-phase loop that guarantees reliable agentic software development"
                        ),
                        "subheading": "Evidence from agentic cycle",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["The six-phase loop structures reliable agentic work."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the cycle reference.",
                        "archetype": "code_panel",
                        "narrative_role": "reference",
                        "exhibit_spec": {
                            "type": "code_panel",
                            "lines": ["Frame the request", "Review the output"],
                        },
                        "design_intent": "reference the six-phase loop",
                        "source_refs": ["Uploaded source"],
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=DetailTitleLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert outlines[0].label == "Codify the operating cycle as reusable rules"
    assert not warnings


def test_planner_repairs_embedded_source_clause_titles() -> None:
    class EmbeddedClauseTitleLLM:
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
                        "action_title": (
                            "Turn context windows are finite even large into an explicit operating decision"
                        ),
                        "subheading": "Evidence from context windows",
                        "content_blocks": [
                            {
                                "type": "chart",
                                "body": [
                                    {"label": "Context window", "value": "1M", "unit": "tokens"}
                                ],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain why external memory is needed.",
                        "archetype": "metric_chart",
                        "narrative_role": "evidence",
                        "exhibit_spec": {
                            "type": "metric_chart",
                            "metrics": [
                                {"label": "Context window", "value": "1M", "unit": "tokens"}
                            ],
                        },
                        "design_intent": "metric chart about finite context windows",
                        "source_refs": ["Uploaded source"],
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=EmbeddedClauseTitleLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert outlines[0].label == "Quantify context-window limits before relying on model memory"
    assert not warnings


def test_planner_repairs_embedded_source_clause_reference_titles() -> None:
    class EmbeddedReferenceClauseLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "reference",
                        "action_title": (
                            "Standardize six core files arranged in a as a reusable reference"
                        ),
                        "subheading": "Evidence from Memory Bank structure",
                        "content_blocks": [
                            {
                                "type": "table",
                                "body": [
                                    ["File", "Role", "Update trigger"],
                                    ["projectbrief.md", "Foundation", "Scope changes"],
                                ],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the reference table.",
                        "archetype": "table_reference",
                        "narrative_role": "reference",
                        "exhibit_spec": {
                            "type": "reference_table",
                            "columns": ["File", "Role", "Update trigger"],
                            "rows": [["projectbrief.md", "Foundation", "Scope changes"]],
                        },
                        "design_intent": "compact memory bank reference table",
                        "source_refs": ["Uploaded source"],
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=EmbeddedReferenceClauseLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert outlines[0].label == "Standardize Memory Bank files as a reusable reference"
    assert not warnings


def test_planner_repairs_awry_memory_reference_titles() -> None:
    class AwryReferenceTitleLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "reference",
                        "action_title": (
                            "Standardize the core files six-file hierarchy as a reusable reference"
                        ),
                        "subheading": "Evidence from Memory Bank structure",
                        "content_blocks": [
                            {
                                "type": "table",
                                "body": [
                                    ["File", "Role", "Update trigger"],
                                    ["projectbrief.md", "Foundation", "Scope changes"],
                                ],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the reference table.",
                        "archetype": "table_reference",
                        "narrative_role": "reference",
                        "exhibit_spec": {
                            "type": "reference_table",
                            "columns": ["File", "Role", "Update trigger"],
                            "rows": [["projectbrief.md", "Foundation", "Scope changes"]],
                        },
                        "design_intent": "compact memory bank reference table",
                        "source_refs": ["Uploaded source"],
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=AwryReferenceTitleLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert outlines[0].label == "Standardize Memory Bank files as a reusable reference"
    assert not warnings


def test_planner_repairs_process_titles_on_closing_slides() -> None:
    class ProcessClosingTitleLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "closing",
                        "action_title": "Run the operating cycle with explicit review gates",
                        "subheading": "Reset sessions after updating memory",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Adopt the cycle as the default operating cadence."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Close with the decision.",
                        "archetype": "closing_recommendation",
                        "narrative_role": "closing",
                        "exhibit_spec": {
                            "type": "recommendation",
                            "recommendation": "Adopt the operating cycle",
                            "next_steps": ["Name owner"],
                        },
                        "design_intent": "closing recommendation",
                        "source_refs": ["Uploaded source"],
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=ProcessClosingTitleLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert outlines[0].label == "Commit to persistent context as the operating default"
    assert not warnings


def test_planner_repairs_wordy_section_divider_titles() -> None:
    class WordyDividerTitleLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "section",
                        "action_title": (
                            "Translate why ephemeral conversations fail into an explicit operating decision"
                        ),
                        "subheading": "Why ephemeral conversations fail professional software development",
                        "content_blocks": [
                            {
                                "type": "text",
                                "body": ["Ephemeral prompting loses context between sessions."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Introduce the next section.",
                        "archetype": "section_divider",
                        "narrative_role": "evidence",
                        "exhibit_spec": {"type": "section_divider"},
                        "design_intent": "dark editorial divider",
                        "source_refs": ["Uploaded source"],
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=WordyDividerTitleLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    # Headline casing lowercases the minor word "from" (AP style, matching the
    # reference deck's titles) while keeping the major words capitalized.
    assert outlines[0].label == "Shift from Ephemeral Chat to Persistent Context"
    assert not warnings


def test_planner_removes_meta_exhibit_language_from_action_titles() -> None:
    class MetaTitleLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "checklist",
                        "action_title": "Use step-by-step guide to establishing memory bank as a distinct exhibit",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Create files", "Assign owners", "Refresh memory"],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the checklist.",
                        "archetype": "checklist",
                        "narrative_role": "implementation",
                        "exhibit_spec": {
                            "type": "checklist",
                            "items": [
                                {"action": "Create files", "owner": "Lead", "timing": "Initial"},
                                {"action": "Assign owners", "owner": "EM", "timing": "Initial"},
                                {"action": "Refresh memory", "owner": "Team", "timing": "Ongoing"},
                            ],
                        },
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=MetaTitleLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert "distinct exhibit" not in outlines[0].label.lower()
    assert outlines[0].label == "Implement the memory bank through a short operating checklist"
    assert not warnings


def test_planner_replaces_meta_storyline_action_titles() -> None:
    class MetaStorylineTitleLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "table_reference",
                        "action_title": "Advance the Storyline with Source-Grounded Evidence",
                        "subheading": "Six-phase operating loop",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": [
                                    "Plan work",
                                    "Generate code",
                                    "Review output",
                                    "Update memory",
                                ],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the reusable reference.",
                        "archetype": "table_reference",
                        "narrative_role": "reference",
                        "design_intent": "compact reference table for the six-phase operating loop",
                        "exhibit_spec": {
                            "type": "table_reference",
                            "columns": ["Phase", "Rule"],
                            "rows": [
                                ["Plan", "Set acceptance criteria"],
                                ["Generate", "Use current context"],
                                ["Review", "Check against source"],
                            ],
                        },
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=MetaStorylineTitleLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert outlines[0].label == "Standardize six-phase operating loop as a reusable reference"
    assert "source-grounded" not in outlines[0].label.lower()
    assert "storyline" not in outlines[0].label.lower()
    assert not warnings


def test_planner_rewrites_soft_beat_titles_before_consulting_qa() -> None:
    class SoftBeatTitleLLM:
        def complete_json(self, **kwargs):
            common = {
                "subheading": "Evidence from uploaded source",
                "content_blocks": [
                    {
                        "type": "bullets",
                        "body": [
                            "Teams need explicit context.",
                            "Review gates improve reliability.",
                            "Shared artifacts preserve decisions.",
                        ],
                        "annotations": [],
                        "callouts": [],
                    }
                ],
                "chart_spec": None,
                "sources": ["Uploaded source"],
                "speaker_notes": "Explain the exhibit.",
                "qa": {
                    "consulting_status": "pending",
                    "visual_status": "pending",
                    "issues": [],
                },
            }
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        **common,
                        "slide_number": 1,
                        "slide_type": "framework",
                        "action_title": "Provide an operating cycle leaders can manage for reliability",
                        "archetype": "framework_cycle",
                        "narrative_role": "framework",
                        "exhibit_spec": {"type": "cycle", "steps": [{"label": "Plan"}]},
                    },
                    {
                        **common,
                        "slide_number": 2,
                        "slide_type": "checklist",
                        "action_title": "Make the next steps executable for immediate adoption",
                        "archetype": "checklist",
                        "narrative_role": "implementation",
                        "exhibit_spec": {
                            "type": "checklist",
                            "items": [
                                {"action": "Create artifacts"},
                                {"action": "Assign owner"},
                                {"action": "Run review"},
                            ],
                        },
                    },
                    {
                        **common,
                        "slide_number": 3,
                        "slide_type": "reference",
                        "action_title": "Provide a compact reference leaders can reuse",
                        "subheading": "Core operating artifacts",
                        "archetype": "table_reference",
                        "narrative_role": "reference",
                        "exhibit_spec": {
                            "type": "reference_table",
                            "columns": ["Artifact", "Role"],
                            "rows": [["rules.md", "Constrains execution"]],
                        },
                    },
                    {
                        **common,
                        "slide_number": 4,
                        "slide_type": "closing",
                        "action_title": "End with a clear recommendation",
                        "archetype": "closing_recommendation",
                        "narrative_role": "closing",
                        "exhibit_spec": {
                            "type": "recommendation",
                            "recommendation": "Approve a governed pilot",
                            "next_steps": ["Name owner"],
                        },
                    },
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=SoftBeatTitleLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    titles = [outline.label for outline in outlines]

    assert "Run the operating cycle with explicit review gates" in titles
    assert "Implement next steps through a short operating checklist" in titles
    assert "Standardize core operating artifacts as a reusable reference" in titles
    assert "Commit to the recommendation with named ownership" in titles
    cycle_spec = outlines[0].content_json["diagram_spec"]
    assert cycle_spec["kind"] == "cycle"
    assert len(cycle_spec["steps"]) >= 4
    assert not any(warning["field"] == "consulting_qa" for warning in warnings)


def test_planner_repairs_sparse_anti_pattern_exhibits() -> None:
    class SparseAntiPatternLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "anti_pattern",
                        "action_title": "Identify anti-patterns before AI work scales",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Context disappears between sessions."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the failure modes.",
                        "archetype": "anti_patterns",
                        "narrative_role": "problem",
                        "exhibit_spec": {
                            "type": "anti_patterns",
                            "patterns": [
                                {
                                    "name": "Context rot",
                                    "symptom": "Context disappears between sessions.",
                                    "better_behavior": "Persist context outside the chat.",
                                }
                            ],
                        },
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=SparseAntiPatternLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    patterns = outlines[0].content_json["exhibit_spec"]["patterns"]

    assert len(patterns) >= 3
    assert all(pattern["name"] and pattern["symptom"] for pattern in patterns[:3])
    assert not warnings


def test_repeated_reference_titles_repair_to_code_panel_action() -> None:
    class DuplicateReferenceLLM:
        def complete_json(self, **kwargs):
            slide = {
                "slide_type": "reference",
                "action_title": "Reference the Six-Phase Loop for Continuous Improvement",
                "subheading": "Evidence from uploaded source",
                "content_blocks": [
                    {
                        "type": "bullets",
                        "body": [
                            "The six-phase loop provides a comprehensive framework.",
                            "Each phase feeds the next, creating a reliable delivery pattern.",
                        ],
                        "annotations": [],
                        "callouts": [],
                    }
                ],
                "chart_spec": None,
                "sources": ["Uploaded source"],
                "speaker_notes": "Explain the reusable loop.",
                "archetype": "reference",
                "narrative_role": "reference",
                "exhibit_spec": {
                    "type": "code_panel",
                    "title": "agentic-cycle.md",
                    "lines": [
                        "Frame the request with an explicit outcome.",
                        "Prime the agent with memory and constraints.",
                        "Review output before updating memory.",
                    ],
                },
                "qa": {
                    "consulting_status": "pending",
                    "visual_status": "pending",
                    "issues": [],
                },
            }
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {"slide_number": 1, **slide},
                    {"slide_number": 2, **slide},
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=DuplicateReferenceLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    titles = [outline.label for outline in outlines]

    assert "Codify the operating cycle as reusable rules" in titles
    assert not any("..." in title for title in titles)
    assert not any("focused recommendation" in title.lower() for title in titles)
    assert not any(warning["field"] == "consulting_qa" for warning in warnings)


def test_planner_varies_generic_llm_slide_layouts() -> None:
    class GenericSlidesLLM:
        def complete_json(self, **kwargs):
            target = int(re.search(r"Create a (\d+)-slide", kwargs["user_prompt"]).group(1))
            titles = [
                "Improve agentic delivery discipline across priority workflows",
                "Standardize context management across software delivery teams",
                "Reduce review gaps through explicit acceptance criteria",
                "Adopt persistent memory to improve agent reliability",
                "Secure production quality with structured oversight",
            ]
            while len(titles) < target:
                suffixes = [
                    "intake",
                    "review",
                    "handoff",
                    "release",
                    "memory",
                    "governance",
                    "cadence",
                ]
                titles.append(
                    "Improve delivery reliability through "
                    f"{suffixes[len(titles) % len(suffixes)]} standards"
                )
            slides = []
            for number, title in enumerate(titles[:target], start=1):
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
        "callouts",
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

    assert outlines[0].content_json["sources"] == ["[source needed]"]
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
    assert "Use source_refs for exact source packet ids" in llm.prompt
    assert "Do not invent document names" in llm.prompt


def test_showcase_planner_uses_richer_source_packet_and_output_budget() -> None:
    class CapturingLLM:
        kwargs = {}

        def complete_json(self, **kwargs):
            self.kwargs = kwargs
            return None

    sections = [
        DocumentSection(
            title=f"Section {idx}",
            level=1,
            content=(
                f"Section {idx} explains the operating model, evidence base, "
                "review gate, ownership model, and implementation implications. "
                "It includes enough detail to support a distinct authored slide."
            ),
            source_doc_id="doc-1",
        )
        for idx in range(1, 19)
    ]
    bundle = _bundle()
    bundle.sections = sections
    llm = CapturingLLM()

    ContentPlanner(llm_client=llm).plan(
        _template("freeform"),
        bundle,
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
        quality_profile="showcase",
        length_strategy="expanded",
    )

    assert llm.kwargs["max_tokens"] == 40000
    prompt = llm.kwargs["user_prompt"]
    packet = json.loads(prompt.split("Source packet: ", 1)[1].split("\nMetrics:", 1)[0])
    assert packet["section_count"] == 18
    assert packet["included_section_count"] == 18
    assert any(section["id"] == "doc-1:Section 18" for section in packet["sections"])
    assert packet["document_outline"]["section_count"] == 18
    assert "key_points" in packet["sections"][0]


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
    assert {
        (metric["label"], metric["value"], metric["unit"])
        for metric in outlines[0].content_json["metrics"]
    } == {
        ("Developers", 85, "%"),
        ("AI-generated code", 95, "%"),
    }
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


def test_document_ingester_extracts_metrics_without_dates() -> None:
    markdown = (
        "February 2026 update. On February 3, 2025, the market was still shifting. "
        "By the end of 2025, roughly 85% of developers were regularly using AI "
        "tools for coding. Y Combinator reported that a quarter of its Winter 2025 "
        "batch had codebases that were 95% AI-generated. The context window ranges "
        "from roughly 32,000 to 200,000 tokens, and some modern advancements have "
        "scaled this window to 1 million tokens."
    )

    metrics = DocumentIngester()._parse_metrics("doc-1", markdown)

    values = {(metric.value, metric.unit) for metric in metrics}
    labels = [metric.label for metric in metrics]
    assert (85, "%") in values
    assert (95, "%") in values
    assert (32_000, "tokens") in values
    assert (200_000, "tokens") in values
    assert (1_000_000, "tokens") in values
    assert not any(metric.unit is None and metric.value in {3, 2025, 2026} for metric in metrics)
    assert any("Developers" in label for label in labels)
    assert "AI-generated codebases" in labels


def test_planner_metric_selection_filters_date_like_values() -> None:
    metrics = [
        DocumentMetric(label="February", value=2026, unit=None, source_doc_id="doc-1"),
        DocumentMetric(label="on February", value=3, unit=None, source_doc_id="doc-1"),
        DocumentMetric(label="Developers using AI tools", value=85, unit="%", source_doc_id="doc-1"),
        DocumentMetric(label="AI-generated codebases", value=95, unit="%", source_doc_id="doc-1"),
        DocumentMetric(label="Context window maximum", value=200_000, unit="tokens", source_doc_id="doc-1"),
    ]

    selected = ContentPlanner()._pick_metrics(metrics, count=3)

    assert selected == [
        {"label": "AI-generated codebases", "value": 95, "unit": "%"},
        {"label": "Developers using AI tools", "value": 85, "unit": "%"},
        {"label": "Context window maximum", "value": 200_000, "unit": "tokens"},
    ]


def test_planner_chart_metric_extraction_skips_leading_years() -> None:
    slide = GeneratedSlideSpec(
        slide_number=1,
        slide_type="chart",
        action_title="Visualize adoption before scaling AI delivery",
        content_blocks=[
            ContentBlock(
                type="bullets",
                body=["By 2025, 85% of developers were regularly using AI tools."],
            )
        ],
    )

    metrics = ContentPlanner()._metrics_from_slide(slide)

    assert metrics == [
        {"label": "developers were regularly using AI tools", "value": 85, "unit": "%"}
    ]


def test_planner_repairs_sparse_comparison_exhibits_before_render() -> None:
    class SparseComparisonLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "comparison",
                        "action_title": "Contrast vibe coding with managed agentic engineering",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "table",
                                "body": [
                                    ["Aspect", "Vibe coding", "Agentic engineering"],
                                    ["Context", "", ""],
                                ],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the comparison.",
                        "archetype": "comparison_table",
                        "narrative_role": "evidence",
                        "exhibit_spec": {
                            "type": "comparison_table",
                            "columns": ["Aspect", "Vibe coding", "Agentic engineering"],
                            "rows": [{"label": "Context", "values": ["", ""]}],
                        },
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=SparseComparisonLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    exhibit = outlines[0].content_json["exhibit_spec"]
    body = outlines[0].content_json["content_blocks"][0]["body"]

    assert warnings == []
    assert exhibit["columns"] == ["Dimension", "Current state", "Target state"]
    assert len(exhibit["rows"]) == 3
    assert all(row["values"][0] and row["values"][1] for row in exhibit["rows"])
    assert body[0] == ["Dimension", "Current state", "Target state"]
    assert len(body) == 4


def test_planner_enriches_single_metric_chart_from_source_metrics() -> None:
    class SparseMetricLLM:
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
                        "action_title": "Quantify adoption pressure before redesigning delivery",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "chart",
                                "body": [
                                    {
                                        "label": "Developers using AI tools",
                                        "value": 85,
                                        "unit": "%",
                                    }
                                ],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": {
                            "type": "bar_chart",
                            "data_points": [
                                {
                                    "label": "Developers using AI tools",
                                    "value": 85,
                                    "unit": "%",
                                }
                            ],
                        },
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the adoption pressure.",
                        "archetype": "metric_chart",
                        "narrative_role": "evidence",
                        "exhibit_spec": {
                            "type": "metric_chart",
                            "metrics": [
                                    {
                                        "label": "Developers using AI tools",
                                        "value": 85,
                                        "unit": "%",
                                    }
                            ],
                        },
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    bundle = _bundle()
    bundle.metrics = [
        DocumentMetric(
            label="Developers regularly using AI tools",
            value=85,
            unit="%",
            source_doc_id="doc-1",
        ),
        DocumentMetric(
            label="AI-generated codebases",
            value=95,
            unit="%",
            source_doc_id="doc-1",
        ),
        DocumentMetric(
            label="Context window",
            value=1_000_000,
            unit="tokens",
            source_doc_id="doc-1",
        ),
    ]
    bundle.sections[0].content += " Developers regularly using AI tools reached 85%."
    bundle.sections[0].content += " AI-generated codebases reached 95%."

    outlines, warnings = ContentPlanner(llm_client=SparseMetricLLM()).plan(
        _template("freeform"),
        bundle,
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    metrics = outlines[0].content_json["metrics"]
    exhibit_metrics = outlines[0].content_json["exhibit_spec"]["metrics"]

    assert warnings == []
    assert len(exhibit_metrics) == 3
    assert {metric["label"] for metric in exhibit_metrics} == {
        "Developers using AI tools",
        "AI-generated codebases",
        "Context window",
    }
    assert len({(metric["value"], metric["unit"]) for metric in exhibit_metrics}) == 3
    assert metrics == exhibit_metrics


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
