# ruff: noqa: F401
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from app.models.document import DocumentBundle, DocumentMetric, DocumentSection
from app.models.generation import ContentBlock, DeckBlueprint, DeckSpec, GeneratedSlideSpec
from app.models.outline import SlideOutline
from app.models.planning import StoryBeat, StoryMap
from app.models.template import SlideSpec, TemplateProfile
from app.services.planning.constants import (
    PLANNER_SYSTEM_PROMPT,
    SOURCE_NEEDED_LABEL,
    UPLOADED_SOURCE_LABEL,
)


class SlideSpecPlanningMixin:
    def _fallback_deck(
        self,
        bundle: DocumentBundle,
        instructions: str,
        mode: str,
        blueprint: DeckBlueprint,
        story_map: StoryMap | None = None,
    ) -> DeckSpec:
        title = bundle.metadata.title or self._title_from_instructions(instructions)
        source_label = UPLOADED_SOURCE_LABEL if bundle.sections else SOURCE_NEEDED_LABEL
        sections = self._pick_sections(bundle.sections)
        if not sections:
            sections = self._sections_from_instructions(instructions)
        metrics = self._pick_metrics(bundle.metrics, count=3)
        roles = self._narrative_roles_for_sequence(blueprint.archetype_sequence)
        slides: list[GeneratedSlideSpec] = []
        for index, archetype in enumerate(blueprint.archetype_sequence):
            role = roles[index] if index < len(roles) else "evidence"
            section = self._section_for_blueprint_slot(index, sections, blueprint)
            slide = self._fallback_slide_for_archetype(
                index=index,
                archetype=archetype,
                role=role,
                title=title,
                section=section,
                sections=sections,
                metrics=metrics,
                source_label=source_label,
                blueprint=blueprint,
                bundle=bundle,
            )
            if story_map:
                self._apply_story_beat_to_slide(slide, story_map, archetype)
            slides.append(slide)
        return DeckSpec(
            deck_title=title,
            audience="Executive audience",
            goal=instructions or "Create an executive-ready recommendation deck.",
            narrative_arc="Situation -> Complication -> Resolution",
            slides=slides,
            blueprint=blueprint,
        )

    def _apply_story_beat_to_slide(
        self,
        slide: GeneratedSlideSpec,
        story_map: StoryMap,
        fallback_archetype: str,
    ) -> None:
        beat = self._story_beat_for_slide(story_map, slide.slide_number)
        if beat is None:
            return
        if slide.archetype not in {"cover", "executive_summary", "closing_recommendation"}:
            selected = self._normalize_archetype(beat.preferred_exhibit or fallback_archetype)
            if selected in {
                "comparison_table",
                "dependency_map",
                "framework_cycle",
                "checklist",
                "code_panel",
                "anti_patterns",
                "quote_sidebar",
                "metric_chart",
                "table_reference",
                "matrix_2x2",
                "callouts",
                "icon_rows",
                "two_column",
            }:
                slide.archetype = selected
                slide.slide_type = self._slide_type_for_archetype(selected)
        if beat.role:
            slide.narrative_role = beat.role
        if beat.claim and slide.archetype not in {"cover"}:
            slide.action_title = self._truncate_title(beat.claim)
        if beat.source_refs:
            slide.source_refs = beat.source_refs
            slide.sources = [UPLOADED_SOURCE_LABEL]
        slide.speaker_notes = beat.rationale or slide.speaker_notes

    def _story_beat_for_slide(
        self,
        story_map: StoryMap,
        slide_number: int,
    ) -> StoryBeat | None:
        for beat in story_map.beats:
            if beat.beat_number == slide_number:
                return beat
        index = slide_number - 1
        if 0 <= index < len(story_map.beats):
            return story_map.beats[index]
        return None

    def _section_for_blueprint_slot(
        self,
        index: int,
        sections: list[DocumentSection],
        blueprint: DeckBlueprint,
    ) -> DocumentSection:
        fallback = sections[min(max(index - 1, 0), len(sections) - 1)]
        source_refs = blueprint.source_coverage_map.get(str(index + 1), [])
        for source_ref in source_refs:
            for section in sections:
                if getattr(section, "source_id", "") == str(source_ref):
                    return section
            title = str(source_ref).split(":", 1)[-1]
            normalized_title = self._clean_section_title(title).casefold()
            if not normalized_title:
                continue
            for section in sections:
                if self._clean_section_title(section.title).casefold() == normalized_title:
                    return section
        return fallback

    def _fallback_slide_for_archetype(
        self,
        index: int,
        archetype: str,
        role: str,
        title: str,
        section: DocumentSection,
        sections: list[DocumentSection],
        metrics: list[dict[str, Any]],
        source_label: str,
        blueprint: DeckBlueprint,
        bundle: DocumentBundle | None = None,
    ) -> GeneratedSlideSpec:
        exhibit_spec = self._exhibit_for_archetype(
            archetype,
            section,
            sections,
            metrics,
            bundle.tables if bundle else None,
            bundle.metrics if bundle else None,
        )
        content_blocks = self._content_blocks_from_exhibit(archetype, exhibit_spec, section)
        action_title = self._fallback_action_title(archetype, title, section)
        source_refs = blueprint.source_coverage_map.get(str(index + 1), [source_label])
        chart_spec = self.exhibit_compiler.chart_spec(exhibit_spec)
        if chart_spec is None and archetype == "metric_chart" and metrics:
            chart_spec = {"type": "bar", "metrics": metrics[:5]}
        return GeneratedSlideSpec(
            slide_number=index + 1,
            slide_type=self._slide_type_for_archetype(archetype),
            action_title=action_title,
            subheading=self._subheading_for_archetype(archetype, section),
            content_blocks=content_blocks,
            chart_spec=chart_spec,
            sources=[source_label],
            speaker_notes=self._beat_message(archetype, title),
            archetype=archetype,
            narrative_role=role,
            exhibit_spec=exhibit_spec,
            diagram_spec=self._diagram_spec_for_exhibit(
                archetype,
                exhibit_spec,
                action_title,
            ),
            design_intent=self._design_intent(archetype),
            source_refs=source_refs,
        )

    def _exhibit_for_archetype(
        self,
        archetype: str,
        section: DocumentSection,
        sections: list[DocumentSection],
        metrics: list[dict[str, Any]],
        tables: list[Any] | None = None,
        source_metrics: list[DocumentMetric] | None = None,
    ) -> dict[str, Any]:
        bullets = self._section_phrases(section, 4)
        if archetype == "cover":
            return {
                "type": "cover",
                "thesis": self._phrase(section.content, "A clear operating model improves execution quality."),
                "signals": [self._clean_section_title(item.title) for item in sections[:3]],
            }
        if archetype == "executive_summary":
            return {
                "type": "executive_summary",
                "messages": [
                    {"label": "Situation", "text": bullets[0]},
                    {
                        "label": "Complication",
                        "text": bullets[1]
                        if len(bullets) > 1
                        else "The current approach exposes execution gaps.",
                    },
                    {
                        "label": "Resolution",
                        "text": bullets[2]
                        if len(bullets) > 2
                        else "Move from intent to explicit owners, evidence, and review gates.",
                    },
                ],
                "proof_points": self._executive_summary_proof_points(metrics),
            }
        if archetype == "anti_patterns":
            pattern_bullets = bullets[:3]
            while len(pattern_bullets) < 3:
                pattern_bullets.append(self._default_pattern(len(pattern_bullets)))
            return {
                "type": "anti_patterns",
                "patterns": [
                    {
                        "name": self._anti_pattern_name(pattern_bullets[idx]),
                        "symptom": pattern_bullets[idx],
                        "consequence": [
                            "Execution quality degrades as assumptions stay implicit.",
                            "Teams spend review time resolving avoidable ambiguity.",
                            "Decisions become hard to trace when conditions change.",
                        ][idx],
                        "better_behavior": [
                            "Make the operating context explicit.",
                            "Require source-backed acceptance criteria.",
                            "Record decisions and next actions in the workflow.",
                        ][idx],
                    }
                    for idx in range(3)
                ],
            }
        if archetype == "dependency_map":
            middle = [
                self._clean_section_title(item.title) or f"Context {idx + 1}"
                for idx, item in enumerate(sections[:3])
            ]
            while len(middle) < 3:
                middle.append(["Decision context", "Operating rules", "Review evidence"][len(middle)])
            return {
                "type": "dependency_map",
                "left_node": "Source evidence",
                "middle_nodes": middle[:3],
                "right_outcome": "Confident decision",
                "connector_labels": ["feeds", "constrains", "verifies"],
            }
        if archetype == "framework_cycle":
            steps = [
                self._phrase(item, "")
                for item in bullets[:5]
                if self._phrase(item, "")
            ]
            while len(steps) < 4:
                steps.append(
                    [
                        "Define the benchmark contract.",
                        "Bind tests to source evidence.",
                        "Run the harness against real workflows.",
                        "Review failures before expanding coverage.",
                    ][len(steps)]
                )
            return {
                "type": "cycle",
                "center_label": self._short_label(section.title),
                "steps": [
                    {
                        "label": self._short_label(step),
                        "description": step,
                    }
                    for step in steps[:5]
                ],
                "reset_label": "Revise the benchmark when evidence changes.",
            }
        if archetype == "comparison_table":
            if tables or source_metrics:
                compiled = self.exhibit_compiler.compile(
                    archetype,
                    "evidence",
                    section,
                    tables or [],
                    source_metrics or [],
                )
                if compiled.get("type") == "comparison_table":
                    return compiled
            return {
                "type": "comparison_table",
                "columns": ["Dimension", "Current model", "Target model"],
                "rows": [
                    {
                        "label": "Context",
                        "values": ["Fragmented inputs", "Shared source of truth"],
                        "indicator": "green",
                    },
                    {
                        "label": "Control",
                        "values": ["Implicit judgment", "Explicit operating rules"],
                        "indicator": "green",
                    },
                    {
                        "label": "Review",
                        "values": ["Late cleanup", "Built-in quality gates"],
                        "indicator": "green",
                    },
                ],
            }
        if archetype == "matrix_2x2":
            return self.exhibit_compiler.compile(
                archetype,
                "evidence",
                section,
                tables or [],
                source_metrics or [],
            )
        if archetype in {"code_panel", "reference"}:
            return self._code_panel_spec_for_section(section)
        if archetype == "checklist":
            return self.exhibit_compiler.compile(
                archetype,
                "implementation",
                section,
                tables or [],
                source_metrics or [],
            )
        if archetype == "quote_sidebar":
            return {
                "type": "quote_sidebar",
                "key_idea": "The work shifts from isolated output to managed operating discipline.",
                "supporting_points": bullets[:3],
                "quote": "Make the standard explicit before asking the team to move faster.",
            }
        if archetype == "callouts":
            spec: dict[str, Any] = {"type": "callouts", "points": bullets[:3]}
            if source_metrics:
                metric_spec = self.exhibit_compiler.compile(
                    "metric_chart",
                    "evidence",
                    section,
                    tables or [],
                    source_metrics,
                )
                metric_items = metric_spec.get("metrics", [])
                if isinstance(metric_items, list) and metric_items:
                    spec["metrics"] = metric_items[:3]
            return spec
        if archetype == "icon_rows":
            return {"type": "icon_rows", "items": bullets[:4]}
        if archetype == "two_column":
            return {
                "type": "two_column",
                "left": bullets[:2],
                "right": bullets[2:4] or bullets[:2],
                "points": bullets[:4],
            }
        if archetype == "table_reference":
            if tables:
                compiled = self.exhibit_compiler.compile(
                    archetype,
                    "reference",
                    section,
                    tables,
                    source_metrics or [],
                )
                if compiled.get("type") == "reference_table":
                    return compiled
            return self._reference_spec_for_section(section, bullets)
        if archetype == "metric_chart":
            if source_metrics:
                return self.exhibit_compiler.compile(
                    archetype,
                    "evidence",
                    section,
                    tables or [],
                    source_metrics,
                )
            return {"type": "metric_chart", "metrics": metrics[:5]}
        if archetype == "closing_recommendation":
            return {
                "type": "recommendation",
                "recommendation": self._phrase(
                    section.content,
                    "Adopt the target operating model as the default way of working.",
                ),
                "next_steps": [
                    "Pick one source-rich workflow.",
                    "Define owners, evidence, and review gates.",
                    "Use lessons from the pilot before expanding.",
                ],
                "decision_ask": "Approve a time-boxed pilot with named owners.",
            }
        return {"type": "text_exhibit", "points": bullets}

    def _code_panel_spec_for_section(self, section: DocumentSection) -> dict[str, Any]:
        section_text = f"{section.title} {section.content}".lower()
        section_title = section.title.lower()
        if any(token in section_title for token in ("update", "stale", "reset")):
            return {
                "type": "code_panel",
                "title": "memory-bank/update-protocol.md",
                "lines": [
                    "Refresh activeContext.md after changes.",
                    "Record decisions before the next session.",
                    "Sync progress.md when status changes.",
                    "Load latest memory files before restart.",
                ],
            }
        if any(token in section_text for token in ("employee", "product manager", "manager")):
            return {
                "type": "code_panel",
                "title": "agent-brief.md",
                "lines": [
                    "State the outcome before assigning work.",
                    "Describe constraints the agent must preserve.",
                    "Name review gates before implementation.",
                    "Close the loop with recorded decisions.",
                ],
            }
        if any(token in section_text for token in ("cycle", "loop", "phase", "workflow")):
            return {
                "type": "code_panel",
                "title": "agentic-cycle.md",
                "lines": [
                    "Frame the request with an explicit outcome.",
                    "Prime the agent with memory and constraints.",
                    "Generate bounded changes from the spec.",
                    "Review output before updating memory.",
                ],
            }
        if any(token in section_text for token in ("update", "stale", "reset")):
            return {
                "type": "code_panel",
                "title": "memory-bank/update-protocol.md",
                "lines": [
                    "Refresh activeContext.md after meaningful changes.",
                    "Record decisions before starting the next session.",
                    "Sync progress.md when status or risk changes.",
                    "Restart with the latest memory files loaded.",
                ],
            }
        if any(token in section_text for token in ("markdown", "specification", "rules file", "rules files")):
            return {
                "type": "code_panel",
                "title": "rules.md",
                "lines": [
                    "Write acceptance criteria before generation.",
                    "Keep constraints in markdown beside code.",
                    "Treat examples as executable review cases.",
                    "Revise rules after QA findings.",
                ],
            }
        if any(token in section_text for token in ("memory bank", "external brain", "persistent context")):
            return {
                "type": "code_panel",
                "title": "memory-bank/README.md",
                "lines": [
                    "Create core files before the first agent run.",
                    "Load projectbrief.md and activeContext.md at session start.",
                    "Persist decisions as memory updates.",
                    "Use progress.md to resume work safely.",
                ],
            }
        return {
            "type": "code_panel",
            "title": "operating-rules.md",
            "lines": [
                "Define the decision before drafting.",
                "Keep source context attached to the work.",
                "Require evidence before approval.",
                "Record accepted decisions after review.",
            ],
        }

    def _reference_spec_for_section(
        self, section: DocumentSection, bullets: list[str]
    ) -> dict[str, Any]:
        if self._is_memory_text(f"{section.title} {section.content}"):
            return self._memory_bank_reference_spec()
        reference_rows = [
            [
                "Decision owner",
                "Names who can approve the recommendation",
                "Owner or mandate changes",
            ],
            [
                "Evidence base",
                "Keeps the sources used for the slide traceable",
                "New data or source challenge",
            ],
            [
                "Operating rule",
                "Turns the recommendation into repeatable behavior",
                "Process or risk changes",
            ],
            [
                "Review gate",
                "Defines the quality check before wider rollout",
                "Pilot or launch milestone",
            ],
        ]
        if bullets:
            triggers = [
                "Evidence changes",
                "Workflow changes",
                "Review standard changes",
                "Ownership changes",
            ]
            reference_rows = [
                [
                    self._short_label(bullet),
                    self._clean_generated_visual_placeholder(bullet),
                    triggers[index % len(triggers)],
                ]
                for index, bullet in enumerate(bullets[:4])
                if self._clean_generated_visual_placeholder(bullet)
            ]
        return {
            "type": "reference_table",
            "columns": ["Artifact", "Purpose", "Update trigger"],
            "rows": reference_rows,
        }

    def _content_blocks_from_exhibit(
        self, archetype: str, exhibit_spec: dict[str, Any], section: DocumentSection
    ) -> list[ContentBlock]:
        if archetype in {"comparison_table", "table_reference"}:
            columns = exhibit_spec.get("columns", [])
            rows = exhibit_spec.get("rows", [])
            body = [columns] if isinstance(columns, list) else []
            for row in rows:
                if isinstance(row, dict):
                    body.append([row.get("label", ""), *row.get("values", [])])
                elif isinstance(row, list):
                    body.append(row)
            return [ContentBlock(type="table", body=body)]
        if archetype == "metric_chart":
            return [ContentBlock(type="chart", body=exhibit_spec.get("metrics", []))]
        if archetype == "matrix_2x2":
            return self.exhibit_compiler.content_blocks(exhibit_spec)
        if archetype == "executive_summary":
            messages = exhibit_spec.get("messages", [])
            return [
                ContentBlock(
                    type="bullets",
                    body=[
                        item.get("text", "")
                        for item in messages
                        if isinstance(item, dict) and item.get("text")
                    ],
                )
            ]
        if archetype == "checklist":
            return [
                ContentBlock(
                    type="table",
                    body=[
                        ["Action", "Owner", "Timing"],
                        *[
                            [item.get("action", ""), item.get("owner", ""), item.get("timing", "")]
                            for item in exhibit_spec.get("items", [])
                            if isinstance(item, dict)
                        ],
                    ],
                )
            ]
        if archetype == "anti_patterns":
            return [
                ContentBlock(
                    type="bullets",
                    body=[
                        f"{item.get('name')}: {item.get('better_behavior')}"
                        for item in exhibit_spec.get("patterns", [])
                        if isinstance(item, dict)
                    ],
                )
            ]
        if archetype in {"code_panel", "reference"}:
            return [ContentBlock(type="bullets", body=exhibit_spec.get("lines", []))]
        if archetype == "quote_sidebar":
            return [ContentBlock(type="bullets", body=exhibit_spec.get("supporting_points", []))]
        if archetype == "callouts":
            points = exhibit_spec.get("points", [])
            if isinstance(points, list) and any(str(point).strip() for point in points):
                return [ContentBlock(type="callout", body=points)]
            metrics = exhibit_spec.get("metrics", [])
            if isinstance(metrics, list) and len(metrics) >= 2:
                return [
                    ContentBlock(
                        type="callout",
                        body=[
                            self._metric_display_text(item)
                            for item in metrics
                            if isinstance(item, dict)
                        ],
                    )
                ]
            return [ContentBlock(type="callout", body=points if isinstance(points, list) else [])]
        if archetype == "icon_rows":
            items = exhibit_spec.get("items", [])
            return [ContentBlock(type="bullets", body=items if isinstance(items, list) else [])]
        if archetype == "two_column":
            points = exhibit_spec.get("points", [])
            if not isinstance(points, list):
                left = exhibit_spec.get("left", [])
                right = exhibit_spec.get("right", [])
                points = [
                    *(left if isinstance(left, list) else []),
                    *(right if isinstance(right, list) else []),
                ]
            return [ContentBlock(type="bullets", body=points)]
        return [ContentBlock(type="bullets", body=self._section_phrases(section, 4))]

    def _fallback_action_title(
        self, archetype: str, title: str, section: DocumentSection
    ) -> str:
        title_phrase = title.lower()
        section_text = f"{section.title} {section.content}".lower()
        keyword_title = self._keyword_action_title(section.title, section.content)
        if keyword_title and archetype not in {"cover", "section_divider"}:
            return self._truncate_title(keyword_title)
        if archetype == "dependency_map":
            if any(token in section_text for token in ("update", "stale", "protocol")):
                return "Map context updates to preserve workflow reliability"
            if self._is_memory_text(section_text):
                return "Use memory systems to make AI work reproducible"
        if archetype == "comparison_table":
            if any(token in section_text for token in ("cycle", "loop", "phase")):
                return "Contrast the operating loop with ad hoc execution"
            if any(token in section_text for token in ("chatbot", "employee", "manager")):
                return "Contrast chatbot prompting with managed AI teammates"
        if archetype in {"code_panel", "reference"}:
            section_title = section.title.lower()
            if any(token in section_title for token in ("update", "stale", "reset")):
                return "Codify memory updates before context goes stale"
            if any(token in section_text for token in ("agent", "ai", "chatbot")) and any(
                token in section_text for token in ("employee", "product manager", "manager")
            ):
                return "Define agent briefs before assigning AI work"
            if any(token in section_text for token in ("cycle", "loop", "phase", "workflow")):
                return "Codify the operating cycle as reusable rules"
            if any(token in section_text for token in ("markdown", "specification", "rules file")):
                return "Codify markdown rules where teams already work"
            if self._is_memory_text(section_text):
                return "Codify memory-bank rules where teams already work"
        titles = {
            "cover": f"Translate {title_phrase} into an executive decision",
            "executive_summary": "Focus the story on decision, risk, and recommended action",
            "anti_patterns": "Stop three failure modes before execution scales",
            "dependency_map": "Map the dependencies that determine the outcome",
            "framework_cycle": "Run the work through a reviewable operating cycle",
            "section_divider": "Shift from diagnosis to execution",
            "comparison_table": "Compare the current model with the target operating model",
            "code_panel": "Codify operating rules where teams already work",
            "checklist": "Adopt the transition through a short operating checklist",
            "quote_sidebar": "Reframe the mindset shift behind the recommendation",
            "table_reference": "Standardize responsibilities across the operating workflow",
            "metric_chart": "Quantify the signal before making the decision",
            "matrix_2x2": "Prioritize the moves by impact and readiness",
            "callouts": "Surface the highest-signal proof points for the decision",
            "icon_rows": "Sequence the operating moves into scannable actions",
            "two_column": "Separate the implication from the evidence",
            "closing_recommendation": "Commit to the next operating decision",
        }
        if archetype in titles:
            return self._truncate_title(titles[archetype])
        return self._action_title(section.title, section.content)

    def _slide_type_for_archetype(self, archetype: str) -> str:
        mapping = {
            "cover": "cover",
            "executive_summary": "executive_summary",
            "anti_patterns": "anti_pattern",
            "dependency_map": "framework",
            "framework_cycle": "framework",
            "section_divider": "section",
            "comparison_table": "comparison",
            "code_panel": "reference",
            "reference": "reference",
            "checklist": "checklist",
            "quote_sidebar": "quote",
            "table_reference": "reference",
            "metric_chart": "chart",
            "matrix_2x2": "matrix",
            "callouts": "callouts",
            "icon_rows": "content",
            "two_column": "content",
            "closing_recommendation": "closing",
        }
        return mapping.get(archetype, "content")

    def _subheading_for_archetype(self, archetype: str, section: DocumentSection) -> str:
        if archetype == "cover":
            return "A practical operating model for a source-backed executive decision"
        if archetype == "section_divider":
            return "The second half of the story turns diagnosis into repeatable execution."
        return f"Evidence from {section.title}"

    def _design_intent(self, archetype: str) -> str:
        intents = {
            "cover": "dark editorial cover with a clear thesis",
            "executive_summary": "three-part situation-complication-resolution summary",
            "anti_patterns": "named failure-mode cards with concise consequences",
            "dependency_map": "left-to-right dependency flow with thick connectors",
            "framework_cycle": "directional cycle around a center operating model",
            "section_divider": "dark editorial divider",
            "comparison_table": "compact comparison table with clear axes",
            "code_panel": "compact reference block with slide-specific rules",
            "reference": "compact reference block with slide-specific rules",
            "checklist": "quick-start reference checklist",
            "quote_sidebar": "quote sidebar visually tied to supporting points",
            "table_reference": "compact reference table",
            "metric_chart": "simple metric chart using sourced values",
            "matrix_2x2": "2x2 prioritization matrix with concise quadrant labels",
            "callouts": "three source-derived proof-point cards",
            "icon_rows": "four scannable action rows with icons",
            "two_column": "balanced implication and evidence columns",
            "closing_recommendation": "closing recommendation with decision ask",
        }
        return intents.get(archetype, "structured exhibit with concise body text")

    def _section_phrases(self, section: DocumentSection, count: int) -> list[str]:
        raw_phrases = []
        for line in self._to_bullets(section.content):
            raw_phrases.extend(
                item.strip()
                for item in re.split(r"(?<=[.!?])\s+", line)
                if item.strip()
            )
        phrases = [
            self._phrase(line, "")
            for line in raw_phrases
            if self._phrase(line, "")
        ]
        if not phrases:
            phrases = [self._phrase(section.content or section.title, section.title)]
        if len(phrases) < count:
            for filler in self._filler_phrases(section, count - len(phrases)):
                if filler not in phrases:
                    phrases.append(filler)
                if len(phrases) >= count:
                    break
        return phrases[:count]

    def _filler_phrases(self, section: DocumentSection, needed: int) -> list[str]:
        subject = self._clean_section_title(section.title) or "the source evidence"
        subject = self._truncate_at_word(subject.lower(), 44).removesuffix("...")
        subject_title = subject[:1].upper() + subject[1:]
        pool = (
            f"{subject_title} defines the evidence to inspect.",
            f"{subject_title} sets the benchmark condition to validate.",
            f"{subject_title} names the workflow signal to preserve.",
            f"{subject_title} clarifies what must change before scaling.",
            f"{subject_title} gives the slide its operating context.",
            f"{subject_title} explains why the decision needs source grounding.",
        )
        seed = sum(ord(char) for char in (section.title or "section")) % len(pool)
        return [pool[(seed + index) % len(pool)] for index in range(needed)]

    def _phrase(self, text: str, fallback: str, limit: int = 105) -> str:
        cleaned = self._clean_generated_visual_placeholder(text or fallback)
        cleaned = re.split(r"[.!?]\s+", cleaned)[0] if cleaned else fallback
        cleaned = " ".join(cleaned.split())
        cleaned = self._repair_dangling_fragment(cleaned)
        if cleaned.count('"') % 2 == 1:
            return ""
        if len(cleaned) <= limit:
            return cleaned
        return ""

    def _derive_exhibit_spec(self, slide: GeneratedSlideSpec) -> dict[str, Any]:
        bullets = self._body_to_bullets(slide)
        archetype = self._normalize_archetype(slide.archetype or "")
        if archetype == "comparison_table":
            table_rows = self._first_table_block(slide)
            if table_rows:
                columns = [str(cell) for cell in table_rows[0]]
                rows = [
                    {"label": str(row[0]), "values": [str(cell) for cell in row[1:]]}
                    for row in table_rows[1:5]
                    if row
                ]
                return {"type": "comparison_table", "columns": columns, "rows": rows}
            return {
                "type": "comparison_table",
                "columns": ["Dimension", "Current state", "Target state"],
                "rows": self._fallback_comparison_rows(slide, bullets),
            }
        if archetype == "dependency_map":
            middle = bullets[:3]
            return {
                "type": "dependency_map",
                "left_node": self._short_label(slide.subheading or slide.action_title),
                "middle_nodes": middle[:3],
                "right_outcome": slide.action_title,
                "connector_labels": ["feeds", "guides", "validates"],
            }
        if archetype == "framework_cycle":
            steps = bullets[:5]
            return {
                "type": "cycle",
                "center_label": "Operating loop",
                "steps": [{"label": self._short_label(step), "description": step} for step in steps],
            }
        if archetype == "checklist":
            checklist_items = bullets[:5]
            defaults = [
                "Name the decision and success criteria",
                "Define acceptance criteria",
                "Assign evidence and review owners",
                "Codify lessons after review",
            ]
            while len(checklist_items) < 3:
                checklist_items.append(defaults[len(checklist_items)])
            return {
                "type": "checklist",
                "items": [
                    {
                        "action": self._repair_dangling_fragment(bullet),
                        "owner": self.exhibit_compiler._owner_for_action(bullet, index),
                        "timing": self.exhibit_compiler._timing_for_action(bullet, index),
                    }
                    for index, bullet in enumerate(checklist_items)
                ],
            }
        if archetype == "code_panel":
            return {"type": "code_panel", "title": "rules.md", "lines": bullets[:5]}
        if archetype == "anti_patterns":
            pattern_bullets = bullets[:4]
            while len(pattern_bullets) < 3:
                pattern_bullets.append(self._default_pattern(len(pattern_bullets)))
            better_behaviors = [
                "Persist context in a shared record.",
                "Verify claims against the source.",
                "Record decisions beside the workflow.",
                "Refresh the record after material changes.",
            ]
            return {
                "type": "anti_patterns",
                "patterns": [
                    {
                        "name": self._anti_pattern_name(bullet),
                        "symptom": bullet,
                        "consequence": "The team loses reliability.",
                        "better_behavior": better_behaviors[idx % len(better_behaviors)],
                    }
                    for idx, bullet in enumerate(pattern_bullets[:4])
                ],
            }
        if archetype == "quote_sidebar":
            return {
                "type": "quote_sidebar",
                "key_idea": slide.subheading or slide.action_title,
                "supporting_points": bullets[:4],
            }
        if archetype == "table_reference":
            if self._is_memory_reference_intent(slide):
                return self._memory_bank_reference_spec()
            return {
                "type": "reference_table",
                "columns": ["Artifact", "Purpose"],
                "rows": [[self._short_label(bullet), bullet] for bullet in bullets[:5]],
            }
        if archetype == "metric_chart":
            return {"type": "metric_chart", "metrics": self._metrics_from_slide(slide)}
        if archetype == "matrix_2x2":
            items = bullets[:4]
            while len(items) < 4:
                items.append(
                    [
                        "Name the decision owner.",
                        "Confirm the evidence standard.",
                        "Set the review cadence.",
                        "Track changes as conditions shift.",
                    ][len(items)]
                )
            labels = [self._short_label(item) for item in items[:4]]
            return {
                "type": "matrix_2x2",
                "x_axis": "Operational clarity",
                "y_axis": "Evidence strength",
                "quadrants": [
                    {"label": labels[index], "description": self._truncate_at_word(item, 78)}
                    for index, item in enumerate(items[:4])
                ],
            }
        if archetype == "callouts":
            return {"type": "callouts", "points": bullets[:3]}
        if archetype == "icon_rows":
            return {"type": "icon_rows", "items": bullets[:4]}
        if archetype == "two_column":
            return {
                "type": "two_column",
                "left": bullets[:2],
                "right": bullets[2:4] or bullets[:2],
                "points": bullets[:4],
            }
        if archetype == "closing_recommendation":
            return {
                "type": "recommendation",
                "recommendation": slide.action_title,
                "next_steps": bullets[:3],
                "decision_ask": "Approve the recommended pilot with named owners and a review date.",
            }
        return {"type": archetype or "text_exhibit", "points": bullets}

    def _sync_diagram_spec(self, slide: GeneratedSlideSpec) -> None:
        archetype = self._normalize_archetype(slide.archetype or "")
        if isinstance(slide.diagram_spec, dict):
            slide.diagram_spec = self._clean_placeholders_in_value(slide.diagram_spec)
        if archetype not in {"dependency_map", "framework_cycle"}:
            return
        if not isinstance(slide.exhibit_spec, dict):
            return
        if self._diagram_spec_is_usable(archetype, slide.diagram_spec):
            return
        slide.diagram_spec = self._diagram_spec_for_exhibit(
            archetype,
            slide.exhibit_spec,
            slide.action_title,
        )

    def _diagram_spec_is_usable(self, archetype: str, diagram_spec) -> bool:
        if not isinstance(diagram_spec, dict):
            return False
        kind = str(diagram_spec.get("kind") or "").lower()
        if archetype == "dependency_map":
            nodes = diagram_spec.get("middle_nodes") or diagram_spec.get("nodes")
            return kind == "dependency_flow" and isinstance(nodes, list) and len(nodes) >= 2
        if archetype == "framework_cycle":
            steps = diagram_spec.get("steps")
            return kind == "cycle" and isinstance(steps, list) and len(steps) >= 4
        return False

    def _diagram_spec_for_exhibit(
        self,
        archetype: str,
        exhibit_spec: dict[str, Any],
        fallback_title: str,
    ) -> dict[str, Any] | None:
        normalized = self._normalize_archetype(archetype)
        if normalized == "dependency_map":
            middle_nodes = [
                self._clean_generated_visual_placeholder(str(item))
                for item in exhibit_spec.get("middle_nodes", [])
                if self._clean_generated_visual_placeholder(str(item))
            ][:4]
            if len(middle_nodes) < 2:
                return None
            return {
                "kind": "dependency_flow",
                "title": fallback_title,
                "left_node": self._clean_generated_visual_placeholder(
                    str(exhibit_spec.get("left_node") or "Source context")
                ),
                "middle_nodes": middle_nodes,
                "right_outcome": self._clean_generated_visual_placeholder(
                    str(exhibit_spec.get("right_outcome") or fallback_title)
                ),
                "connector_labels": [
                    self._clean_generated_visual_placeholder(str(item))
                    for item in exhibit_spec.get("connector_labels", [])
                    if self._clean_generated_visual_placeholder(str(item))
                ][:4],
            }
        if normalized == "framework_cycle":
            raw_steps = exhibit_spec.get("steps")
            steps = raw_steps if isinstance(raw_steps, list) else []
            labels = [
                self._clean_generated_visual_placeholder(
                    str(step.get("label") or step.get("description") or "")
                )
                for step in steps
                if isinstance(step, dict)
                and self._clean_generated_visual_placeholder(
                    str(step.get("label") or step.get("description") or "")
                )
            ][:6]
            if len(labels) < 4:
                return None
            return {
                "kind": "cycle",
                "title": fallback_title,
                "center_label": self._clean_generated_visual_placeholder(
                    str(exhibit_spec.get("center_label") or "Operating loop")
                ),
                "steps": [{"label": label} for label in labels[:6]],
            }
        return None

    def _fallback_comparison_rows(
        self, slide: GeneratedSlideSpec, bullets: list[str]
    ) -> list[dict[str, Any]]:
        intent = self._slide_intent_text(slide)
        if "chatbot" in intent or "employee" in intent or "ai teammate" in intent:
            return [
                {
                    "label": "Context",
                    "values": ["Conversation history", "Persistent external memory"],
                },
                {
                    "label": "Specification",
                    "values": ["Implicit prompt intent", "Explicit acceptance criteria"],
                },
                {
                    "label": "Review",
                    "values": ["Manual cleanup", "Evidence-backed QA gates"],
                },
            ]
        labels = ["Context", "Control", "Review"]
        defaults = [
            ["Fragmented inputs", "Shared source of truth"],
            ["Implicit judgment", "Explicit operating rules"],
            ["Late cleanup", "Built-in quality gates"],
        ]
        rows: list[dict[str, Any]] = []
        for idx, label in enumerate(labels):
            target = bullets[idx] if idx < len(bullets) else defaults[idx][1]
            rows.append({"label": label, "values": [defaults[idx][0], target]})
        return rows

    def _memory_bank_reference_spec(self) -> dict[str, Any]:
        return {
            "type": "reference_table",
            "columns": ["File", "Role", "Update trigger"],
            "rows": [
                [
                    "projectbrief.md",
                    "Defines purpose, scope, and success criteria",
                    "Scope or objective changes",
                ],
                [
                    "productContext.md",
                    "Captures user problem, experience goals, and value",
                    "User or market insight changes",
                ],
                [
                    "systemPatterns.md",
                    "Records architecture, patterns, and constraints",
                    "Design or integration changes",
                ],
                [
                    "activeContext.md",
                    "Tracks current focus, decisions, and next actions",
                    "Each meaningful work session",
                ],
                [
                    "progress.md",
                    "Shows what is done, open, and at risk",
                    "Milestone or status change",
                ],
            ],
        }

    def _is_memory_reference_intent(self, slide: GeneratedSlideSpec) -> bool:
        intent = self._slide_intent_text(slide)
        return self._is_memory_text(intent)

    def _is_memory_text(self, text: str) -> bool:
        intent = text.lower()
        return any(
            token in intent
            for token in (
                "memory bank",
                "core file",
                "persistent context",
                "external brain",
                "hierarchical context",
                "root-level",
            )
        )

    def _is_generic_reference_table(self, exhibit: dict[str, Any]) -> bool:
        columns = [str(column).strip().lower() for column in exhibit.get("columns", [])]
        row_text = " ".join(
            " ".join(str(value).lower() for value in row)
            for row in exhibit.get("rows", [])
            if isinstance(row, list)
        )
        if len(columns) <= 2:
            return True
        if columns[:2] in (["item", "implication"], ["artifact", "purpose"]):
            return True
        return "projectbrief.md" not in row_text and "activecontext.md" not in row_text

    def _exhibit_is_incomplete(self, slide: GeneratedSlideSpec) -> bool:
        exhibit = slide.exhibit_spec
        if not isinstance(exhibit, dict):
            return True
        exhibit_type = str(exhibit.get("type") or "").lower().replace("-", "_")
        checks = {
            "comparison_table": lambda item: not self._comparison_exhibit_is_sparse(item),
            "dependency_map": lambda item: len(item.get("middle_nodes", [])) >= 2,
            "cycle": lambda item: len(item.get("steps", [])) >= 3,
            "checklist": lambda item: len(item.get("items", [])) >= 3,
            "code_panel": lambda item: bool(item.get("lines")),
            "anti_patterns": lambda item: not self._anti_patterns_exhibit_is_sparse(item),
            "quote_sidebar": lambda item: bool(item.get("supporting_points") or item.get("key_idea")),
            "reference_table": lambda item: bool(item.get("columns") and item.get("rows")),
            "recommendation": lambda item: bool(item.get("next_steps") or item.get("recommendation")),
            "metric_chart": lambda item: bool(item.get("metrics")),
            "matrix_2x2": lambda item: len(item.get("quadrants", [])) >= 4,
            "callouts": lambda item: bool(item.get("points") or item.get("metrics")),
            "icon_rows": lambda item: len(item.get("items", [])) >= 3,
            "two_column": lambda item: bool(item.get("points") or item.get("left") or item.get("right")),
        }
        checker = checks.get(exhibit_type)
        if checker and not checker(exhibit):
            return True
        if exhibit_type == "reference_table" and self._is_memory_reference_intent(slide):
            return self._is_generic_reference_table(exhibit)
        return False

    def _repair_underfilled_exhibit(
        self, slide: GeneratedSlideSpec, source_metrics: list[dict[str, Any]]
    ) -> None:
        if not isinstance(slide.exhibit_spec, dict):
            return
        archetype = self._normalize_archetype(slide.archetype or "")
        if archetype == "comparison_table" and self._comparison_exhibit_is_sparse(
            slide.exhibit_spec
        ):
            slide.exhibit_spec = {
                "type": "comparison_table",
                "columns": ["Dimension", "Current state", "Target state"],
                "rows": self._fallback_comparison_rows(slide, self._body_to_bullets(slide)),
            }
        if archetype == "metric_chart":
            existing_metrics = self._normalized_metric_dicts(
                slide.exhibit_spec.get("metrics", [])
            )
            enriched_metrics = self._merge_metric_dicts(existing_metrics, source_metrics)
            if source_metrics and len(enriched_metrics) < min(3, len(source_metrics)):
                enriched_metrics = source_metrics
            if enriched_metrics:
                slide.exhibit_spec = {
                    **slide.exhibit_spec,
                    "type": "metric_chart",
                    "metrics": enriched_metrics[:4],
                }
        if archetype == "anti_patterns" and self._anti_patterns_exhibit_is_sparse(
            slide.exhibit_spec
        ):
            slide.exhibit_spec = self._derive_exhibit_spec(slide)
        if archetype == "executive_summary":
            proof_points = slide.exhibit_spec.get("proof_points", [])
            if source_metrics and (
                not isinstance(proof_points, list) or len(proof_points) < 2
            ):
                slide.exhibit_spec = {
                    **slide.exhibit_spec,
                    "type": "executive_summary",
                    "proof_points": self._executive_summary_proof_points(source_metrics),
                }

    def _sync_content_blocks_from_exhibit(self, slide: GeneratedSlideSpec) -> None:
        if not isinstance(slide.exhibit_spec, dict):
            return
        archetype = self._normalize_archetype(slide.archetype or "")
        if archetype == "comparison_table":
            columns = slide.exhibit_spec.get("columns", [])
            rows = slide.exhibit_spec.get("rows", [])
            body = [columns] if isinstance(columns, list) else []
            for row in rows if isinstance(rows, list) else []:
                if isinstance(row, dict):
                    body.append([row.get("label", ""), *row.get("values", [])])
                elif isinstance(row, list):
                    body.append(row)
            if len(body) >= 2:
                slide.content_blocks = [ContentBlock(type="table", body=body)]
        if archetype == "metric_chart":
            metrics = slide.exhibit_spec.get("metrics", [])
            if isinstance(metrics, list) and metrics:
                slide.content_blocks = [ContentBlock(type="chart", body=metrics)]
        if archetype == "matrix_2x2":
            slide.content_blocks = self.exhibit_compiler.content_blocks(slide.exhibit_spec)
        if archetype == "callouts":
            slide.content_blocks = self._content_blocks_from_exhibit(
                archetype,
                slide.exhibit_spec,
                DocumentSection(
                    title=slide.action_title,
                    level=1,
                    content=slide.subheading,
                    source_doc_id="generated",
                ),
            )
        if archetype in {"icon_rows", "two_column"}:
            slide.content_blocks = self._content_blocks_from_exhibit(
                archetype,
                slide.exhibit_spec,
                DocumentSection(
                    title=slide.action_title,
                    level=1,
                    content=slide.subheading,
                    source_doc_id="generated",
                ),
            )

    def _comparison_exhibit_is_sparse(self, exhibit: dict[str, Any]) -> bool:
        columns = exhibit.get("columns", [])
        rows = exhibit.get("rows", [])
        if not isinstance(columns, list) or len(columns) < 3:
            return True
        normalized_columns = [self._display_cell_text(column) for column in columns[:3]]
        if any(not self._has_meaningful_cell_text(column) for column in normalized_columns):
            return True
        if not isinstance(rows, list):
            return True
        usable_rows = 0
        for row in rows:
            cells = self._comparison_row_cells(row)
            if len(cells) < 3:
                continue
            if all(self._has_meaningful_cell_text(cell) for cell in cells[:3]):
                usable_rows += 1
        return usable_rows < 3

    def _anti_patterns_exhibit_is_sparse(self, exhibit: dict[str, Any]) -> bool:
        patterns = exhibit.get("patterns", [])
        if not isinstance(patterns, list):
            return True
        usable = 0
        for pattern in patterns:
            if not isinstance(pattern, dict):
                continue
            if (
                self._has_meaningful_cell_text(pattern.get("name", ""))
                and self._has_meaningful_cell_text(pattern.get("symptom", ""))
                and self._has_meaningful_cell_text(pattern.get("better_behavior", ""))
            ):
                usable += 1
        return usable < 3

    def _comparison_row_cells(self, row: Any) -> list[str]:
        if isinstance(row, dict):
            values = row.get("values", [])
            if not isinstance(values, list):
                values = [values]
            return [self._display_cell_text(row.get("label", ""))] + [
                self._display_cell_text(value) for value in values
            ]
        if isinstance(row, list):
            return [self._display_cell_text(value) for value in row]
        return []

    def _display_cell_text(self, value: Any) -> str:
        if isinstance(value, dict):
            for key in ("text", "label", "name", "value", "title"):
                text = str(value.get(key) or "").strip()
                if text:
                    return text
            return ""
        return str(value or "").strip()

    def _has_meaningful_cell_text(self, value: Any) -> bool:
        text = self._clean_generated_visual_placeholder(self._display_cell_text(value))
        text = re.sub(r"\[source needed\]", "", text, flags=re.IGNORECASE).strip()
        if not text:
            return False
        if text.lower() in {"n/a", "na", "none", "tbd", "todo", "placeholder"}:
            return False
        return bool(re.search(r"[A-Za-z0-9]", text))

    def _normalized_metric_dicts(self, metrics: Any) -> list[dict[str, Any]]:
        if not isinstance(metrics, list):
            return []
        normalized: list[dict[str, Any]] = []
        for metric in metrics:
            if not isinstance(metric, dict) or not self._is_chartable_metric_dict(metric):
                continue
            value = metric.get("value")
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                continue
            normalized.append(
                {
                    "label": self._truncate_at_word(str(metric.get("label") or "Metric"), 42)
                    .removesuffix("..."),
                    "value": int(numeric_value)
                    if numeric_value.is_integer()
                    else numeric_value,
                    "unit": self._normalize_metric_unit(str(metric.get("unit") or "")),
                }
            )
        normalized.sort(key=self._metric_dict_priority)
        return normalized

    def _merge_metric_dicts(
        self, primary: list[dict[str, Any]], secondary: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[tuple[str, float, str]] = set()
        for metric in [*primary, *secondary]:
            value = metric.get("value")
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                continue
            unit = self._normalize_metric_unit(str(metric.get("unit") or "")) or ""
            key = (round(numeric_value, 4), unit)
            if key in seen:
                continue
            seen.add(key)
            merged.append(
                {
                    "label": self._truncate_at_word(str(metric.get("label") or "Metric"), 42)
                    .removesuffix("..."),
                    "value": int(numeric_value)
                    if numeric_value.is_integer()
                    else numeric_value,
                    "unit": unit or None,
                }
            )
        merged.sort(key=self._metric_dict_priority)
        return merged

    def _executive_summary_proof_points(
        self, metrics: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        normalized = self._normalized_metric_dicts(metrics)[:3]
        if normalized:
            return [
                {
                    "label": metric["label"],
                    "value": metric["value"],
                    "unit": metric.get("unit"),
                    "detail": self._metric_detail(metric),
                }
                for metric in normalized
            ]
        return [
            {
                "label": "Context",
                "value": "1",
                "unit": None,
                "detail": "Persistent memory makes AI work reproducible.",
            },
            {
                "label": "Rules",
                "value": "2",
                "unit": None,
                "detail": "Acceptance criteria constrain generation.",
            },
            {
                "label": "Review",
                "value": "3",
                "unit": None,
                "detail": "Evidence gates protect delivery quality.",
            },
        ]

    def _metric_detail(self, metric: dict[str, Any]) -> str:
        label = str(metric.get("label") or "Sourced signal")
        unit = self._normalize_metric_unit(str(metric.get("unit") or ""))
        if unit == "%":
            return f"{label} is cited as a sourced percentage."
        if unit == "tokens":
            return f"{label} signals context capacity pressure."
        return f"{label} is a sourced signal."

    def _metric_display_text(self, metric: dict[str, Any]) -> str:
        label = str(metric.get("label") or "Sourced metric").strip()
        value = metric.get("value", "")
        unit = self._normalize_metric_unit(str(metric.get("unit") or "")) or ""
        value_text = f"{value:g}" if isinstance(value, float) else str(value)
        return f"{label}: {value_text}{unit}" if value_text else label

    def _first_table_block(self, slide: GeneratedSlideSpec) -> list[list[Any]]:
        for block in slide.content_blocks:
            if block.type != "table":
                continue
            rows = [item for item in block.body if isinstance(item, list)]
            if rows:
                return rows
        return []

    def _remove_placeholder_text(self, slide: GeneratedSlideSpec) -> None:
        for block in slide.content_blocks:
            block.body = [
                self._clean_generated_visual_placeholder(str(item))
                if isinstance(item, str)
                else item
                for item in block.body
            ]
        if isinstance(slide.exhibit_spec, dict):
            slide.exhibit_spec = self._clean_placeholders_in_value(slide.exhibit_spec)

    def _clean_placeholders_in_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._clean_generated_visual_placeholder(value)
        if isinstance(value, list):
            return [self._clean_placeholders_in_value(item) for item in value]
        if isinstance(value, dict):
            return {
                key: self._clean_placeholders_in_value(item)
                for key, item in value.items()
            }
        return value

    def _short_label(self, text: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9\s-]", "", str(text)).strip()
        words = cleaned.split()
        return " ".join(words[:3]) or "Item"

    def _anti_pattern_name(self, text: str) -> str:
        before_colon = str(text).split(":", 1)[0]
        cleaned = re.sub(r"[^A-Za-z0-9\s-]", "", before_colon).strip()
        words = cleaned.split()
        if len(words) >= 2:
            return " ".join(words[:3])
        return self._short_label(text)
