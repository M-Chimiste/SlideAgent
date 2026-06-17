import concurrent.futures
import re
from typing import Any

from app.models.outline import SlideOutline
from app.models.qa import QAIssue


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
            "icon_grid",
            "two_column",
            "quote_sidebar",
            "dependency_map",
            "checklist",
            "callouts",
            "framework_cycle",
            "code_panel",
            "anti_patterns",
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
            )
        )

    def _needs_layout_change(self, issue_text: str) -> bool:
        return any(
            token in issue_text
            for token in ("layout", "repetition", "repeated", "contrast", "spacing")
        )

    def _best_visual_layout(self, outline: SlideOutline, current: str) -> str:
        content = outline.content_json
        if content.get("metrics"):
            return "chart" if current != "chart" else "callouts"
        if self._has_table(content):
            return "process" if current != "process" else "icon_grid"
        bullets = self._content_bullets(content)
        if len(bullets) <= 3:
            return "callouts" if current != "callouts" else "icon_grid"
        return "icon_grid" if current != "icon_grid" else "two_column"

    def _next_layout(self, current: str | None, outline: SlideOutline) -> str:
        preferred = self._normalize_layout(current or "icon_rows", outline)
        for layout in self.layout_fallbacks:
            if layout != preferred and self._layout_is_suitable(layout, outline):
                return layout
        return self.layout_fallbacks[0]

    def _layout_is_suitable(self, layout: str, outline: SlideOutline) -> bool:
        if layout == "chart" and not outline.content_json.get("metrics"):
            return False
        if layout == "process" and not self._has_table(outline.content_json):
            return bool(self._content_bullets(outline.content_json))
        if layout == "chart" and not outline.content_json.get("metrics"):
            return False
        return True

    def _diversify_layout_sequence(self, outlines: list[SlideOutline]) -> list[SlideOutline]:
        diversified: list[SlideOutline] = []
        last_layout: str | None = None
        seen_counts: dict[str, int] = {}
        fallback_cycle = [
            "anti_patterns",
            "quote_sidebar",
            "dependency_map",
            "framework_cycle",
            "code_panel",
            "checklist",
            "callouts",
            "icon_grid",
            "two_column",
        ]
        for index, outline in enumerate(outlines):
            if outline.mode != "flexible":
                diversified.append(outline)
                continue
            revised = outline.model_copy(deep=True)
            current = str(revised.layout_json.get("layout") or "two_column")
            intended = self._intent_layout(revised, index) or current
            if index > 0 and intended in {"executive_summary", "section_divider"}:
                intended = current if current not in {"executive_summary", "section_divider"} else "two_column"
            if (
                intended == last_layout
                or seen_counts.get(intended, 0) >= 2
                and intended in {"two_column", "icon_grid", "icon_rows", "executive_summary"}
            ):
                intended = self._next_diverse_layout(
                    fallback_cycle,
                    last_layout,
                    seen_counts,
                    revised,
                )
            revised.layout_json["layout"] = intended
            revised.layout_json["visual_elements"] = self._visuals_for_layout(intended)
            if intended != current:
                revised.layout_json.setdefault("qa_repair", {"applied": True})
                revised.layout_json["qa_repair"]["layout_variety"] = True
            revised.layout_json["icons"] = self._select_icons(revised)
            seen_counts[intended] = seen_counts.get(intended, 0) + 1
            last_layout = intended
            diversified.append(revised)
        return diversified

    def _next_diverse_layout(
        self,
        fallback_cycle: list[str],
        last_layout: str | None,
        seen_counts: dict[str, int],
        outline: SlideOutline,
    ) -> str:
        for layout in fallback_cycle:
            if layout == last_layout:
                continue
            if seen_counts.get(layout, 0) >= 2:
                continue
            if self._layout_is_suitable(layout, outline):
                return layout
        for layout in fallback_cycle:
            if layout != last_layout and self._layout_is_suitable(layout, outline):
                return layout
        return "two_column"

    def _intent_layout(self, outline: SlideOutline, index: int) -> str | None:
        current = str(outline.layout_json.get("layout") or "")
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
        truncated = cleaned[: max(20, working_limit - 3)].rsplit(" ", 1)[0].rstrip(".,;:")
        return f"{truncated}...{source_marker}"

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
        outline.layout_json.setdefault("icons", self._select_icons(outline))
        outline.layout_json["visual_elements"] = outline.layout_json.get(
            "visual_elements"
        ) or self._visuals_for_layout(outline.layout_json["layout"])
        return outline

    def _normalize_layout(self, layout: str, outline: SlideOutline) -> str:
        if layout == "chart" and not outline.content_json.get("metrics"):
            return "callouts"
        if layout not in self.layout_fallbacks:
            return "icon_rows"
        return layout

    def _visuals_for_layout(self, layout: str) -> list[str]:
        if layout == "chart":
            return ["charts", "callouts"]
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
        return ["icons", "shapes"]

    def _select_icons(self, outline: SlideOutline) -> list[str]:
        content = outline.content_json
        title = str(content.get("title") or content.get("action_title") or "")
        summary = str(content.get("summary") or content.get("subheading") or "")
        bullets = self._content_bullets(content)
        text_units = bullets or [f"{title} {summary}"]
        selected = [self._icon_for_text(text) for text in text_units if text.strip()]
        if not selected:
            selected.append(self.icon_pool["default"])
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
