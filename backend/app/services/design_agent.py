import concurrent.futures
import re
from typing import Any

from app.models.outline import SlideOutline
from app.models.qa import QAIssue


UNICODE_BULLET_CHARS = "\u2022\u25e6\u25aa\u25cf"
UNICODE_BULLET_PREFIX_RE = re.compile(rf"^\s*[{UNICODE_BULLET_CHARS}]\s*")


class DesignAgent:
    def __init__(self) -> None:
        self.icon_pool = {
            "strategy": "FaChessKnight",
            "growth": "FaChartLine",
            "risk": "FaExclamationTriangle",
            "status": "FaTachometerAlt",
            "timeline": "FaProjectDiagram",
            "security": "FaShieldAlt",
            "data": "FaDatabase",
            "customer": "FaUsers",
            "finance": "FaDollarSign",
            "agent": "FaRobot",
            "brain": "FaBrain",
            "chat": "FaComments",
            "code": "FaCodeBranch",
            "docs": "FaBookOpen",
            "manager": "FaUserTie",
            "standards": "FaClipboardCheck",
            "systems": "FaSitemap",
            "tools": "FaTools",
            "default": "FaLightbulb",
        }
        self.keyword_icon_map = [
            (("hallucination", "fabricated", "broken", "defect", "fragile"), "risk"),
            (("context rot", "context window", "context windows", "knowledge", "data", "database"), "data"),
            (("reproducibility", "traceable", "traceability", "version", "verified"), "security"),
            (("memory bank", "external brain", "persistent context", "context management"), "brain"),
            (("agent", "agents", "model", "models", "ai manager"), "agent"),
            (("chat", "prompt", "prompts", "conversation", "transient"), "chat"),
            (("documentation", "markdown", "docs", "document", "files", "file"), "docs"),
            (("developer role", "manager", "product manager", "stakeholder"), "manager"),
            (("standard", "standards", "criteria", "checklist", "review"), "standards"),
            (("github", "repository", "repo", "codebase", "implementation"), "code"),
            (("architecture", "system", "systems", "framework", "hierarchy"), "systems"),
            (("tool", "tools", "automation"), "tools"),
            (("growth", "scale", "scalable", "adoption", "quantify", "metric", "production readiness"), "growth"),
            (("workflow", "workflows", "process", "timeline", "session", "sessions", "step", "transition"), "timeline"),
            (("secure", "quality", "review", "reliability", "guardrail"), "security"),
            (("developer", "team", "manager", "employee", "stakeholder"), "customer"),
            (("finance", "cost", "revenue", "margin", "value"), "finance"),
            (("strategy", "architecture", "specification", "criteria", "discipline"), "strategy"),
            (("status", "progress", "cadence", "operating"), "status"),
            (("risk", "failure", "rot"), "risk"),
        ]
        self.layout_fallbacks = [
            "cover",
            "icon_grid",
            "two_column",
            "quote_sidebar",
            "dependency_map",
            "checklist",
            "callouts",
            "framework_cycle",
            "comparison_table",
            "code_panel",
            "anti_patterns",
            "table_reference",
            "matrix_2x2",
            "closing_recommendation",
            "icon_rows",
            "process",
            "chart",
            "executive_summary",
            "section_divider",
        ]

    def apply_design(self, outlines: list[SlideOutline]) -> list[SlideOutline]:
        if len(outlines) < 6:
            return self._diversify_layout_sequence(
                [self._apply_one(outline) for outline in outlines]
            )
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            return self._diversify_layout_sequence(list(executor.map(self._apply_one, outlines)))

    def apply_editing_contract(self, outlines: list[SlideOutline]) -> list[SlideOutline]:
        """Remap monotonous card-heavy plans before rendering.

        Claude's PPTX editing guidance treats layout mapping as an authoring
        step, not a post-hoc decoration pass. This pass keeps the planner's
        content but swaps excess card/bullet slides into semantically compatible
        layouts so the deck has a real visual rhythm before it reaches QA.
        """
        revised = [outline.model_copy(deep=True) for outline in outlines]
        for outline in revised:
            self._repair_concatenated_multi_item_blocks(outline)
            self._repair_unicode_bullets(outline)
        flexible = [outline for outline in revised if outline.mode == "flexible"]
        if len(flexible) < 5:
            return self._diversify_layout_sequence(revised)

        max_card_slides = max(1, int(len(flexible) * 0.58))
        current_card_count = self._card_layout_count(flexible)
        seen_counts: dict[str, int] = {}
        last_layout: str | None = None
        for outline in flexible:
            layout = str(outline.layout_json.get("layout") or "two_column")
            should_promote = (
                self._is_card_layout(layout)
                and current_card_count > max_card_slides
            ) or (last_layout == layout and layout not in {"cover", "section_divider"})
            if should_promote:
                replacement = self._editing_contract_layout(
                    outline,
                    last_layout,
                    seen_counts,
                )
                if replacement != layout:
                    self._set_layout_for_contract(outline, replacement, previous=layout)
                    if self._is_card_layout(layout):
                        current_card_count -= 1
                    layout = replacement
            seen_counts[layout] = seen_counts.get(layout, 0) + 1
            last_layout = layout
        return self._diversify_layout_sequence(revised)

    def _repair_unicode_bullets(self, outline: SlideOutline) -> None:
        count = 0
        blocks = outline.content_json.get("content_blocks")
        if isinstance(blocks, list):
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                body = block.get("body")
                repaired, delta = self._sanitize_item_body(body)
                if delta:
                    block["body"] = repaired
                    count += delta
        bullets = outline.content_json.get("bullets")
        if isinstance(bullets, list):
            repaired_bullets, delta = self._sanitize_item_list(bullets)
            if delta:
                outline.content_json["bullets"] = repaired_bullets
                count += delta
        exhibit = outline.content_json.get("exhibit_spec")
        if isinstance(exhibit, dict):
            repaired_exhibit, delta = self._sanitize_unicode_bullets_in_value(exhibit)
            if delta and isinstance(repaired_exhibit, dict):
                outline.content_json["exhibit_spec"] = repaired_exhibit
                count += delta
        if count:
            self._mark_editing_contract_repair(
                outline,
                "unicode_bullet_sanitized_count",
                count,
            )

    def _repair_concatenated_multi_item_blocks(self, outline: SlideOutline) -> None:
        blocks = outline.content_json.get("content_blocks")
        if not isinstance(blocks, list):
            return
        changed = False
        for block in blocks:
            if not isinstance(block, dict):
                continue
            body = block.get("body")
            if isinstance(body, str):
                split = self._split_concatenated_multi_item_text(body)
                if split:
                    block["body"] = split
                    changed = True
            elif isinstance(body, list):
                repaired: list[Any] = []
                block_changed = False
                for item in body:
                    if isinstance(item, str):
                        split = self._split_concatenated_multi_item_text(item)
                        if split:
                            repaired.extend(split)
                            changed = True
                            block_changed = True
                            continue
                    repaired.append(item)
                if block_changed:
                    block["body"] = repaired
        if not changed:
            return
        self._mark_editing_contract_repair(outline, "multi_item_split", True)

    def _mark_editing_contract_repair(
        self,
        outline: SlideOutline,
        key: str,
        value: Any,
    ) -> None:
        repair = outline.layout_json.get("editing_contract_repair")
        if not isinstance(repair, dict):
            repair = {}
            outline.layout_json["editing_contract_repair"] = repair
        repair["applied"] = True
        repair[key] = value

    def _sanitize_item_body(self, value: Any) -> tuple[Any, int]:
        if isinstance(value, str):
            split = self._split_unicode_bullet_lines(value)
            if split:
                return split, len(split)
            cleaned = self._strip_unicode_bullet_prefix(value)
            return cleaned, int(cleaned != value)
        if isinstance(value, list):
            return self._sanitize_item_list(value)
        return value, 0

    def _sanitize_item_list(self, values: list[Any]) -> tuple[list[Any], int]:
        repaired: list[Any] = []
        count = 0
        for item in values:
            if isinstance(item, str):
                split = self._split_unicode_bullet_lines(item)
                if split:
                    repaired.extend(split)
                    count += len(split)
                    continue
                cleaned = self._strip_unicode_bullet_prefix(item)
                if cleaned != item:
                    count += 1
                repaired.append(cleaned)
                continue
            fixed, delta = self._sanitize_unicode_bullets_in_value(item)
            repaired.append(fixed)
            count += delta
        return repaired, count

    def _sanitize_unicode_bullets_in_value(self, value: Any) -> tuple[Any, int]:
        if isinstance(value, str):
            cleaned = self._strip_unicode_bullet_prefixes_by_line(value)
            return cleaned, int(cleaned != value)
        if isinstance(value, list):
            repaired: list[Any] = []
            count = 0
            for item in value:
                fixed, delta = self._sanitize_unicode_bullets_in_value(item)
                repaired.append(fixed)
                count += delta
            return repaired, count
        if isinstance(value, dict):
            repaired: dict[str, Any] = {}
            count = 0
            for key, item in value.items():
                fixed, delta = self._sanitize_unicode_bullets_in_value(item)
                repaired[key] = fixed
                count += delta
            return repaired, count
        return value, 0

    def _split_unicode_bullet_lines(self, text: str) -> list[str] | None:
        lines = [line.strip() for line in str(text).splitlines() if line.strip()]
        bullet_lines = [
            self._strip_unicode_bullet_prefix(line)
            for line in lines
            if UNICODE_BULLET_PREFIX_RE.search(line)
        ]
        if len(bullet_lines) >= 2 and len(bullet_lines) == len(lines):
            return [line for line in bullet_lines if line]
        return None

    def _strip_unicode_bullet_prefixes_by_line(self, text: str) -> str:
        lines = str(text).splitlines()
        if len(lines) <= 1:
            return self._strip_unicode_bullet_prefix(text)
        return "\n".join(self._strip_unicode_bullet_prefix(line) for line in lines)

    def _strip_unicode_bullet_prefix(self, text: str) -> str:
        return UNICODE_BULLET_PREFIX_RE.sub("", str(text)).strip()

    def _split_concatenated_multi_item_text(self, text: str) -> list[str] | None:
        cleaned = " ".join(str(text).replace("\n", " ").split())
        if not cleaned:
            return None
        marker_re = re.compile(
            r"(?<!\w)(?:Step|Phase|Stage)\s+\d+\s*[:.)-]?|\b\d{1,2}[.)](?=\s+[A-Z])",
            re.IGNORECASE,
        )
        matches = list(marker_re.finditer(cleaned))
        if len(matches) < 2:
            return None
        prefix = cleaned[: matches[0].start()].strip(" ;")
        items: list[str] = []
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(cleaned)
            segment = cleaned[match.start() : end].strip(" ;")
            if prefix and index == 0:
                segment = f"{prefix} {segment}".strip()
            if segment:
                items.append(segment)
        return items if len(items) >= 2 else None

    def revise_for_qa(
        self, outline: SlideOutline, issues: list[QAIssue] | None = None
    ) -> SlideOutline:
        if outline.mode != "flexible":
            return outline
        revised = outline.model_copy(deep=True)
        issue_text = self._issue_text(issues)
        current = revised.layout_json.get("layout", "icon_rows")
        if self._needs_content_condensing(issue_text):
            self._condense_content(revised)
        self._repair_exhibit_spec(revised, issue_text)
        if self._needs_more_visual_structure(issue_text):
            revised.layout_json["layout"] = self._best_visual_layout(revised, current)
        elif self._needs_layout_change(issue_text):
            revised.layout_json["layout"] = self._next_layout(current, revised)
        else:
            revised.layout_json["layout"] = self._normalize_layout(current, revised)
        revised.layout_json["icons"] = self._select_icons(revised)
        revised.layout_json["visual_elements"] = self._visuals_for_layout(
            revised.layout_json["layout"]
        )
        revised.layout_json["qa_repair"] = {
            "applied": True,
            "issue_categories": sorted(
                {
                    str(issue.category)
                    for issue in issues or []
                    if getattr(issue, "category", None)
                }
            ),
        }
        return revised

    def revise_deck_for_qa(
        self, outlines: list[SlideOutline], issues: list[QAIssue]
    ) -> list[SlideOutline]:
        issues_by_slide: dict[int, list[QAIssue]] = {}
        has_deck_layout_issue = False
        for issue in issues:
            if not self.is_actionable_qa_issue(issue):
                continue
            if issue.slide_index is None:
                if self._needs_layout_change(self._issue_text([issue])):
                    has_deck_layout_issue = True
                continue
            issues_by_slide.setdefault(issue.slide_index, []).append(issue)
        updated: list[SlideOutline] = []
        last_layout: str | None = None
        for outline in outlines:
            slide_issues = issues_by_slide.get(outline.slide_index, [])
            revised = (
                self.revise_for_qa(outline, slide_issues)
                if slide_issues
                else outline.model_copy(deep=True)
            )
            if (
                has_deck_layout_issue
                and revised.mode == "flexible"
                and last_layout == revised.layout_json.get("layout")
            ):
                revised.layout_json["layout"] = self._next_layout(last_layout, revised)
                revised.layout_json["visual_elements"] = self._visuals_for_layout(
                    revised.layout_json["layout"]
                )
                revised.layout_json.setdefault("qa_repair", {"applied": True})
                revised.layout_json["qa_repair"]["layout_variety"] = True
            if revised.mode == "flexible":
                last_layout = revised.layout_json.get("layout")
            updated.append(revised)
        return self._diversify_layout_sequence(updated)

    def is_actionable_qa_issue(self, issue: QAIssue) -> bool:
        text = self._issue_text([issue])
        ignored = {
            "render_unavailable",
            "render_fallback",
            "preview_unavailable",
            "source_placeholder",
            "source_coverage",
            "qa_parse",
            "qa_schema",
        }
        if issue.category in ignored:
            return False
        if "approximate preview finding" in text:
            return False
        return any(
            token in text
            for token in (
                "critical",
                "text_wall",
                "text-wall",
                "text wall",
                "overflow",
                "cut-off",
                "cut_off",
                "overlap",
                "spacing",
                "contrast",
                "layout",
                "repetition",
                "repeated",
                "missing_visual",
                "missing visuals",
                "scanability",
                "content_quality",
                "incomplete_content",
                "placeholder_text",
                "raw_artifact",
                "semantic_visual_fit",
                "diagram_semantic_fit",
                "rendered_slide_audit",
                "missing_exhibit",
                "exhibit",
                "narrative_rhythm",
                "visual_rhythm",
                "archetype",
                "bullet_card_usage",
            )
        )

    def _issue_text(self, issues: list[QAIssue] | None) -> str:
        parts: list[str] = []
        for issue in issues or []:
            parts.extend([issue.severity, issue.category or "", issue.message])
        return " ".join(parts).lower()

    def _needs_content_condensing(self, issue_text: str) -> bool:
        return any(
            token in issue_text
            for token in (
                "text_wall",
                "text-wall",
                "text wall",
                "overflow",
                "cut-off",
                "cut_off",
                "overlap",
                "spacing",
                "scanability",
                "content_quality",
                "incomplete_content",
                "placeholder_text",
                "raw_artifact",
                "semantic_visual_fit",
                "diagram_semantic_fit",
            )
        )

    def _needs_more_visual_structure(self, issue_text: str) -> bool:
        return any(
            token in issue_text
            for token in (
                "missing_visual",
                "missing visuals",
                "text_wall",
                "text-wall",
                "text wall",
                "content_quality",
                "missing_exhibit",
                "exhibit",
                "bullet_card_usage",
                "semantic_visual_fit",
                "diagram_semantic_fit",
            )
        )

    def _needs_layout_change(self, issue_text: str) -> bool:
        return any(
            token in issue_text
            for token in (
                "layout",
                "repetition",
                "repeated",
                "contrast",
                "spacing",
                "narrative_rhythm",
                "visual_rhythm",
                "archetype",
            )
        )

    def _best_visual_layout(self, outline: SlideOutline, current: str) -> str:
        content = outline.content_json
        if self._is_source_repair_slide(outline):
            return self._safe_source_repair_layout(outline, current)
        exhibit_layout = self._layout_from_exhibit(content.get("exhibit_spec"))
        if exhibit_layout and exhibit_layout != current:
            return exhibit_layout
        if content.get("metrics"):
            return "chart" if current != "chart" else "callouts"
        if self._has_table(content):
            return "process" if current != "process" else "icon_grid"
        bullets = self._content_bullets(content)
        if len(bullets) <= 3:
            return "callouts" if current != "callouts" else "icon_grid"
        return "icon_grid" if current != "icon_grid" else "two_column"

    def _layout_from_exhibit(self, exhibit_spec) -> str | None:
        if not isinstance(exhibit_spec, dict):
            return None
        exhibit_type = str(exhibit_spec.get("type") or "").lower().replace("-", "_")
        mapping = {
            "comparison_table": "comparison_table",
            "dependency_map": "dependency_map",
            "cycle": "framework_cycle",
            "process": "framework_cycle",
            "checklist": "checklist",
            "code_panel": "code_panel",
            "anti_patterns": "anti_patterns",
            "quote_sidebar": "quote_sidebar",
            "reference_table": "table_reference",
            "recommendation": "closing_recommendation",
            "metric_chart": "chart",
            "line_chart": "chart",
            "matrix_2x2": "matrix_2x2",
            "2x2": "matrix_2x2",
        }
        return mapping.get(exhibit_type)

    def _next_layout(self, current: str | None, outline: SlideOutline) -> str:
        preferred = self._normalize_layout(current or "icon_rows", outline)
        for layout in self.layout_fallbacks:
            if layout in {"cover", "executive_summary", "section_divider", "closing_recommendation"}:
                continue
            if layout != preferred and self._layout_is_suitable(layout, outline):
                return layout
        return "two_column"

    def _layout_is_suitable(self, layout: str, outline: SlideOutline) -> bool:
        if layout == "chart" and not outline.content_json.get("metrics"):
            return False
        if layout == "matrix_2x2":
            exhibit = outline.content_json.get("exhibit_spec")
            return isinstance(exhibit, dict) and exhibit.get("type") == "matrix_2x2"
        if layout == "process" and not self._has_table(outline.content_json):
            return bool(self._content_bullets(outline.content_json))
        if layout == "chart" and not outline.content_json.get("metrics"):
            return False
        return True

    def _is_card_layout(self, layout: str) -> bool:
        return layout in {"callouts", "icon_grid", "icon_rows", "two_column"}

    def _card_layout_count(self, outlines: list[SlideOutline]) -> int:
        return sum(
            1
            for outline in outlines
            if self._is_card_layout(str(outline.layout_json.get("layout") or ""))
        )

    def _editing_contract_layout(
        self,
        outline: SlideOutline,
        last_layout: str | None,
        seen_counts: dict[str, int],
    ) -> str:
        for layout in self._editing_contract_candidates(outline):
            if layout == last_layout:
                continue
            if seen_counts.get(layout, 0) >= self._layout_repeat_limit(layout):
                continue
            if self._layout_is_suitable(layout, outline):
                return layout
        for layout in self._editing_contract_candidates(outline):
            if layout != last_layout and self._layout_is_suitable(layout, outline):
                return layout
        return str(outline.layout_json.get("layout") or "two_column")

    def _editing_contract_candidates(self, outline: SlideOutline) -> list[str]:
        content = outline.content_json
        current = str(outline.layout_json.get("layout") or "two_column")
        exhibit = content.get("exhibit_spec")
        exhibit_type = str(exhibit.get("type") or "") if isinstance(exhibit, dict) else ""
        text = self._outline_text(outline)
        candidates: list[str] = []
        if current in {"cover", "executive_summary", "section_divider", "closing_recommendation"}:
            return [current]
        if self._is_source_repair_slide(outline):
            candidates.extend(["quote_sidebar", "checklist", "process"])
        if content.get("metrics"):
            candidates.append("chart")
        if exhibit_type == "comparison_table":
            candidates.extend(["comparison_table", "process"])
        if exhibit_type == "reference_table":
            candidates.extend(["table_reference", "comparison_table", "process"])
        if exhibit_type == "checklist" or "question" in text or "checklist" in text:
            candidates.extend(["checklist", "quote_sidebar"])
        if any(token in text for token in ("decision", "mental model", "why", "shift", "reframe")):
            candidates.append("quote_sidebar")
        if self._has_table(content):
            candidates.append("process")
        candidates.extend(["quote_sidebar", "checklist", "process", "comparison_table"])
        deduped: list[str] = []
        for candidate in candidates:
            if candidate in deduped:
                continue
            if self._is_card_layout(candidate):
                continue
            deduped.append(candidate)
        return deduped

    def _set_layout_for_contract(
        self,
        outline: SlideOutline,
        layout: str,
        previous: str,
    ) -> None:
        outline.layout_json["layout"] = layout
        outline.layout_json["archetype"] = self._archetype_for_layout(layout)
        outline.layout_json["visual_elements"] = self._visuals_for_layout(layout)
        outline.layout_json["icons"] = self._select_icons(outline)
        repair = outline.layout_json.get("editing_contract_repair")
        if not isinstance(repair, dict):
            repair = {}
            outline.layout_json["editing_contract_repair"] = repair
        repair["applied"] = True
        repair["from_layout"] = previous
        repair["to_layout"] = layout

    def _diversify_layout_sequence(self, outlines: list[SlideOutline]) -> list[SlideOutline]:
        diversified: list[SlideOutline] = []
        last_layout: str | None = None
        seen_counts: dict[str, int] = {}
        fallback_cycle = [
            "callouts",
            "icon_rows",
            "comparison_table",
            "checklist",
            "two_column",
            "icon_grid",
            "quote_sidebar",
            "anti_patterns",
            "matrix_2x2",
            "dependency_map",
            "framework_cycle",
            "code_panel",
            "table_reference",
        ]
        for index, outline in enumerate(outlines):
            if outline.mode != "flexible":
                diversified.append(outline)
                continue
            revised = outline.model_copy(deep=True)
            current = str(revised.layout_json.get("layout") or "two_column")
            if self._is_source_repair_slide(revised):
                intended = self._safe_source_repair_layout(revised, current)
                revised.layout_json["layout"] = intended
                revised.layout_json["archetype"] = self._archetype_for_layout(intended)
                revised.layout_json["visual_elements"] = self._visuals_for_layout(intended)
                revised.layout_json["icons"] = self._select_icons(revised)
                seen_counts[intended] = seen_counts.get(intended, 0) + 1
                last_layout = intended
                diversified.append(revised)
                continue
            intended = self._intent_layout(revised, index) or current
            if index > 0 and intended == "executive_summary" and current != "executive_summary":
                intended = current if current != "executive_summary" else "two_column"
            if (
                intended == last_layout
                or seen_counts.get(intended, 0) >= self._layout_repeat_limit(intended)
            ) and not self._should_preserve_repeated_exhibit_layout(
                intended,
                revised,
                last_layout,
                seen_counts,
            ):
                intended = self._next_diverse_layout(
                    fallback_cycle,
                    last_layout,
                    seen_counts,
                    revised,
                    preferred=intended,
                )
            revised.layout_json["layout"] = intended
            revised.layout_json["visual_elements"] = self._visuals_for_layout(intended)
            if intended != current:
                # Keep the archetype label consistent with the diversified layout
                # so downstream repetition checks see the same variety the deck
                # actually renders, instead of a stale archetype sequence.
                revised.layout_json["archetype"] = self._archetype_for_layout(intended)
                revised.layout_json.setdefault("qa_repair", {"applied": True})
                revised.layout_json["qa_repair"]["layout_variety"] = True
            revised.layout_json["icons"] = self._select_icons(revised)
            seen_counts[intended] = seen_counts.get(intended, 0) + 1
            last_layout = intended
            diversified.append(revised)
        return diversified

    def _should_preserve_repeated_exhibit_layout(
        self,
        layout: str,
        outline: SlideOutline,
        last_layout: str | None,
        seen_counts: dict[str, int],
    ) -> bool:
        if layout == last_layout:
            return False
        text = self._outline_text(outline)
        exhibit = outline.content_json.get("exhibit_spec")
        exhibit_type = str(exhibit.get("type") or "") if isinstance(exhibit, dict) else ""
        if layout == "dependency_map":
            return (
                seen_counts.get(layout, 0) < 2
                and exhibit_type == "dependency_map"
                and any(
                    token in text
                    for token in (
                        "directed dependency graph",
                        "dependency graph",
                        "file hierarchy",
                        "relationship map",
                    )
                )
            )
        if layout == "table_reference":
            return (
                seen_counts.get(layout, 0) < 2
                and exhibit_type == "reference_table"
                and any(
                    token in text
                    for token in (
                        "six core files",
                        "core files",
                        "rules files",
                        "specification files",
                    )
                )
            )
        if layout == "framework_cycle":
            return (
                seen_counts.get(layout, 0) < 2
                and exhibit_type == "cycle"
                and any(
                    token in text
                    for token in (
                        "six-phase loop",
                        "six phase loop",
                        "agentic cycle",
                        "operating loop",
                    )
                )
            )
        return False

    def _archetype_for_layout(self, layout: str) -> str:
        return {
            "chart": "metric_chart",
            "process": "table_reference",
            "icon_grid": "callouts",
        }.get(layout, layout)

    def _next_diverse_layout(
        self,
        fallback_cycle: list[str],
        last_layout: str | None,
        seen_counts: dict[str, int],
        outline: SlideOutline,
        preferred: str | None = None,
    ) -> str:
        semantic_fallbacks = self._semantic_layout_fallbacks(preferred)
        for layout in [*semantic_fallbacks, *fallback_cycle]:
            if layout in {"cover", "executive_summary", "section_divider"}:
                continue
            if layout == last_layout:
                continue
            if seen_counts.get(layout, 0) >= self._layout_repeat_limit(layout):
                continue
            if self._layout_is_suitable(layout, outline):
                return layout
        for layout in fallback_cycle:
            if layout in {"cover", "executive_summary", "section_divider"}:
                continue
            if layout != last_layout and self._layout_is_suitable(layout, outline):
                return layout
        return "two_column"

    def _semantic_layout_fallbacks(self, preferred: str | None) -> list[str]:
        if preferred == "framework_cycle":
            return ["checklist", "icon_rows", "two_column"]
        if preferred == "dependency_map":
            return ["table_reference", "comparison_table", "icon_rows"]
        if preferred == "table_reference":
            return ["code_panel", "comparison_table", "two_column"]
        if preferred == "anti_patterns":
            return ["icon_rows", "comparison_table", "two_column"]
        if preferred == "comparison_table":
            return ["process", "callouts", "icon_rows", "two_column"]
        return []

    def _layout_repeat_limit(self, layout: str) -> int:
        if layout in {
            "cover",
            "executive_summary",
            "section_divider",
            "closing_recommendation",
        }:
            return 99
        if layout in {
            "anti_patterns",
            "chart",
            "dependency_map",
            "framework_cycle",
            "code_panel",
            "table_reference",
            "comparison_table",
            "matrix_2x2",
            "quote_sidebar",
        }:
            return 1
        return 2

    def _intent_layout(self, outline: SlideOutline, index: int) -> str | None:
        current = str(outline.layout_json.get("layout") or "")
        if self._is_source_repair_slide(outline):
            return self._safe_source_repair_layout(outline, current)
        explicit = self._explicit_archetype_layout(outline)
        if explicit:
            return explicit
        if index == 0 and current == "cover":
            return "cover"
        if index == 0 and current == "executive_summary":
            return "executive_summary"
        if current == "chart" and outline.content_json.get("metrics"):
            return "chart"
        if current == "process" and self._has_table(outline.content_json):
            return "process"
        text = self._outline_text(outline)
        if any(token in text for token in ("failure mode", "failure modes", "anti-pattern", "anti pattern", "stop doing")):
            return "anti_patterns"
        if any(token in text for token in ("external brain", "memory bank", "persistent context", "dependency graph")):
            return "dependency_map"
        if any(token in text for token in ("developer role", "product manager", "product-manager", "ai manager", "managed team member", "employee management", "mental model")):
            return "quote_sidebar"
        if any(token in text for token in ("rules file", "rules files", "markdown", "github", "codebase")):
            return "code_panel"
        if any(token in text for token in ("checklist", "critical steps", "execute the transition", "adopt it tomorrow")):
            return "checklist"
        if any(token in text for token in ("cycle", "workflow", "workflows", "operating model")):
            return "framework_cycle"
        return None

    def _explicit_archetype_layout(self, outline: SlideOutline) -> str | None:
        archetype = str(
            outline.layout_json.get("archetype")
            or outline.content_json.get("archetype")
            or ""
        )
        normalized = archetype.strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "cycle": "framework_cycle",
            "process": "framework_cycle",
            "comparison": "comparison_table",
            "reference": "code_panel",
            "reference_table": "table_reference",
            "chart": "chart",
            "metric_chart": "chart",
            "anti_pattern": "anti_patterns",
            "quote": "quote_sidebar",
            "closing": "closing_recommendation",
            "recommendation": "closing_recommendation",
        }
        layout = aliases.get(normalized, normalized)
        if layout in self.layout_fallbacks:
            return layout
        return None

    def _outline_text(self, outline: SlideOutline) -> str:
        content = outline.content_json
        parts = [
            str(content.get("title") or ""),
            str(content.get("action_title") or ""),
            str(content.get("summary") or ""),
            str(content.get("subheading") or ""),
        ]
        parts.extend(self._content_bullets(content))
        return " ".join(parts).lower()

    def _condense_content(self, outline: SlideOutline) -> None:
        content = outline.content_json
        for key, limit in [("summary", 130), ("subheading", 130)]:
            if isinstance(content.get(key), str):
                content[key] = self._truncate_text(content[key], limit)
        if isinstance(content.get("bullets"), list):
            content["bullets"] = [
                self._truncate_text(str(item), 145)
                for item in content["bullets"][:4]
                if str(item).strip()
            ]
        blocks = content.get("content_blocks")
        if not isinstance(blocks, list):
            return
        for block in blocks:
            if not isinstance(block, dict):
                continue
            body = block.get("body")
            if not isinstance(body, list):
                continue
            if block.get("type") == "table":
                block["body"] = self._condense_table(body)
            else:
                block["body"] = [
                    self._condense_value(item)
                    for item in body[:4]
                    if str(item).strip()
                ]

    def _repair_exhibit_spec(self, outline: SlideOutline, issue_text: str) -> None:
        if outline.mode != "flexible":
            return
        content = outline.content_json
        exhibit = content.get("exhibit_spec")
        if not isinstance(exhibit, dict):
            if not self._needs_more_visual_structure(issue_text):
                return
            bullets = self._content_bullets(content)[:4]
            content["exhibit_spec"] = {
                "type": "checklist",
                "items": self._ensure_min_items(
                    [
                    {"action": self._truncate_text(bullet, 92), "owner": "Lead", "timing": "Review gate"}
                    for bullet in bullets
                    ],
                    [
                        {"action": "Confirm source context", "owner": "Lead", "timing": "Review gate"},
                        {"action": "Define review gate", "owner": "Manager", "timing": "Pilot"},
                        {"action": "Run pilot workflow", "owner": "Team", "timing": "Pilot"},
                    ],
                    min_count=3,
                ),
            }
            content["archetype"] = "checklist"
            outline.layout_json["archetype"] = "checklist"
            outline.layout_json["exhibit_type"] = "checklist"
            return
        content["exhibit_spec"] = self._condense_exhibit(exhibit)
        content["exhibit_repair_applied"] = True

    def _condense_exhibit(self, value):
        if isinstance(value, str):
            return self._truncate_text(value, 96)
        if isinstance(value, list):
            return [self._condense_exhibit(item) for item in value[:6]]
        if isinstance(value, dict):
            condensed = {
                key: self._condense_exhibit(item)
                for key, item in value.items()
                if not self._is_placeholder_text(item)
            }
            exhibit_type = str(condensed.get("type") or "")
            if exhibit_type == "anti_patterns":
                condensed["patterns"] = self._ensure_min_items(
                    condensed.get("patterns"),
                    [
                        {"name": "Context rot", "symptom": "Memory disappears", "better_behavior": "Persist context"},
                        {"name": "Thin review", "symptom": "Outputs pass too quickly", "better_behavior": "Use QA gates"},
                    ],
                )
            if exhibit_type == "checklist":
                condensed["items"] = self._ensure_min_items(
                    condensed.get("items"),
                    [
                        {"action": "Confirm source context", "owner": "Lead", "timing": "Review gate"},
                        {"action": "Define review gate", "owner": "Manager", "timing": "Pilot"},
                        {"action": "Run pilot workflow", "owner": "Team", "timing": "Pilot"},
                    ],
                    min_count=3,
                )
            if exhibit_type == "cycle":
                condensed["steps"] = self._ensure_min_items(
                    condensed.get("steps"),
                    [
                        {"label": "Define scope", "description": "Define the ask"},
                        {"label": "Load evidence", "description": "Load context"},
                        {"label": "Check evidence", "description": "Check against evidence"},
                    ],
                    min_count=3,
                )
            if exhibit_type == "dependency_map":
                condensed["middle_nodes"] = self._ensure_min_items(
                    condensed.get("middle_nodes"),
                    ["Source evidence", "Operating constraints", "Review standard"],
                    min_count=2,
                )
            return condensed
        return value

    def _ensure_min_items(self, items, fallback: list, min_count: int = 2) -> list:
        if isinstance(items, list) and len(items) >= min_count:
            return items
        return fallback

    def _is_placeholder_text(self, value) -> bool:
        if isinstance(value, str):
            normalized = value.lower()
            return "diagram description" in normalized or "placeholder" in normalized
        return False

    def _condense_table(self, rows: list[Any]) -> list[Any]:
        condensed: list[Any] = []
        for row in rows[:6]:
            if isinstance(row, list):
                condensed.append(
                    [self._truncate_text(str(cell), 52) for cell in row[:4]]
                )
            else:
                condensed.append(self._truncate_text(str(row), 120))
        return condensed

    def _condense_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._truncate_text(value, 145)
        if isinstance(value, list):
            return [self._truncate_text(str(item), 52) for item in value[:4]]
        return value

    def _truncate_text(self, text: str, limit: int) -> str:
        cleaned = " ".join(text.split())
        if len(cleaned) <= limit:
            return cleaned
        source_marker = " [source needed]" if "[source needed]" in cleaned.lower() else ""
        working_limit = limit - len(source_marker)
        cleaned = cleaned.replace("[source needed]", "").strip()
        truncated = cleaned[: max(20, working_limit)].rsplit(" ", 1)[0].rstrip(".,;:")
        trailing = {"a", "an", "and", "as", "by", "for", "from", "in", "into", "of", "or", "the", "their", "through", "to", "with"}
        words = truncated.split()
        while words and words[-1].lower() in trailing:
            words.pop()
        truncated = " ".join(words).strip(".,;:")
        return f"{truncated}{source_marker}"

    def _content_bullets(self, content: dict[str, Any]) -> list[str]:
        bullets = content.get("bullets")
        if isinstance(bullets, list) and bullets:
            return [str(item) for item in bullets if str(item).strip()]
        collected: list[str] = []
        blocks = content.get("content_blocks")
        if isinstance(blocks, list):
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                for item in block.get("body", []):
                    if isinstance(item, str):
                        collected.append(item)
        return collected

    def _has_table(self, content: dict[str, Any]) -> bool:
        blocks = content.get("content_blocks")
        return isinstance(blocks, list) and any(
            isinstance(block, dict) and block.get("type") == "table" for block in blocks
        )

    def _apply_one(self, outline: SlideOutline) -> SlideOutline:
        if outline.mode != "flexible":
            return outline
        layout = outline.layout_json.get("layout", "icon_rows")
        outline.layout_json["layout"] = self._normalize_layout(layout, outline)
        self._repair_underfilled_exhibit(outline)
        outline.layout_json.setdefault("icons", self._select_icons(outline))
        outline.layout_json["visual_elements"] = outline.layout_json.get(
            "visual_elements"
        ) or self._visuals_for_layout(outline.layout_json["layout"])
        return outline

    def _repair_underfilled_exhibit(self, outline: SlideOutline) -> None:
        exhibit = outline.content_json.get("exhibit_spec")
        if not isinstance(exhibit, dict):
            return
        exhibit_type = str(exhibit.get("type") or "").lower().replace("-", "_")
        if exhibit_type == "checklist":
            items = self._normalized_checklist_items(exhibit.get("items"))
            repaired = self._extend_min_items(
                items,
                self._checklist_fallback_items(outline),
                min_count=3,
            )
            if repaired != exhibit.get("items"):
                exhibit["items"] = repaired
                self._sync_checklist_content_block(outline, repaired)
                self._mark_editing_contract_repair(
                    outline,
                    "underfilled_checklist_repaired",
                    True,
                )
        elif exhibit_type == "icon_rows":
            items = self._normalized_text_items(exhibit.get("items"))
            repaired = self._extend_min_items(
                items,
                self._icon_row_fallback_items(outline),
                min_count=3,
            )
            if repaired != exhibit.get("items"):
                exhibit["items"] = repaired
                self._mark_editing_contract_repair(
                    outline,
                    "underfilled_icon_rows_repaired",
                    True,
                )
        elif exhibit_type == "callouts":
            items = self._normalized_text_items(exhibit.get("points"))
            repaired = self._extend_min_items(
                items,
                self._callout_fallback_items(outline),
                min_count=3,
            )
            if repaired != exhibit.get("points"):
                exhibit["points"] = repaired
                self._mark_editing_contract_repair(
                    outline,
                    "underfilled_callouts_repaired",
                    True,
                )

    def _normalized_checklist_items(self, value: Any) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        if not isinstance(value, list):
            return items
        for index, item in enumerate(value):
            if isinstance(item, dict):
                action = str(
                    item.get("action") or item.get("text") or item.get("label") or ""
                ).strip()
                if not action:
                    continue
                items.append(
                    {
                        "action": self._truncate_text(action, 118),
                        "owner": str(
                            item.get("owner") or self._fallback_owner(index)
                        ).strip(),
                        "timing": str(
                            item.get("timing") or self._fallback_timing(index)
                        ).strip(),
                    }
                )
            elif str(item).strip():
                items.append(
                    {
                        "action": self._truncate_text(str(item), 118),
                        "owner": self._fallback_owner(index),
                        "timing": self._fallback_timing(index),
                    }
                )
        return items

    def _normalized_text_items(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        items: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = str(
                    item.get("text") or item.get("label") or item.get("action") or ""
                ).strip()
            else:
                text = str(item).strip()
            if text:
                items.append(self._truncate_text(text, 118))
        return items

    def _checklist_fallback_items(self, outline: SlideOutline) -> list[dict[str, str]]:
        source_items = self._content_bullets(outline.content_json)
        fallbacks = [
            "Name the evidence pattern before reuse",
            "Attach source context to each benchmark run",
            "Set the review gate before scaling",
            "Refresh the benchmark when evidence changes",
        ]
        actions = [
            self._truncate_text(item, 118)
            for item in [*source_items, *fallbacks]
            if str(item).strip()
        ]
        deduped: list[str] = []
        seen: set[str] = set()
        for action in actions:
            key = action.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(action)
        return [
            {
                "action": action,
                "owner": self._fallback_owner(index),
                "timing": self._fallback_timing(index),
            }
            for index, action in enumerate(deduped)
        ]

    def _icon_row_fallback_items(self, outline: SlideOutline) -> list[str]:
        fallbacks = [
            "Name the evidence pattern before reuse",
            "Attach source context to each benchmark run",
            "Set the review gate before scaling",
            "Refresh the benchmark when evidence changes",
        ]
        return [
            self._truncate_text(item, 118)
            for item in [*self._content_bullets(outline.content_json), *fallbacks]
            if str(item).strip()
        ]

    def _callout_fallback_items(self, outline: SlideOutline) -> list[str]:
        context = " ".join(
            [
                str(outline.content_json.get("action_title") or outline.label),
                str(outline.content_json.get("subheading") or ""),
                " ".join(str(source) for source in outline.content_json.get("sources", [])),
            ]
        ).lower()
        if "executive summary" in context or "benchmark" in context:
            fallbacks = [
                "Public benchmarks are saturated and weakly tied to enterprise workflows.",
                "Existing documents and decisions can become benchmark evidence.",
                "Harness-centric discovery converts operating evidence into reusable tests.",
            ]
        else:
            fallbacks = [
                "Name the evidence signal before scaling.",
                "Connect the source context to the decision.",
                "Make the review rule explicit.",
            ]
        return [
            self._truncate_text(item, 118)
            for item in [*self._content_bullets(outline.content_json), *fallbacks]
            if str(item).strip()
        ]

    def _extend_min_items(
        self, items: list[Any], fallback: list[Any], min_count: int
    ) -> list[Any]:
        if len(items) >= min_count:
            return items
        merged: list[Any] = []
        seen: set[str] = set()
        for item in [*items, *fallback]:
            key = self._item_identity(item)
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= min_count:
                break
        return merged

    def _item_identity(self, item: Any) -> str:
        if isinstance(item, dict):
            return " ".join(
                str(item.get(key) or "")
                for key in ("action", "text", "label", "title", "description")
            ).strip().casefold()
        return str(item).strip().casefold()

    def _fallback_owner(self, index: int) -> str:
        return ["Strategy", "Data", "Review", "Operations"][index % 4]

    def _fallback_timing(self, index: int) -> str:
        return ["Design", "Build", "Pilot", "Scale"][index % 4]

    def _sync_checklist_content_block(
        self, outline: SlideOutline, items: list[dict[str, str]]
    ) -> None:
        outline.content_json["content_blocks"] = [
            {
                "type": "table",
                "body": [
                    ["Action", "Owner", "Timing"],
                    *[
                        [
                            item.get("action", ""),
                            item.get("owner", ""),
                            item.get("timing", ""),
                        ]
                        for item in items
                    ],
                ],
            }
        ]

    def _normalize_layout(self, layout: str, outline: SlideOutline) -> str:
        if layout == "chart" and not outline.content_json.get("metrics"):
            return "callouts"
        if layout == "matrix_2x2":
            exhibit = outline.content_json.get("exhibit_spec")
            if not isinstance(exhibit, dict) or exhibit.get("type") != "matrix_2x2":
                return "comparison_table"
        if layout not in self.layout_fallbacks:
            return "icon_rows"
        return layout

    def _is_source_repair_slide(self, outline: SlideOutline) -> bool:
        return bool((outline.content_json or {}).get("visual_qa_source_repair"))

    def _safe_source_repair_layout(self, outline: SlideOutline, current: str | None) -> str:
        normalized = str(current or "").strip().lower().replace("-", "_")
        if normalized in {
            "callouts",
            "icon_rows",
            "icon_grid",
            "two_column",
            "checklist",
            "quote_sidebar",
            "process",
        }:
            return normalized
        bullets = self._content_bullets(outline.content_json)
        if "question" in self._outline_text(outline) or "checklist" in self._outline_text(outline):
            return "checklist"
        if len(bullets) <= 3:
            return "callouts"
        return "icon_rows"

    def _visuals_for_layout(self, layout: str) -> list[str]:
        if layout == "cover":
            return ["hero_typography", "section_marker"]
        if layout == "chart":
            return ["charts", "callouts"]
        if layout == "comparison_table":
            return ["tables", "comparison"]
        if layout == "callouts":
            return ["callouts"]
        if layout == "process":
            return ["tables"]
        if layout == "section_divider":
            return ["section_marker", "typography"]
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
        if layout == "executive_summary":
            return ["structured_text"]
        if layout == "table_reference":
            return ["tables", "reference"]
        if layout == "matrix_2x2":
            return ["matrix", "quadrants"]
        if layout == "closing_recommendation":
            return ["recommendation", "checklist"]
        return ["icons", "shapes"]

    def _select_icons(self, outline: SlideOutline) -> list[str]:
        content = outline.content_json
        title = str(content.get("title") or content.get("action_title") or "")
        summary = str(content.get("summary") or content.get("subheading") or "")
        bullets = self._content_bullets(content)
        text_units = bullets or [f"{title} {summary}"]
        # Rotate through neutral icons when text doesn't match a keyword, so
        # unmatched slides don't fill with repeated identical lightbulbs.
        neutral_cycle = ["systems", "docs", "standards", "status", "tools", "growth"]
        default_icon = self.icon_pool["default"]
        selected: list[str] = []
        fallback_index = 0
        for text in text_units:
            if not text.strip():
                continue
            icon = self._icon_for_text(text)
            if icon == default_icon:
                icon = self.icon_pool[neutral_cycle[fallback_index % len(neutral_cycle)]]
                fallback_index += 1
            selected.append(icon)
        if not selected:
            selected.append(self.icon_pool["systems"])
        while len(selected) < 4:
            selected.append(selected[-1])
        return selected[:4]

    def _icon_for_text(self, text: str) -> str:
        normalized = text.lower()
        for keywords, icon_key in self.keyword_icon_map:
            if any(self._contains_keyword(normalized, keyword) for keyword in keywords):
                return self.icon_pool[icon_key]
        return self.icon_pool["default"]

    def _contains_keyword(self, normalized_text: str, keyword: str) -> bool:
        if " " in keyword:
            return keyword in normalized_text
        return bool(re.search(rf"\b{re.escape(keyword)}\b", normalized_text))
