from collections import Counter
import re
from typing import Any

from app.models.outline import SlideOutline
from app.models.template import SlideSpec, TemplateProfile


CLAUDE_EDITING_GUIDE_URL = (
    "https://github.com/anthropics/skills/blob/main/skills/pptx/editing.md"
)


class GenerationEditingContract:
    """Claude-style editing standard for generated decks.

    The contract is intentionally an artifact, not a renderer. It captures the
    mapping decisions Claude's PPTX editing workflow asks an author to make:
    choose varied layouts up front, match content type to layout style, avoid
    repeating text-heavy slides, and keep diagram usage deliberate.
    """

    bullet_card_layouts = {"callouts", "icon_grid", "icon_rows", "two_column"}
    card_composition_families = {
        "callouts",
        "challenge_cards",
        "evidence_wall",
        "icon_grid",
        "icon_rows",
        "proof_strip",
        "source_repair_cards",
        "toolkit_grid",
        "two_column",
        "why_it_matters_cards",
    }
    diagram_layouts = {"dependency_map", "framework_cycle", "matrix_2x2"}
    fixed_layouts = {"cover", "section_divider", "closing_recommendation"}
    fixed_composition_families = {
        "editorial_cover",
        "path_forward_close",
        "section_divider",
    }
    multi_item_marker_re = re.compile(
        r"(?<!\w)(?:Step|Phase|Stage)\s+\d+\s*[:.)-]?|\b\d{1,2}[.)](?=\s+[A-Z])",
        re.IGNORECASE,
    )
    unicode_bullet_re = re.compile(r"[\u2022\u25e6\u25aa\u25cf]")

    def build(
        self,
        template: TemplateProfile,
        outlines: list[SlideOutline],
        phase: str = "planned",
    ) -> dict[str, Any]:
        flexible = [outline for outline in outlines if outline.mode == "flexible"]
        layouts = [self._visible_layout_key(outline) for outline in flexible]
        layout_counts = Counter(layouts)
        composition_families = [
            self._composition_family(outline)
            for outline in flexible
            if self._composition_family(outline)
            not in self.fixed_composition_families
        ]
        composition_counts = Counter(composition_families)
        adjacent_repeats = self._adjacent_repeats(flexible)
        adjacent_composition_repeats = self._adjacent_composition_repeats(flexible)
        bullet_card_count = sum(1 for layout in layouts if layout in self.bullet_card_layouts)
        composition_card_count = sum(
            1
            for family in composition_families
            if family in self.card_composition_families
        )
        diagram_slides = [outline for outline in flexible if self._layout(outline) in self.diagram_layouts]
        slide_mappings = [
            self._slide_mapping(outline, template, flexible)
            for outline in flexible
        ]
        template_mapped = sum(
            1 for mapping in slide_mappings if mapping.get("template_slide") is not None
        )
        slot_risk_count = sum(
            1
            for mapping in slide_mappings
            if mapping.get("slot_plan", {}).get("status") in {"risk", "cleanup", "inspect"}
        )
        structural_plan = self._structural_plan(template, outlines, slide_mappings)
        structural_operations = {
            int(operation["slide_index"]): operation
            for operation in structural_plan["operations"]
            if isinstance(operation.get("slide_index"), int)
        }
        for mapping in slide_mappings:
            operation = structural_operations.get(int(mapping["slide_index"]))
            if operation:
                mapping["structural_operation"] = operation
        formatting_fix_count = sum(
            self._formatting_fix_count(outline) for outline in flexible
        )
        formatting_warning_count = sum(
            1 for outline in flexible if self._unicode_bullet_count(outline) > 0
        )
        requirements = [
            self._varied_layout_requirement(layout_counts, len(flexible)),
            self._varied_composition_requirement(
                composition_counts,
                len(composition_families),
            ),
            self._adjacent_repeat_requirement(adjacent_repeats),
            self._composition_repeat_requirement(
                adjacent_composition_repeats,
                composition_counts,
                len(composition_families),
            ),
            self._bullet_card_requirement(bullet_card_count, len(flexible)),
            self._composition_card_requirement(
                composition_card_count,
                len(composition_families),
            ),
            self._diagram_requirement(diagram_slides, len(flexible)),
            self._template_mapping_requirement(template, flexible, template_mapped),
            self._structural_plan_requirement(structural_plan),
            self._formatting_requirement(flexible, formatting_fix_count),
            self._slot_fit_requirement(slide_mappings),
            self._multi_item_requirement(flexible),
        ]
        issue_count = sum(1 for item in requirements if item["status"] == "warning")
        return {
            "artifact": "editing-contract",
            "standard": "claude-pptx-editing-v1",
            "source": CLAUDE_EDITING_GUIDE_URL,
            "phase": phase,
            "status": "pass" if issue_count == 0 else "warning",
            "issue_count": issue_count,
            "slide_count": len(flexible),
            "layout_count": len(layout_counts),
            "unique_layout_count": len(layout_counts),
            "composition_family_count": len(composition_counts),
            "unique_composition_family_count": len(composition_counts),
            "bullet_card_ratio": round(
                bullet_card_count / len(flexible), 3
            )
            if flexible
            else 0,
            "composition_card_ratio": round(
                composition_card_count / len(composition_families), 3
            )
            if composition_families
            else 0,
            "diagram_count": len(diagram_slides),
            "template_mapped_count": template_mapped,
            "slot_risk_count": slot_risk_count,
            "structural_operation_count": structural_plan["operation_count"],
            "structural_warning_count": structural_plan["warning_count"],
            "formatting_fix_count": formatting_fix_count,
            "formatting_warning_count": formatting_warning_count,
            "structural_plan": structural_plan,
            "requirements": requirements,
            "layout_counts": dict(sorted(layout_counts.items())),
            "composition_family_counts": dict(sorted(composition_counts.items())),
            "slides": slide_mappings,
            "warnings": [
                item["message"]
                for item in requirements
                if item["status"] == "warning"
            ],
        }

    def template_slide_for(
        self,
        outline: SlideOutline,
        template: TemplateProfile,
        outlines: list[SlideOutline],
        used_counts: dict[int, int] | None = None,
    ) -> dict[str, Any] | None:
        """Return the source template frame selected for a generated slide.

        When ``used_counts`` is supplied (a per-deck source-slide usage tally),
        selection spreads across the template's slides — breaking the "same few
        slides over and over" repetition — by preferring the least-used source
        among comparably-scored candidates and for the no-match fallback."""
        return self._template_slide_for(outline, template, outlines, used_counts)

    def template_slide_candidates_for(
        self,
        outline: SlideOutline,
        template: TemplateProfile,
        outlines: list[SlideOutline],
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Return ranked source-template alternatives for review/debug UI."""
        return self._template_slide_candidates(outline, template, outlines, limit)

    def slot_plan_for(
        self,
        outline: SlideOutline,
        template_slide: dict[str, Any] | None,
        template: TemplateProfile,
    ) -> dict[str, Any]:
        """Return the item/slot fit plan for a mapped template slide.

        This public wrapper lets the renderer carry the Claude-style editing
        contract into the actual clone/edit artifact, so "delete excess
        elements" is measurable instead of only advisory.
        """
        return self._slot_plan(outline, template_slide, template)

    def _slide_mapping(
        self,
        outline: SlideOutline,
        template: TemplateProfile,
        outlines: list[SlideOutline],
    ) -> dict[str, Any]:
        layout = self._layout(outline)
        role = str(
            outline.content_json.get("narrative_role")
            or outline.layout_json.get("narrative_role")
            or ""
        )
        exhibit_type = self._exhibit_type(outline)
        content_type = self._content_type(layout, role, exhibit_type)
        template_slide = self._template_slide_for(outline, template, outlines)
        slot_plan = self._slot_plan(outline, template_slide, template)
        formatting_plan = self._formatting_plan(outline)
        return {
            "slide_index": outline.slide_index,
            "title": outline.content_json.get("action_title")
            or outline.content_json.get("title")
            or outline.label,
            "narrative_role": role,
            "content_type": content_type,
            "layout": layout,
            "composition_family": outline.layout_json.get("composition_family")
            or outline.content_json.get("composition_family"),
            "exhibit_type": exhibit_type,
            "template_slide": template_slide,
            "slot_plan": slot_plan,
            "formatting_plan": formatting_plan,
            "source_ref_count": len(outline.content_json.get("source_refs") or []),
            "rationale": self._rationale(layout, content_type, template_slide),
            "editing_notes": self._editing_notes(outline, layout),
        }

    def _structural_plan(
        self,
        template: TemplateProfile,
        outlines: list[SlideOutline],
        slide_mappings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        mappings_by_index = {
            int(mapping["slide_index"]): mapping
            for mapping in slide_mappings
            if isinstance(mapping.get("slide_index"), int)
        }
        operations: list[dict[str, Any]] = []
        used_template_indexes: set[int] = set()
        warnings: list[str] = []
        for position, outline in enumerate(outlines):
            mapping = mappings_by_index.get(outline.slide_index)
            template_slide = mapping.get("template_slide") if mapping else None
            operation = "render_native_composition"
            method = None
            if outline.mode == "strict":
                template_slide = self._strict_template_slide_payload(template, outline)
                operation = "preserve_template_slide"
                method = "strict_index"
            elif template.type == "brand" and template_slide:
                method = template_slide.get("method")
                operation = (
                    "fallback_template_frame"
                    if method in {"cyclic_fallback", "low_confidence_match"}
                    else "use_template_frame"
                )
            elif template.type == "strict" and outline.mode == "flexible":
                operation = "render_flexible_insert"
            if isinstance(template_slide, dict) and isinstance(template_slide.get("index"), int):
                used_template_indexes.add(int(template_slide["index"]))
            if operation == "fallback_template_frame":
                warnings.append(
                    f"Slide {outline.slide_index + 1} uses weak template mapping; inspect layout fit."
                )
            operations.append(
                {
                    "position": position,
                    "slide_index": outline.slide_index,
                    "operation": operation,
                    "template_slide": template_slide,
                    "template_method": method,
                    "layout": self._layout(outline),
                    "mode": outline.mode,
                    "before_content_edit": True,
                    "rationale": self._structural_operation_rationale(
                        operation,
                        template_slide,
                    ),
                }
            )
        template_indexes = {slide.index for slide in template.slides}
        unused_template_indexes = sorted(template_indexes - used_template_indexes)
        delete_unused = unused_template_indexes if template.type == "brand" else []
        unmapped_strict = unused_template_indexes if template.type == "strict" else []
        if unmapped_strict:
            warnings.append(
                f"{len(unmapped_strict)} strict template slide(s) lack a planned preserve/edit operation."
            )
        return {
            "status": "warning" if warnings else "pass",
            "template_type": template.type,
            "operation_count": len(operations),
            "warning_count": len(warnings),
            "delete_unused_template_slide_indexes": delete_unused,
            "unmapped_template_slide_indexes": unmapped_strict,
            "operations": operations,
            "warnings": warnings,
        }

    def _strict_template_slide_payload(
        self,
        template: TemplateProfile,
        outline: SlideOutline,
    ) -> dict[str, Any] | None:
        for slide in template.slides:
            if slide.index == outline.slide_index:
                return self._template_slide_payload(slide, "strict_index")
        return None

    def _structural_operation_rationale(
        self,
        operation: str,
        template_slide: dict[str, Any] | None,
    ) -> str:
        if operation == "use_template_frame" and template_slide:
            return (
                f"Map content to template slide {int(template_slide['index']) + 1} "
                "before filling placeholders."
            )
        if operation == "fallback_template_frame" and template_slide:
            return (
                f"Use template slide {int(template_slide['index']) + 1} as a fallback frame; "
                "review visually before content edit."
            )
        if operation == "preserve_template_slide":
            return "Preserve strict template slide geometry and edit only mapped fields."
        if operation == "render_flexible_insert":
            return "Insert a generated flexible slide after strict structural planning."
        return "Render a native authored composition before text/content fitting."

    def _layout(self, outline: SlideOutline) -> str:
        return str(outline.layout_json.get("layout") or "two_column")

    def _composition_family(self, outline: SlideOutline) -> str:
        return str(
            outline.layout_json.get("composition_family")
            or outline.content_json.get("composition_family")
            or self._layout(outline)
        )

    def _visible_layout_key(self, outline: SlideOutline) -> str:
        """Return the visible slide silhouette used for layout-variety checks.

        After authored rendering, the legacy ``layout`` field is often a
        compatibility/content-route label while ``composition_family`` is the
        actual visual shape the user sees. The Claude editing guidance is about
        visible monotony, so prefer the authored composition when present.
        """
        family = self._composition_family(outline)
        if family:
            return family
        return self._layout(outline)

    def _exhibit_type(self, outline: SlideOutline) -> str:
        exhibit = outline.content_json.get("exhibit_spec")
        if isinstance(exhibit, dict):
            return str(exhibit.get("type") or "")
        return ""

    def _content_type(self, layout: str, role: str, exhibit_type: str) -> str:
        if layout == "cover" or role == "cover":
            return "cover"
        if layout == "executive_summary" or role == "executive_summary":
            return "executive_summary"
        if exhibit_type in {"comparison_table", "reference_table"}:
            return "structured_comparison"
        if exhibit_type == "checklist" or layout == "checklist":
            return "steps_or_decisions"
        if layout in self.diagram_layouts:
            return "diagram_or_matrix"
        if role in {"closing", "recommendation"} or layout == "closing_recommendation":
            return "decision_close"
        return "evidence_points"

    def _template_slide_for(
        self,
        outline: SlideOutline,
        template: TemplateProfile,
        outlines: list[SlideOutline],
        used_counts: dict[int, int] | None = None,
    ) -> dict[str, Any] | None:
        if template.type == "freeform" or not template.slides:
            return None
        if template.type == "strict":
            for slide in template.slides:
                if slide.index == outline.slide_index:
                    return self._template_slide_payload(
                        slide,
                        "strict_index",
                        match_score=10,
                        match_reasons=["strict slide index"],
                    )
        candidates = self._template_slide_candidates(outline, template, outlines, limit=4)
        if not candidates or int(candidates[0].get("match_score") or 0) <= 0:
            if used_counts is not None:
                fallback_slide = min(
                    template.slides,
                    key=lambda s: (used_counts.get(int(s.index), 0), int(s.index)),
                )
            else:
                fallback_slide = template.slides[outline.slide_index % len(template.slides)]
            payload = self._template_slide_payload(
                fallback_slide,
                "cyclic_fallback",
                match_score=0,
                match_reasons=["no semantic or category match"],
            )
            payload["closest_candidates"] = candidates
            return payload
        if used_counts is not None:
            best_score = int(candidates[0].get("match_score") or 0)
            eligible = [
                candidate
                for candidate in candidates
                if int(candidate.get("match_score") or 0) >= max(1, best_score - 1)
            ]
            best = min(
                eligible,
                key=lambda c: (used_counts.get(int(c["index"]), 0), -int(c.get("match_score") or 0)),
            )
        else:
            best = candidates[0]
        score = int(best.get("match_score") or 0)
        method = "semantic_match" if score >= 3 else "low_confidence_match"
        slide = next(
            candidate_slide
            for candidate_slide in template.slides
            if candidate_slide.index == int(best["index"])
        )
        payload = self._template_slide_payload(
            slide,
            method,
            match_score=score,
            match_reasons=str(best.get("match_reason") or "").split(", "),
        )
        payload["closest_candidates"] = [
            candidate
            for candidate in candidates
            if candidate.get("index") != payload.get("index")
        ][:3]
        return payload

    def _template_slide_candidates(
        self,
        outline: SlideOutline,
        template: TemplateProfile,
        outlines: list[SlideOutline],
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        if template.type == "freeform" or not template.slides:
            return []
        layout = self._layout(outline)
        role = str(
            outline.content_json.get("narrative_role")
            or outline.layout_json.get("narrative_role")
            or ""
        )
        exhibit_type = self._exhibit_type(outline)
        content_type = self._content_type(layout, role, exhibit_type)
        wanted = " ".join(
            [
                layout,
                str(outline.content_json.get("archetype") or ""),
                role,
                exhibit_type,
                content_type,
                str(outline.label),
            ]
        ).lower()
        ranked: list[dict[str, Any]] = []
        for slide in template.slides:
            match = self._template_score(
                slide,
                wanted,
                content_type=content_type,
                exhibit_type=exhibit_type,
                role=role,
            )
            ranked.append(
                self._template_slide_payload(
                    slide,
                    "candidate",
                    match_score=int(match["score"]),
                    match_reasons=match["reasons"],
                )
            )
        ranked.sort(
            key=lambda candidate: (
                int(candidate.get("match_score") or 0),
                int(candidate.get("item_slot_count") or 0),
                -int(candidate.get("index") or 0),
            ),
            reverse=True,
        )
        return ranked[: max(0, limit)]

    def _template_score(
        self,
        slide: SlideSpec,
        wanted: str,
        content_type: str,
        exhibit_type: str,
        role: str,
    ) -> dict[str, Any]:
        parts = [
            slide.label,
            slide.layout_name or "",
            slide.intent or "",
            slide.content_category or "",
            slide.visual_guidance or "",
        ]
        haystack = " ".join(parts).lower()
        score = 0
        reasons: list[str] = []
        category = str(slide.content_category or "").strip().lower()
        category_score = self._category_match_score(
            content_type,
            exhibit_type,
            role,
            category,
            str(slide.visual_guidance or "").lower(),
        )
        if category_score:
            score += category_score
            reasons.append(f"category:{category or 'unspecified'}")
        for token in {
            token
            for token in wanted.replace("_", " ").split()
            if len(token) >= 5
        }:
            if token in haystack:
                score += 1
                reasons.append(f"token:{token}")
        if slide.mode == "strict":
            score += 1
            reasons.append("strict-mode")
        return {
            "score": score,
            "reasons": reasons[:6],
        }

    def _category_match_score(
        self,
        content_type: str,
        exhibit_type: str,
        role: str,
        category: str,
        visual_guidance: str,
    ) -> int:
        category = category.replace("-", "_")
        content_type = content_type.replace("-", "_")
        exhibit_type = exhibit_type.replace("-", "_")
        role = role.replace("-", "_")
        if content_type == "cover":
            return 5 if category == "section_or_cover" else 0
        if content_type == "executive_summary":
            return 4 if category in {"section_or_cover", "content", "evidence_points"} else 0
        if content_type == "structured_comparison":
            if category == "comparison":
                return 7
            if category == "structured_table" or "table frame" in visual_guidance:
                return 5
            return 0
        if exhibit_type == "reference_table":
            return 6 if category == "structured_table" else 0
        if exhibit_type in {"metric_chart", "line_chart", "bar_chart", "chart"}:
            return 7 if category == "metric_chart" or "chart frame" in visual_guidance else 0
        if content_type == "steps_or_decisions":
            if category == "process":
                return 6
            if category in {"structured_table", "quote_callout"}:
                return 3
            return 0
        if content_type == "diagram_or_matrix":
            return 4 if category in {"process", "comparison", "structured_table"} else 0
        if content_type == "decision_close":
            return 4 if category in {"quote_callout", "section_or_cover", "content"} else 0
        if role in {"problem", "risk", "challenge"} and category in {
            "evidence_points",
            "content",
            "quote_callout",
        }:
            return 3
        if content_type == "evidence_points":
            return 4 if category in {"evidence_points", "content", "media_story"} else 0
        return 0

    def _template_slide_payload(
        self,
        slide: SlideSpec,
        method: str,
        match_score: int = 0,
        match_reasons: list[str] | None = None,
    ) -> dict[str, Any]:
        fields = slide.slide_schema.fields if slide.slide_schema else []
        confidence = "fallback"
        if match_score >= 6:
            confidence = "high"
        elif match_score >= 3:
            confidence = "medium"
        elif match_score > 0:
            confidence = "low"
        return {
            "index": slide.index,
            "source_slide": slide.index + 1,
            "label": slide.label,
            "layout_name": slide.layout_name,
            "mode": slide.mode,
            "method": method,
            "match_score": match_score,
            "match_confidence": confidence,
            "match_reason": ", ".join(match_reasons or []) or "fallback",
            "intent": slide.intent,
            "content_category": slide.content_category,
            "visual_guidance": slide.visual_guidance,
            "schema_field_count": len(fields),
            "item_slot_count": self._template_item_slot_count(slide),
        }

    def _slot_plan(
        self,
        outline: SlideOutline,
        template_slide: dict[str, Any] | None,
        template: TemplateProfile,
    ) -> dict[str, Any]:
        source_items = self._source_item_count(outline)
        if template.type == "freeform" or template_slide is None:
            return {
                "status": "native",
                "action": "use_native_composition_slots",
                "source_item_count": source_items,
                "template_item_slot_count": None,
                "message": "Freeform authored slide uses renderer-native composition slots.",
            }
        slot_count = template_slide.get("item_slot_count")
        if not isinstance(slot_count, int) or slot_count <= 0:
            return {
                "status": "inspect",
                "action": "inspect_template_placeholders",
                "source_item_count": source_items,
                "template_item_slot_count": slot_count,
                "message": "Template slide has no schema item count; inspect placeholders before editing.",
            }
        if source_items > slot_count:
            return {
                "status": "risk",
                "action": "split_or_summarize_source_items",
                "source_item_count": source_items,
                "template_item_slot_count": slot_count,
                "overflow_count": source_items - slot_count,
                "message": (
                    f"{source_items} source items must fit {slot_count} template slots; "
                    "split the slide or summarize before render."
                ),
            }
        if source_items < slot_count:
            return {
                "status": "cleanup",
                "action": "delete_excess_template_elements",
                "source_item_count": source_items,
                "template_item_slot_count": slot_count,
                "excess_slot_count": slot_count - source_items,
                "message": (
                    f"{slot_count - source_items} unused template slot(s) should be removed, "
                    "not left blank."
                ),
            }
        return {
            "status": "fit",
            "action": "fill_template_slots",
            "source_item_count": source_items,
            "template_item_slot_count": slot_count,
            "message": "Source items match template item slots.",
        }

    def _template_item_slot_count(self, slide: SlideSpec) -> int | None:
        if not slide.slide_schema:
            return None
        total = 0
        list_like_fields = 0
        for field in slide.slide_schema.fields:
            if field.max_items:
                total += field.max_items
                list_like_fields += 1
                continue
            field_text = " ".join([field.id, field.type, field.location]).lower()
            if any(token in field_text for token in ("bullet", "item", "point", "step", "row")):
                total += 1
                list_like_fields += 1
        if total:
            return total
        return list_like_fields or None

    def _source_item_count(self, outline: SlideOutline) -> int:
        count = 0
        blocks = outline.content_json.get("content_blocks")
        if isinstance(blocks, list):
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                body = block.get("body")
                if isinstance(body, list):
                    count += len([item for item in body if str(item).strip()])
                elif isinstance(body, str) and body.strip():
                    count += max(1, len(self.multi_item_marker_re.findall(body)))
        exhibit = outline.content_json.get("exhibit_spec")
        if isinstance(exhibit, dict):
            for key in ("items", "steps", "rows", "messages", "supporting_points", "next_steps"):
                value = exhibit.get(key)
                if isinstance(value, list):
                    count = max(count, len([item for item in value if str(item).strip()]))
        bullets = outline.content_json.get("bullets")
        if isinstance(bullets, list):
            count = max(count, len([item for item in bullets if str(item).strip()]))
        return count

    def _rationale(
        self,
        layout: str,
        content_type: str,
        template_slide: dict[str, Any] | None,
    ) -> str:
        template_note = (
            f" mapped to template slide {template_slide['index'] + 1}"
            if template_slide
            else ""
        )
        if content_type == "diagram_or_matrix":
            return f"Use {layout} only because the slide carries a structural visual claim{template_note}."
        if content_type == "structured_comparison":
            return f"Use {layout} to keep multi-item evidence separated instead of concatenated{template_note}."
        if content_type == "steps_or_decisions":
            return f"Use {layout} so each step remains an independent paragraph/item{template_note}."
        return f"Use {layout} to match the slide role and avoid a default title-plus-bullets pattern{template_note}."

    def _editing_notes(self, outline: SlideOutline, layout: str) -> list[str]:
        notes = [
            "Keep each bullet/table item as a separate paragraph or shape.",
            "Shorten text before shrinking font size or allowing title wraps.",
        ]
        if layout in self.diagram_layouts:
            notes.append("Render diagram only when labels are source-specific and connectors do not cross node labels.")
        if outline.content_json.get("visual_qa_source_repair"):
            notes.append("Source-repaired slide: preserve safe source copy and avoid fake anti-pattern/diagram fallbacks.")
        return notes

    def _adjacent_repeats(
        self,
        outlines: list[SlideOutline],
    ) -> list[dict[str, Any]]:
        repeats: list[dict[str, Any]] = []
        for left, right in zip(outlines, outlines[1:]):
            left_layout = self._visible_layout_key(left)
            right_layout = self._visible_layout_key(right)
            if (
                left_layout == right_layout
                and left_layout not in self.fixed_layouts
                and left_layout not in self.fixed_composition_families
            ):
                repeats.append(
                    {
                        "slides": [left.slide_index, right.slide_index],
                        "layout": left_layout,
                    }
                )
        return repeats

    def _adjacent_composition_repeats(
        self,
        outlines: list[SlideOutline],
    ) -> list[dict[str, Any]]:
        repeats: list[dict[str, Any]] = []
        for left, right in zip(outlines, outlines[1:]):
            left_family = self._composition_family(left)
            right_family = self._composition_family(right)
            if (
                left_family
                and left_family == right_family
                and left_family not in self.fixed_composition_families
            ):
                repeats.append(
                    {
                        "slides": [left.slide_index, right.slide_index],
                        "composition_family": left_family,
                    }
                )
        return repeats

    def _varied_layout_requirement(
        self,
        layout_counts: Counter,
        slide_count: int,
    ) -> dict[str, Any]:
        minimum = min(5, max(2, (slide_count + 2) // 3)) if slide_count else 0
        unique = len(layout_counts)
        status = "pass" if unique >= minimum else "warning"
        return {
            "id": "varied_layout_mapping",
            "label": "Map content to varied layouts",
            "status": status,
            "message": f"{unique} visible layouts used; target is at least {minimum}.",
            "evidence": {"layout_counts": dict(sorted(layout_counts.items()))},
        }

    def _varied_composition_requirement(
        self,
        composition_counts: Counter,
        slide_count: int,
    ) -> dict[str, Any]:
        minimum = min(7, max(4, (slide_count + 1) // 2)) if slide_count >= 6 else min(2, slide_count)
        unique = len(composition_counts)
        status = "pass" if unique >= minimum else "warning"
        return {
            "id": "varied_composition_families",
            "label": "Vary visible composition families",
            "status": status,
            "message": (
                f"{unique} visible composition families used; target is at least {minimum}."
            ),
            "evidence": {
                "composition_family_counts": dict(sorted(composition_counts.items())),
            },
        }

    def _adjacent_repeat_requirement(
        self,
        adjacent_repeats: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "id": "avoid_adjacent_repetition",
            "label": "Avoid monotonous adjacent slide layouts",
            "status": "warning" if adjacent_repeats else "pass",
            "message": (
                f"{len(adjacent_repeats)} adjacent repeated layout pair(s)."
                if adjacent_repeats
                else "No adjacent repeated flexible layouts."
            ),
            "evidence": {"adjacent_repeats": adjacent_repeats},
        }

    def _composition_repeat_requirement(
        self,
        adjacent_repeats: list[dict[str, Any]],
        composition_counts: Counter,
        slide_count: int,
    ) -> dict[str, Any]:
        most_common_count = max(composition_counts.values(), default=0)
        repeat_limit = max(2, int(slide_count * 0.3)) if slide_count else 0
        overused = [
            {
                "composition_family": family,
                "count": count,
            }
            for family, count in sorted(composition_counts.items())
            if count > repeat_limit
        ]
        status = "warning" if adjacent_repeats or overused else "pass"
        return {
            "id": "avoid_repeated_composition_family",
            "label": "Avoid visible composition cycling",
            "status": status,
            "message": (
                f"{len(adjacent_repeats)} adjacent repeated composition pair(s); "
                f"most-used family appears {most_common_count}/{slide_count} times."
            ),
            "evidence": {
                "adjacent_repeats": adjacent_repeats,
                "overused_families": overused,
                "repeat_limit": repeat_limit,
            },
        }

    def _bullet_card_requirement(
        self,
        bullet_card_count: int,
        slide_count: int,
    ) -> dict[str, Any]:
        ratio = bullet_card_count / slide_count if slide_count else 0
        status = "warning" if slide_count >= 5 and ratio > 0.58 else "pass"
        return {
            "id": "avoid_card_grid_default",
            "label": "Avoid card-grid and title/bullet defaults",
            "status": status,
            "message": f"{bullet_card_count}/{slide_count} slides use bullet/card layouts.",
            "evidence": {"ratio": round(ratio, 3)},
        }

    def _composition_card_requirement(
        self,
        card_count: int,
        slide_count: int,
    ) -> dict[str, Any]:
        ratio = card_count / slide_count if slide_count else 0
        status = "warning" if slide_count >= 6 and ratio > 0.46 else "pass"
        return {
            "id": "avoid_card_composition_default",
            "label": "Avoid card-heavy visible composition",
            "status": status,
            "message": (
                f"{card_count}/{slide_count} visible slides use card/grid/strip composition families."
            ),
            "evidence": {"ratio": round(ratio, 3)},
        }

    def _diagram_requirement(
        self,
        diagram_slides: list[SlideOutline],
        slide_count: int,
    ) -> dict[str, Any]:
        limit = max(1, slide_count // 5) if slide_count else 0
        weak = [
            outline.slide_index
            for outline in diagram_slides
            if not outline.content_json.get("diagram_spec")
            and self._layout(outline) != "matrix_2x2"
        ]
        status = "pass" if len(diagram_slides) <= limit and not weak else "warning"
        return {
            "id": "minimize_and_ground_diagrams",
            "label": "Use diagrams sparingly and only when source-backed",
            "status": status,
            "message": f"{len(diagram_slides)} diagram-like slide(s); target maximum is {limit}.",
            "evidence": {
                "diagram_slide_indexes": [outline.slide_index for outline in diagram_slides],
                "weak_diagram_slide_indexes": weak,
            },
        }

    def _template_mapping_requirement(
        self,
        template: TemplateProfile,
        outlines: list[SlideOutline],
        mapped_count: int,
    ) -> dict[str, Any]:
        if template.type == "freeform":
            return {
                "id": "template_mapping",
                "label": "Map to source template slides when present",
                "status": "pass",
                "message": "Freeform deck has no uploaded template to map.",
                "evidence": {"template_type": template.type},
            }
        if template.type == "brand" and not template.slides:
            status = "warning" if template.source_file else "pass"
            return {
                "id": "template_mapping",
                "label": "Map generated slides to analyzed template slides",
                "status": status,
                "message": (
                    "Brand template source has no analyzed slide frames."
                    if status == "warning"
                    else "Brand profile has no source slide inventory; native authored rendering is used."
                ),
                "evidence": {
                    "template_type": template.type,
                    "template_slide_count": 0,
                    "source_file": template.source_file,
                },
            }
        status = "pass" if mapped_count == len(outlines) else "warning"
        return {
            "id": "template_mapping",
            "label": "Map generated slides to analyzed template slides",
            "status": status,
            "message": f"{mapped_count}/{len(outlines)} slides have a template mapping.",
            "evidence": {"template_type": template.type},
        }

    def _structural_plan_requirement(self, structural_plan: dict[str, Any]) -> dict[str, Any]:
        warning_count = int(structural_plan.get("warning_count") or 0)
        delete_count = len(structural_plan.get("delete_unused_template_slide_indexes") or [])
        return {
            "id": "complete_structure_before_content_edit",
            "label": "Complete structural plan before content edits",
            "status": "warning" if warning_count else "pass",
            "message": (
                f"{structural_plan.get('operation_count', 0)} structural operation(s) planned before content edits; "
                f"{delete_count} unused template slide(s) marked for deletion."
            ),
            "evidence": {
                "warning_count": warning_count,
                "delete_unused_template_slide_indexes": structural_plan.get(
                    "delete_unused_template_slide_indexes",
                    [],
                ),
                "unmapped_template_slide_indexes": structural_plan.get(
                    "unmapped_template_slide_indexes",
                    [],
                ),
                "warnings": structural_plan.get("warnings", []),
            },
        }

    def _formatting_requirement(
        self,
        outlines: list[SlideOutline],
        formatting_fix_count: int,
    ) -> dict[str, Any]:
        risky = [
            {
                "slide_index": outline.slide_index,
                "unicode_bullet_count": self._unicode_bullet_count(outline),
            }
            for outline in outlines
            if self._unicode_bullet_count(outline) > 0
        ]
        return {
            "id": "pptx_formatting_rules",
            "label": "Follow PPTX text formatting rules",
            "status": "warning" if risky else "pass",
            "message": (
                f"{formatting_fix_count} unicode bullet glyph(s) sanitized; "
                f"{len(risky)} slide(s) still contain unicode bullets."
            ),
            "evidence": {"unicode_bullet_slide_indexes": risky},
        }

    def _slot_fit_requirement(self, slide_mappings: list[dict[str, Any]]) -> dict[str, Any]:
        risky = [
            {
                "slide_index": mapping["slide_index"],
                "action": mapping.get("slot_plan", {}).get("action"),
                "message": mapping.get("slot_plan", {}).get("message"),
            }
            for mapping in slide_mappings
            if mapping.get("slot_plan", {}).get("status") in {"risk", "cleanup", "inspect"}
        ]
        return {
            "id": "match_source_items_to_template_slots",
            "label": "Match source items to template slots",
            "status": "warning" if risky else "pass",
            "message": (
                f"{len(risky)} slide(s) need slot cleanup or split/summarize decisions."
                if risky
                else "Source item counts match available template/native slots."
            ),
            "evidence": {"slot_risks": risky},
        }

    def _multi_item_requirement(self, outlines: list[SlideOutline]) -> dict[str, Any]:
        risky: list[int] = []
        for outline in outlines:
            blocks = outline.content_json.get("content_blocks")
            if not isinstance(blocks, list):
                continue
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                body = block.get("body")
                if isinstance(body, str) and self._looks_concatenated_multi_item(body):
                    risky.append(outline.slide_index)
                    break
                if isinstance(body, list) and any(
                    isinstance(item, str) and self._looks_concatenated_multi_item(item)
                    for item in body
                ):
                    risky.append(outline.slide_index)
                    break
        return {
            "id": "separate_multi_item_content",
            "label": "Keep multi-item content as separate paragraphs/items",
            "status": "warning" if risky else "pass",
            "message": (
                f"{len(risky)} slide(s) have concatenated multi-item content."
                if risky
                else "No concatenated multi-item content blocks detected."
            ),
            "evidence": {"risky_slide_indexes": risky},
        }

    def _looks_concatenated_multi_item(self, text: str) -> bool:
        if "\n" in text:
            return True
        return len(self.multi_item_marker_re.findall(text)) >= 2

    def _formatting_plan(self, outline: SlideOutline) -> dict[str, Any]:
        remaining = self._unicode_bullet_count(outline)
        fixed = self._formatting_fix_count(outline)
        if remaining:
            return {
                "status": "warning",
                "action": "replace_unicode_bullets_with_list_items",
                "unicode_bullet_count": remaining,
                "sanitized_count": fixed,
                "message": "Unicode bullet glyphs remain; use proper PPTX list items instead.",
            }
        if fixed:
            return {
                "status": "fixed",
                "action": "sanitized_unicode_bullets",
                "unicode_bullet_count": 0,
                "sanitized_count": fixed,
                "message": f"Sanitized {fixed} unicode bullet glyph(s) before rendering.",
            }
        return {
            "status": "pass",
            "action": "inherit_layout_list_formatting",
            "unicode_bullet_count": 0,
            "sanitized_count": 0,
            "message": "No unicode bullet glyphs detected.",
        }

    def _formatting_fix_count(self, outline: SlideOutline) -> int:
        repair = outline.layout_json.get("editing_contract_repair")
        if not isinstance(repair, dict):
            return 0
        try:
            return int(repair.get("unicode_bullet_sanitized_count") or 0)
        except (TypeError, ValueError):
            return 0

    def _unicode_bullet_count(self, outline: SlideOutline) -> int:
        return sum(
            len(self.unicode_bullet_re.findall(text))
            for text in self._iter_outline_text_values(outline.content_json)
        )

    def _iter_outline_text_values(self, value: Any):
        if isinstance(value, str):
            yield value
        elif isinstance(value, list):
            for item in value:
                yield from self._iter_outline_text_values(item)
        elif isinstance(value, dict):
            for item in value.values():
                yield from self._iter_outline_text_values(item)
