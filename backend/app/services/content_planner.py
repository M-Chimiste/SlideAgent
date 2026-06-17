import re
import uuid
from datetime import UTC, datetime
from typing import Any, Optional

from app.clients.openai_compatible_client import OpenAICompatibleClient
from app.models.document import DocumentBundle, DocumentMetric, DocumentSection
from app.models.generation import (
    ContentBlock,
    DeckSpec,
    GeneratedSlideSpec,
    GenerationMode,
)
from app.models.outline import SlideOutline
from app.models.template import SlideSpec, TemplateProfile
from app.services.consulting_qa import ConsultingQA


PLANNER_SYSTEM_PROMPT = """You are a senior engagement manager creating consulting-quality decks.
Follow the style guide rules: SCR/Pyramid structure, action titles, one message per slide,
MECE grouping, source discipline, and concise evidence. Return strict JSON only."""

UPLOADED_SOURCE_LABEL = "Uploaded source"
SOURCE_NEEDED_LABEL = "[source needed]"


class ContentPlanner:
    def __init__(self, llm_client: Optional[OpenAICompatibleClient] = None) -> None:
        self.llm_client = llm_client
        self.qa = ConsultingQA()
        self.layouts = [
            "executive_summary",
            "section_divider",
            "icon_rows",
            "two_column",
            "callouts",
            "chart",
            "icon_grid",
            "process",
            "quote_sidebar",
            "framework_cycle",
            "dependency_map",
            "checklist",
            "code_panel",
            "anti_patterns",
        ]

    def plan(
        self,
        template: TemplateProfile,
        bundle: DocumentBundle,
        instructions: str = "",
        generation_mode: str | None = None,
    ) -> tuple[list[SlideOutline], list[dict[str, Any]]]:
        mode = generation_mode or template.type
        if mode in {GenerationMode.freeform.value, GenerationMode.brand.value}:
            deck, warnings = self._plan_generated_deck(template, bundle, instructions, mode)
            return self._deck_to_outlines(deck, bundle.job_id, mode), warnings

        warnings: list[dict[str, Any]] = []
        outlines: list[SlideOutline] = []
        last_layout: str | None = None
        for slide_spec in template.slides:
            if slide_spec.mode == "strict":
                outline, slide_warnings = self._outline_for_strict_slide(
                    template, bundle, slide_spec
                )
                outlines.append(outline)
                warnings.extend(slide_warnings)
            else:
                layout = self._next_layout(last_layout)
                last_layout = layout
                outline = self._outline_for_flexible_slide(
                    template, bundle, slide_spec, layout
                )
                outlines.append(outline)
        return outlines, warnings

    def _plan_generated_deck(
        self,
        template: TemplateProfile,
        bundle: DocumentBundle,
        instructions: str,
        mode: str,
    ) -> tuple[DeckSpec, list[dict[str, Any]]]:
        warnings: list[dict[str, Any]] = []
        deck = self._plan_with_llm(bundle, instructions, mode)
        if deck is None:
            if self.llm_client is not None:
                warnings.append(
                    {
                        "slide_index": None,
                        "field": "llm_planning",
                        "message": "LLM planning was unavailable or malformed; used deterministic fallback.",
                    }
                )
            deck = self._fallback_deck(bundle, instructions, mode)
        warnings.extend(self._normalize_source_labels(deck, bundle))
        warnings.extend(self._ground_numeric_claims(deck, bundle))
        deck, qa_warnings = self.qa.inspect(deck)
        warnings.extend(qa_warnings)
        return deck, warnings

    def _plan_with_llm(
        self, bundle: DocumentBundle, instructions: str, mode: str
    ) -> DeckSpec | None:
        if self.llm_client is None:
            return None
        sections = [
            {"title": section.title, "content": section.content[:1200]}
            for section in bundle.sections[:10]
        ]
        metrics = [
            {"label": metric.label, "value": metric.value, "unit": metric.unit}
            for metric in bundle.metrics[:8]
        ]
        allowed_numbers = sorted(self._supported_numeric_tokens(bundle))[:50]
        user_prompt = (
            "Create a 7-10 slide consulting deck plan as strict JSON when the source depth supports it. "
            "Use distinct slide archetypes across the deck: executive summary, failure modes or anti-patterns, "
            "framework/cycle, memory or dependency diagram, rules/reference, checklist, chart, or comparison. "
            "Avoid repeating the same slide type on adjacent slides. "
            "Use exactly this shape: "
            "{\"deck_title\":\"string\",\"audience\":\"string\",\"goal\":\"string\","
            "\"narrative_arc\":\"Situation -> Complication -> Resolution\","
            "\"slides\":[{\"slide_number\":1,\"slide_type\":\"executive_summary|content|chart|comparison|process|framework|reference|checklist|anti_pattern|quote\","
            "\"action_title\":\"complete sentence with a verb, 15 words or fewer\","
            "\"subheading\":\"evidence context\","
            "\"content_blocks\":[{\"type\":\"bullets|chart|table|callout|text\","
            "\"body\":[\"short evidence point\"],\"annotations\":[],\"callouts\":[]}],"
            "\"chart_spec\":null,\"sources\":[\"Uploaded source\"],"
            "\"speaker_notes\":\"short presenter note\",\"qa\":{\"consulting_status\":\"pending\","
            "\"visual_status\":\"pending\",\"issues\":[]}}]}. "
            "Action titles must avoid the word 'and'; split the idea instead. "
            "Only use numeric claims that appear in the allowed numeric tokens. "
            "If an unsupported numeric claim is necessary, write [source needed] beside it. "
            "Sources may only be Uploaded source or [source needed]. "
            "Do not invent document names, reports, URLs, people, companies, or dates as sources. "
            "Do not include markdown, comments, reasoning, or text outside the JSON. "
            f"Generation mode: {mode}. Instructions: {instructions or 'No extra instructions.'}\n"
            f"Allowed numeric tokens: {allowed_numbers or ['none']}\n"
            f"Sections: {sections}\nMetrics: {metrics}"
        )
        try:
            payload = self.llm_client.complete_json(
                system_prompt=PLANNER_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_tokens=4096,
                temperature=0.2,
            )
        except Exception:
            return None
        if payload is None:
            return None
        try:
            deck = DeckSpec.model_validate(payload)
            self._repair_model_titles(deck)
            return deck
        except Exception:
            return None

    def _fallback_deck(
        self, bundle: DocumentBundle, instructions: str, mode: str
    ) -> DeckSpec:
        title = bundle.metadata.title or self._title_from_instructions(instructions)
        source_label = UPLOADED_SOURCE_LABEL if bundle.sections else SOURCE_NEEDED_LABEL
        sections = self._pick_sections(bundle.sections)
        if not sections:
            sections = self._sections_from_instructions(instructions)
        metrics = self._pick_metrics(bundle.metrics, count=3)
        slides: list[GeneratedSlideSpec] = [
            GeneratedSlideSpec(
                slide_number=1,
                slide_type="executive_summary",
                action_title=f"{title} requires focused action to improve outcomes",
                subheading="Situation, complication, and recommended resolution",
                content_blocks=[
                    ContentBlock(
                        type="bullets",
                        body=[
                            "Current conditions create a clear need for executive action.",
                            "The strongest opportunities concentrate in a small number of priorities.",
                            "A sequenced plan can convert analysis into measurable progress.",
                        ],
                    )
                ],
                sources=[source_label],
                speaker_notes="Use this slide to align leaders on the recommendation before details.",
            )
        ]
        last_layout = "executive_summary"
        for section in sections[:4]:
            layout = self._next_layout(last_layout)
            last_layout = layout
            body = self._to_bullets(section.content)
            if not body:
                body = [self._summarize(section.content or section.title)]
            slides.append(
                GeneratedSlideSpec(
                    slide_number=len(slides) + 1,
                    slide_type="chart" if metrics and layout in {"chart", "callouts"} else "content",
                    action_title=self._action_title(section.title, section.content),
                    subheading=f"Evidence from {section.title}",
                    content_blocks=[
                        ContentBlock(
                            type="callout" if metrics and layout == "callouts" else "bullets",
                            body=body[:4],
                            callouts=[
                                f"{metric['label']}: {metric['value']}"
                                for metric in metrics[:3]
                            ]
                            if metrics and layout == "callouts"
                            else [],
                        )
                    ],
                    chart_spec={"type": "bar", "metrics": metrics} if metrics and layout == "chart" else None,
                    sources=[source_label],
                    speaker_notes=f"Explain why {section.title} matters to the recommendation.",
                )
            )
        slides.append(
            GeneratedSlideSpec(
                slide_number=len(slides) + 1,
                slide_type="process",
                action_title="Prioritize next steps to convert the recommendation into execution",
                subheading="Recommended ownership sequence",
                content_blocks=[
                    ContentBlock(
                        type="table",
                        body=[
                            ["Action", "Owner", "Timing"],
                            ["Confirm decision criteria", "Executive sponsor", "Week 1"],
                            ["Assign workstream owners", "Program lead", "Week 2"],
                            ["Review progress and risks", "Steering team", "Monthly"],
                        ],
                    )
                ],
                sources=[SOURCE_NEEDED_LABEL],
                speaker_notes="Close with specific actions, owners, and cadence.",
            )
        )
        return DeckSpec(
            deck_title=title,
            audience="Executive audience",
            goal=instructions or "Create an executive-ready recommendation deck.",
            narrative_arc="Situation -> Complication -> Resolution",
            slides=slides,
        )

    def _deck_to_outlines(
        self, deck: DeckSpec, job_id: str, mode: str
    ) -> list[SlideOutline]:
        outlines = []
        last_layout: str | None = None
        for slide in deck.slides:
            content = slide.model_dump()
            content["title"] = slide.action_title
            content["summary"] = slide.subheading
            content["bullets"] = self._body_to_bullets(slide)
            content["metrics"] = self._metrics_from_slide(slide)
            preferred_layout = self._layout_for_slide(slide)
            layout = self._layout_with_variety(
                slide, preferred_layout, last_layout, len(outlines)
            )
            last_layout = layout
            outlines.append(
                SlideOutline(
                    id=str(uuid.uuid4()),
                    job_id=job_id,
                    slide_index=slide.slide_number - 1,
                    mode="flexible",
                    label=slide.action_title,
                    content_json=content,
                    layout_json={
                        "layout": layout,
                        "visual_elements": self._visual_elements_for_layout(layout),
                        "generation_mode": mode,
                    },
                    qa_status=slide.qa.consulting_status,
                    qa_issues_json={"issues": slide.qa.issues},
                    created_at=self._timestamp(),
                )
            )
        return outlines

    def _pick_sections(self, sections: list[DocumentSection]) -> list[DocumentSection]:
        skipped = {"overview", "executive summary", "introduction", "background"}
        primary = [
            section
            for section in sections
            if section.level <= 2 and section.title.strip().lower() not in skipped
        ]
        return primary[:12] if primary else sections[:8]

    def _outline_for_section(
        self,
        template: TemplateProfile,
        bundle: DocumentBundle,
        slide_index: int,
        section: DocumentSection,
        layout: str,
    ) -> SlideOutline:
        metrics = self._pick_metrics(bundle.metrics, count=3)
        content = {
            "title": section.title,
            "summary": self._summarize(section.content),
            "bullets": self._to_bullets(section.content),
            "metrics": metrics,
        }
        if metrics and layout == "chart":
            layout_json = {"layout": "chart", "visual_elements": ["charts"]}
        elif metrics and layout == "callouts":
            layout_json = {"layout": "callouts", "visual_elements": ["callouts"]}
        else:
            layout_json = {"layout": layout, "visual_elements": ["icons"]}
        return SlideOutline(
            id=str(uuid.uuid4()),
            job_id=bundle.job_id,
            slide_index=slide_index,
            mode="flexible",
            label=section.title,
            content_json=content,
            layout_json=layout_json,
            created_at=self._timestamp(),
        )

    def _outline_for_flexible_slide(
        self,
        template: TemplateProfile,
        bundle: DocumentBundle,
        slide_spec: SlideSpec,
        layout: str,
    ) -> SlideOutline:
        section = self._match_section(bundle.sections, slide_spec)
        metrics = self._pick_metrics(bundle.metrics, count=3)
        content = {
            "title": slide_spec.label,
            "summary": self._summarize(section.content if section else ""),
            "bullets": self._to_bullets(section.content if section else ""),
            "metrics": metrics,
            "intent": slide_spec.intent or slide_spec.label,
        }
        if metrics and layout == "chart":
            layout_json = {"layout": "chart", "visual_elements": ["charts"]}
        elif metrics and layout == "callouts":
            layout_json = {"layout": "callouts", "visual_elements": ["callouts"]}
        else:
            layout_json = {"layout": layout, "visual_elements": ["icons"]}
        return SlideOutline(
            id=str(uuid.uuid4()),
            job_id=bundle.job_id,
            slide_index=slide_spec.index,
            mode="flexible",
            label=slide_spec.label,
            content_json=content,
            layout_json=layout_json,
            created_at=self._timestamp(),
        )

    def _outline_for_strict_slide(
        self,
        template: TemplateProfile,
        bundle: DocumentBundle,
        slide_spec: SlideSpec,
    ) -> tuple[SlideOutline, list[dict[str, Any]]]:
        warnings: list[dict[str, Any]] = []
        field_values: dict[str, Any] = {}
        if slide_spec.slide_schema:
            for field in slide_spec.slide_schema.fields:
                value = self._find_field_value(field.id, field.type, bundle)
                if value is None:
                    value = "[INSERT CONTENT HERE]"
                    warnings.append(
                        {
                            "slide_index": slide_spec.index,
                            "field": field.id,
                            "message": "Missing content for strict field.",
                        }
                    )
                field_values[field.id] = value
        content = {"fields": field_values}
        layout_json = {"layout": "strict", "visual_elements": []}
        outline = SlideOutline(
            id=str(uuid.uuid4()),
            job_id=bundle.job_id,
            slide_index=slide_spec.index,
            mode="strict",
            label=slide_spec.label,
            content_json=content,
            layout_json=layout_json,
            created_at=self._timestamp(),
        )
        return outline, warnings

    def _match_section(
        self, sections: list[DocumentSection], slide_spec: SlideSpec
    ) -> DocumentSection | None:
        if not sections:
            return None
        for section in sections:
            if slide_spec.label.lower() in section.title.lower():
                return section
        return sections[0]

    def _find_field_value(
        self, field_id: str, field_type: str, bundle: DocumentBundle
    ) -> Any:
        normalized = field_id.replace("_", " ").lower()
        for section in bundle.sections:
            if normalized in section.title.lower():
                return self._summarize(section.content)
        if field_type in {"text", "date"}:
            semantic = self._semantic_field_value(normalized, bundle)
            if semantic is not None:
                return semantic
        if field_type in {"number", "enum"} and bundle.metrics:
            return bundle.metrics[0].value
        return None

    def _semantic_field_value(self, normalized_field_id: str, bundle: DocumentBundle) -> str | None:
        sections = bundle.sections
        if not sections:
            return None
        if any(token in normalized_field_id for token in ["title", "name"]):
            return bundle.metadata.title or sections[0].title
        if "summary" in normalized_field_id:
            for section in sections:
                if "executive summary" in section.title.lower():
                    return self._summarize(section.content)
            return self._summarize(sections[0].content)
        if any(token in normalized_field_id for token in ["implication", "recommendation", "message"]):
            for section in sections:
                if section.title.lower() not in {"overview", "executive summary"}:
                    return self._summarize(section.content)
            return self._summarize(sections[0].content)
        return None

    def _title_from_instructions(self, instructions: str) -> str:
        cleaned = " ".join(instructions.split())
        if not cleaned:
            return "Executive Recommendation"
        return cleaned[:70].rstrip(".,;:") or "Executive Recommendation"

    def _sections_from_instructions(self, instructions: str) -> list[DocumentSection]:
        content = instructions or "Build a concise executive recommendation deck."
        return [
            DocumentSection(
                title="Decision Context",
                level=1,
                content=content,
                source_doc_id="prompt",
            ),
            DocumentSection(
                title="Key Implications",
                level=1,
                content=content,
                source_doc_id="prompt",
            ),
            DocumentSection(
                title="Recommended Path",
                level=1,
                content=content,
                source_doc_id="prompt",
            ),
        ]

    def _action_title(self, title: str, content: str) -> str:
        keyword_title = self._keyword_action_title(title, content)
        if keyword_title:
            return keyword_title
        first_sentence = self._summarize(content)
        if 5 <= len(first_sentence.split()) <= 16:
            return first_sentence[:110]
        base = self._clean_section_title(title)
        if not base:
            base = "The analysis"
        if re.search(r"\b\d+(\.\d+)?%?\b", first_sentence):
            return f"{base} shows measurable impact that should guide the decision"[:110]
        return f"Prioritize {base.lower()} to strengthen the recommendation"[:110]

    def _clean_section_title(self, title: str) -> str:
        cleaned = re.sub(r"^\d+(\.\d+)*\s*", "", title).strip()
        cleaned = re.sub(r"[^A-Za-z0-9\s%-]", "", cleaned)
        return " ".join(cleaned.split())

    def _keyword_action_title(self, title: str, content: str) -> str | None:
        combined = f"{title} {content}".lower()
        rules = [
            (
                "context rot",
                "Context rot makes long-running AI coding work increasingly unreliable",
            ),
            (
                "hallucination",
                "Ambiguous prompts amplify hallucinations in generated code",
            ),
            (
                "reproducibility",
                "Untracked AI decisions create a reproducibility gap for teams",
            ),
            (
                "chatbot to employee",
                "Treat AI agents as managed teammates to improve software outcomes",
            ),
            (
                "product manager",
                "Developers should manage AI agents with product-style specifications",
            ),
            (
                "external brain",
                "External memory gives agents the context they need to work reliably",
            ),
            (
                "memory bank",
                "A memory bank turns ad hoc prompting into persistent-context engineering",
            ),
            (
                "vibe coding",
                "Vibe coding breaks down when software work requires engineering discipline",
            ),
        ]
        for keyword, action_title in rules:
            if keyword in combined:
                return action_title
        return None

    def _repair_model_titles(self, deck: DeckSpec) -> None:
        for slide in deck.slides:
            title = " ".join(slide.action_title.split())
            title = title.rstrip(".")
            compound = re.match(
                r"^(Identify|Recognize|Address|Explain|Describe)\s+(.+?)\s+and\s+(.+?)\s+as\s+(.+)$",
                title,
                flags=re.IGNORECASE,
            )
            if compound:
                title = f"{compound.group(1)} {compound.group(4)}"
            compound_action = re.match(
                r"^(Mitigate|Reduce|Address|Eliminate|Manage|Prevent|Quantify)\s+"
                r"(.+?)\s+and\s+(.+)$",
                title,
                flags=re.IGNORECASE,
            )
            if compound_action:
                title = f"{compound_action.group(1)} {compound_action.group(3)}"
            if " and " in title.lower():
                title = title.split(" and ", 1)[0]
            if len(title.split()) > 16:
                title = " ".join(title.split()[:16]).rstrip(".,;:")
            slide.action_title = title

    def _normalize_source_labels(
        self, deck: DeckSpec, bundle: DocumentBundle
    ) -> list[dict[str, Any]]:
        has_source_material = self._has_uploaded_source_material(bundle)
        fallback_label = (
            UPLOADED_SOURCE_LABEL if has_source_material else SOURCE_NEEDED_LABEL
        )
        warnings: list[dict[str, Any]] = []
        for slide in deck.slides:
            original_sources = list(slide.sources)
            normalized: list[str] = []
            invalid_sources: list[str] = []
            for source in original_sources:
                label = str(source).strip()
                canonical = self._canonical_source_label(label, has_source_material)
                if canonical:
                    normalized.append(canonical)
                elif label:
                    invalid_sources.append(label)

            if invalid_sources and fallback_label not in normalized:
                normalized.append(fallback_label)
            if not normalized:
                normalized.append(fallback_label)

            slide.sources = self._dedupe_preserving_order(normalized)
            if slide.sources == original_sources and not invalid_sources:
                continue

            invalid_summary = ", ".join(invalid_sources[:3])
            if invalid_summary:
                message = (
                    "Unverified source labels were replaced with "
                    f"{fallback_label}: {invalid_summary}"
                )
            else:
                message = f"Missing source labels were set to {fallback_label}."
            slide.qa.issues.append({"category": "source_label", "message": message})
            warnings.append(
                {
                    "slide_index": slide.slide_number - 1,
                    "field": "source_label",
                    "message": message,
                }
            )
        return warnings

    def _has_uploaded_source_material(self, bundle: DocumentBundle) -> bool:
        return bool(
            bundle.sections
            or bundle.tables
            or bundle.metrics
            or bundle.content_inventory
        )

    def _canonical_source_label(
        self, label: str, allow_uploaded_source: bool
    ) -> str | None:
        normalized = label.strip().casefold()
        if allow_uploaded_source and normalized == UPLOADED_SOURCE_LABEL.casefold():
            return UPLOADED_SOURCE_LABEL
        if normalized == SOURCE_NEEDED_LABEL.casefold():
            return SOURCE_NEEDED_LABEL
        return None

    def _dedupe_preserving_order(self, values: list[str]) -> list[str]:
        deduped: list[str] = []
        for value in values:
            if value not in deduped:
                deduped.append(value)
        return deduped

    def _ground_numeric_claims(
        self, deck: DeckSpec, bundle: DocumentBundle
    ) -> list[dict[str, Any]]:
        supported_numbers = self._supported_numeric_tokens(bundle)
        warnings: list[dict[str, Any]] = []
        for slide in deck.slides:
            unsupported = sorted(
                token
                for token in self._numeric_tokens(self._slide_claim_text(slide))
                if token not in supported_numbers
            )
            if not unsupported:
                continue
            self._mark_unsupported_numeric_claims(slide, unsupported)
            if SOURCE_NEEDED_LABEL not in slide.sources:
                slide.sources.append(SOURCE_NEEDED_LABEL)
            issue = {
                "category": "source_coverage",
                "message": (
                    "Unsupported quantitative claim needs a source: "
                    + ", ".join(unsupported[:5])
                ),
            }
            slide.qa.issues.append(issue)
            warnings.append(
                {
                    "slide_index": slide.slide_number - 1,
                    "field": "source_coverage",
                    "message": issue["message"],
                }
            )
        return warnings

    def _supported_numeric_tokens(self, bundle: DocumentBundle) -> set[str]:
        source_text = " ".join(
            [section.content for section in bundle.sections]
            + [str(metric.value) for metric in bundle.metrics]
            + [inventory for inventory in bundle.content_inventory]
        )
        tokens = self._numeric_tokens(source_text)
        for token in list(tokens):
            if token.endswith("%"):
                tokens.add(token[:-1])
        for metric in bundle.metrics:
            tokens.add(self._normalize_numeric_token(str(metric.value)))
            if metric.unit:
                tokens.add(self._normalize_numeric_token(f"{metric.value}{metric.unit}"))
        return tokens

    def _slide_claim_text(self, slide: GeneratedSlideSpec) -> str:
        parts: list[str] = [slide.action_title, slide.subheading]
        for block in slide.content_blocks:
            parts.extend(str(item) for item in block.body)
            parts.extend(block.annotations)
            parts.extend(block.callouts)
        if slide.chart_spec:
            parts.append(str(slide.chart_spec))
        return " ".join(parts)

    def _mark_unsupported_numeric_claims(
        self, slide: GeneratedSlideSpec, unsupported: list[str]
    ) -> None:
        unsupported_set = set(unsupported)
        for block in slide.content_blocks:
            block.body = [
                self._mark_value_if_unsupported_number(item, unsupported_set)
                for item in block.body
            ]
            block.annotations = [
                self._mark_text_if_unsupported_number(item, unsupported_set)
                for item in block.annotations
            ]
            block.callouts = [
                self._mark_text_if_unsupported_number(item, unsupported_set)
                for item in block.callouts
            ]

    def _mark_value_if_unsupported_number(
        self, value: Any, unsupported: set[str]
    ) -> Any:
        if isinstance(value, str):
            return self._mark_text_if_unsupported_number(value, unsupported)
        if isinstance(value, list):
            return [
                self._mark_text_if_unsupported_number(item, unsupported)
                if isinstance(item, str)
                else item
                for item in value
            ]
        return value

    def _mark_text_if_unsupported_number(self, text: str, unsupported: set[str]) -> str:
        if "[source needed]" in text:
            return text
        if self._numeric_tokens(text) & unsupported:
            return f"{text} [source needed]"
        return text

    def _numeric_tokens(self, text: str) -> set[str]:
        return {
            self._normalize_numeric_token(match.group(0))
            for match in re.finditer(
                r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)%?(?!\w)",
                text,
            )
        }

    def _normalize_numeric_token(self, token: str) -> str:
        cleaned = token.strip().replace(",", "")
        if cleaned.endswith(".0"):
            cleaned = cleaned[:-2]
        return cleaned

    def _body_to_bullets(self, slide: GeneratedSlideSpec) -> list[str]:
        bullets: list[str] = []
        for block in slide.content_blocks:
            for item in block.body:
                if isinstance(item, str):
                    cleaned = self._clean_generated_visual_placeholder(item)
                    if cleaned:
                        bullets.append(cleaned)
                elif isinstance(item, list):
                    cleaned = self._clean_generated_visual_placeholder(
                        " | ".join(str(value) for value in item)
                    )
                    if cleaned:
                        bullets.append(cleaned)
        return bullets[:5]

    def _clean_generated_visual_placeholder(self, text: str) -> str:
        cleaned = re.sub(
            r"\[\s*diagram description\s*:[^\]]+\]",
            "",
            str(text),
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"\bdiagram description\s*:[^.]+\.?",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        return " ".join(cleaned.split()).strip(" -:;")

    def _metrics_from_slide(self, slide: GeneratedSlideSpec) -> list[dict[str, Any]]:
        metrics = self._metrics_from_chart_spec(slide.chart_spec)
        if metrics:
            return metrics
        chart_signal = (
            slide.slide_type == "chart"
            or any(
                token in slide.action_title.lower()
                for token in ("quantify", "visualize", "measure", "adoption")
            )
        )
        if not chart_signal:
            return []
        extracted: list[dict[str, Any]] = []
        for bullet in self._body_to_bullets(slide):
            match = re.search(
                r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(%?)(?!\w)",
                bullet,
            )
            if not match:
                continue
            value_text = match.group(1).replace(",", "")
            try:
                value: float | int = float(value_text)
            except ValueError:
                continue
            if value.is_integer():
                value = int(value)
            label = self._metric_label_from_text(bullet, match.start())
            extracted.append(
                {
                    "label": label,
                    "value": value,
                    "unit": match.group(2) or None,
                }
            )
        return extracted[:5]

    def _metric_label_from_text(self, text: str, number_start: int) -> str:
        prefix = text[:number_start].strip(" :,-")
        if prefix:
            return self._truncate_at_word(prefix, 34).removesuffix("...")
        suffix = text[number_start:].strip(" :,-")
        return self._truncate_at_word(suffix, 34).removesuffix("...") or "Metric"

    def _metrics_from_chart_spec(
        self, chart_spec: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        if not chart_spec:
            return []
        metrics = chart_spec.get("metrics", [])
        if isinstance(metrics, list) and metrics:
            return metrics
        data_points = chart_spec.get("data_points", [])
        if isinstance(data_points, list) and data_points:
            normalized: list[dict[str, Any]] = []
            for point in data_points:
                if not isinstance(point, dict):
                    continue
                label = point.get("label") or point.get("name") or "Metric"
                value = point.get("value")
                if value is None:
                    continue
                normalized.append(
                    {
                        "label": label,
                        "value": value,
                        "unit": point.get("unit"),
                    }
                )
            return normalized
        return []

    def _layout_for_slide(self, slide: GeneratedSlideSpec) -> str:
        intent_text = self._slide_intent_text(slide)
        if slide.chart_spec or (
            slide.slide_type == "chart" and self._metrics_from_slide(slide)
        ):
            return "chart"
        if slide.slide_type in {"section", "divider"}:
            return "section_divider"
        if slide.slide_type == "executive_summary" and slide.slide_number == 1:
            return "executive_summary"
        if slide.slide_type in {"anti_pattern", "anti-pattern"} or any(
            token in intent_text
            for token in ("anti-pattern", "anti pattern", "stop doing", "failure mode", "fails")
        ):
            return "anti_patterns"
        if any(
            token in intent_text
            for token in ("external brain", "memory bank", "hierarchy", "dependency graph")
        ):
            return "dependency_map"
        if slide.slide_type == "checklist" or any(
            token in intent_text
            for token in ("checklist", "quick-start", "quick start", "adopt it", "execute the transition", "standardize")
        ):
            return "checklist"
        if slide.slide_type == "quote" or any(
            token in intent_text
            for token in (
                "developer role",
                "product manager",
                "product-manager",
                "ai manager",
                "manager of ai",
                "employee management",
                "managed team member",
                "team member",
                "mental model",
                "reviewer mode",
            )
        ):
            return "quote_sidebar"
        if slide.slide_type in {"reference", "code"} or any(
            token in intent_text
            for token in ("markdown", "rules file", "rules files", "code", "github", "tool-agnostic", "tool agnostic")
        ):
            return "code_panel"
        if slide.slide_type in {"framework", "cycle"} or any(
            token in intent_text
            for token in ("cycle", "workflow", "six phases", "phase", "operating model")
        ):
            return "framework_cycle"
        block_types = {block.type for block in slide.content_blocks}
        if "table" in block_types:
            return "process"
        if "callout" in block_types:
            return "callouts"
        if slide.slide_type in {"matrix", "comparison"}:
            return "icon_grid"
        return "two_column"

    def _layout_with_variety(
        self,
        slide: GeneratedSlideSpec,
        preferred_layout: str,
        last_layout: str | None,
        slide_index: int,
    ) -> str:
        fixed_layouts = {
            "executive_summary",
            "section_divider",
            "chart",
            "process",
            "quote_sidebar",
            "framework_cycle",
            "dependency_map",
            "checklist",
            "code_panel",
            "anti_patterns",
        }
        if preferred_layout in fixed_layouts:
            if preferred_layout != last_layout:
                return preferred_layout
        cycle = ["two_column", "icon_grid", "quote_sidebar", "callouts", "checklist"]
        if preferred_layout == "two_column":
            layout = cycle[slide_index % len(cycle)]
        else:
            layout = preferred_layout if preferred_layout in cycle else cycle[slide_index % len(cycle)]
        if layout == last_layout:
            layout = cycle[(cycle.index(layout) + 1) % len(cycle)]
        return layout

    def _visual_elements_for_layout(self, layout: str) -> list[str]:
        if layout == "section_divider":
            return ["section_marker", "typography"]
        if layout == "chart":
            return ["charts", "callouts"]
        if layout == "callouts":
            return ["callouts"]
        if layout == "process":
            return ["tables"]
        if layout == "quote_sidebar":
            return ["quote", "sidebar"]
        if layout == "framework_cycle":
            return ["cycle", "process"]
        if layout == "dependency_map":
            return ["diagram", "connectors"]
        if layout == "checklist":
            return ["checklist", "steps"]
        if layout == "code_panel":
            return ["reference_panel", "code"]
        if layout == "anti_patterns":
            return ["anti_pattern_cards", "icons"]
        return ["structured_text", "shapes"]

    def _slide_intent_text(self, slide: GeneratedSlideSpec) -> str:
        parts: list[str] = [slide.slide_type, slide.action_title, slide.subheading]
        for block in slide.content_blocks:
            parts.append(block.type)
            parts.extend(str(item) for item in block.body)
            parts.extend(block.annotations)
            parts.extend(block.callouts)
        return " ".join(parts).lower()

    def _next_layout(self, last_layout: str | None) -> str:
        for layout in self.layouts:
            if layout != last_layout:
                return layout
        return self.layouts[0]

    def _summarize(self, content: str) -> str:
        sentences = re.split(r"[.!?]\s+", content)
        summary = sentences[0] if sentences else content
        return self._truncate_at_word(summary, 160)

    def _truncate_at_word(self, text: str, limit: int) -> str:
        cleaned = " ".join(text.split())
        if len(cleaned) <= limit:
            return cleaned
        truncated = cleaned[: limit - 3].rsplit(" ", 1)[0].rstrip(".,;:")
        return f"{truncated}..."

    def _to_bullets(self, content: str) -> list[str]:
        lines = [line.strip("-• ") for line in content.splitlines() if line.strip()]
        bullets = [line for line in lines if len(line.split()) > 3]
        return bullets[:4] if bullets else lines[:4]

    def _pick_metrics(
        self, metrics: list[DocumentMetric], count: int
    ) -> list[dict[str, Any]]:
        selected = metrics[:count]
        return [
            {"label": metric.label, "value": metric.value, "unit": metric.unit}
            for metric in selected
        ]

    def _timestamp(self) -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")
