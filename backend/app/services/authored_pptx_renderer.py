from pathlib import Path
import re
from typing import Any

from app.models.brand import BrandDNA
from app.models.outline import SlideOutline
from app.services.pptx_renderer import DeterministicPptxRenderer


class AuthoredPptxRenderer:
    """Content-aware renderer facade for generated decks.

    The first authored pass preserves editable PPTX text and the proven native
    drawing layer, but moves layout selection into an explicit composition
    stage. Complex diagram assets are only allowed when the plan carries a
    source-specific diagram spec; weak diagram requests degrade to safer
    editorial/card compositions.
    """

    def __init__(self, legacy_renderer: DeterministicPptxRenderer | None = None) -> None:
        self.legacy_renderer = legacy_renderer or DeterministicPptxRenderer()
        self.card_like_families = {
            "challenge_cards",
            "evidence_wall",
            "proof_strip",
            "source_repair_cards",
            "toolkit_grid",
            "why_it_matters_cards",
        }
        self.fixed_rhythm_families = {
            "editorial_cover",
            "path_forward_close",
            "section_divider",
            "source_backed_diagram",
            "decision_matrix",
        }

    def render(
        self,
        outlines: list[SlideOutline],
        brand: BrandDNA,
        output_path: Path,
        enable_diagrams: bool = True,
    ) -> list[dict[str, str | int]]:
        authored = self.author_outlines(outlines)
        return self.legacy_renderer.render(
            authored,
            brand,
            output_path,
            enable_diagrams=enable_diagrams,
        )

    def author_outlines(self, outlines: list[SlideOutline]) -> list[SlideOutline]:
        history: list[str] = []
        counts: dict[str, int] = {}
        authored: list[SlideOutline] = []
        for idx, outline in enumerate(outlines):
            revised = self._author_outline(
                outline,
                idx,
                len(outlines),
                history=history,
                family_counts=counts,
            )
            family = str(revised.layout_json.get("composition_family") or "")
            if family:
                history.append(family)
                counts[family] = counts.get(family, 0) + 1
            authored.append(revised)
        return self._repair_visual_rhythm(authored)

    def _author_outline(
        self,
        outline: SlideOutline,
        index: int,
        total: int,
        history: list[str] | None = None,
        family_counts: dict[str, int] | None = None,
    ) -> SlideOutline:
        if outline.mode != "flexible":
            return outline
        revised = outline.model_copy(deep=True)
        content = revised.content_json
        layout = revised.layout_json
        current = str(layout.get("layout") or "two_column")
        role = str(content.get("narrative_role") or layout.get("narrative_role") or "")
        exhibit = content.get("exhibit_spec")
        exhibit_type = str(exhibit.get("type") or "") if isinstance(exhibit, dict) else ""
        family, chosen_layout = self._composition_for(
            current=current,
            role=role,
            exhibit_type=exhibit_type,
            content=content,
            index=index,
            total=total,
            history=history or [],
            family_counts=family_counts or {},
        )
        # Honor a planning-pinned composition family (the planned slide kind).
        pinned_family = str(content.get("pinned_family") or "").strip()
        if pinned_family:
            family = pinned_family
        layout["layout"] = chosen_layout
        layout["composition_family"] = family
        variant = f"{family}-{index % 4}"
        layout["composition_variant"] = variant
        layout["composition_signature"] = "|".join(
            part
            for part in (
                family,
                variant,
                role or "content",
                exhibit_type or chosen_layout,
                self._density_bucket(content),
            )
            if part
        )
        layout["render_engine"] = "authored"
        content["visual_intent"] = self._visual_intent(
            role=role,
            family=family,
            exhibit_type=exhibit_type,
        )
        content["composition_family"] = family
        content["composition_variant"] = variant
        content["composition_signature"] = layout["composition_signature"]
        return revised

    def _repair_visual_rhythm(self, outlines: list[SlideOutline]) -> list[SlideOutline]:
        if len(outlines) < 3:
            return outlines
        repaired = [outline.model_copy(deep=True) for outline in outlines]
        families = [self._outline_family(outline) for outline in repaired]
        counts = self._family_counts(families)
        for index, family in enumerate(list(families)):
            if not family or family in self.fixed_rhythm_families:
                continue
            previous = families[index - 1] if index > 0 else ""
            if family != previous:
                continue
            replacement = self._rhythm_repair_family(
                repaired[index],
                index,
                families,
                counts,
                require_non_card=family in self.card_like_families,
            )
            if replacement:
                self._retarget_composition(
                    repaired[index],
                    replacement,
                    index,
                    reason="adjacent_visible_composition_repeat",
                )
                counts[family] = max(0, counts.get(family, 0) - 1)
                counts[replacement] = counts.get(replacement, 0) + 1
                families[index] = replacement
        card_count = sum(1 for family in families if family in self.card_like_families)
        while len(families) >= 6 and card_count / len(families) > 0.46:
            replacement_applied = False
            for index, family in sorted(
                enumerate(families),
                key=lambda item: counts.get(item[1], 0),
                reverse=True,
            ):
                if family not in self.card_like_families or family in self.fixed_rhythm_families:
                    continue
                replacement = self._rhythm_repair_family(
                    repaired[index],
                    index,
                    families,
                    counts,
                    require_non_card=True,
                )
                if not replacement:
                    continue
                self._retarget_composition(
                    repaired[index],
                    replacement,
                    index,
                    reason="card_heavy_visual_rhythm",
                )
                counts[family] = max(0, counts.get(family, 0) - 1)
                counts[replacement] = counts.get(replacement, 0) + 1
                families[index] = replacement
                card_count -= 1
                replacement_applied = True
                break
            if not replacement_applied:
                break
        return repaired

    def _outline_family(self, outline: SlideOutline) -> str:
        return str(
            outline.layout_json.get("composition_family")
            or outline.content_json.get("composition_family")
            or ""
        )

    def _family_counts(self, families: list[str]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for family in families:
            if family:
                counts[family] = counts.get(family, 0) + 1
        return counts

    def _rhythm_repair_family(
        self,
        outline: SlideOutline,
        index: int,
        families: list[str],
        counts: dict[str, int],
        require_non_card: bool,
    ) -> str | None:
        current = families[index]
        for candidate in self._rhythm_repair_candidates(outline, require_non_card):
            if candidate == current:
                continue
            if require_non_card and candidate in self.card_like_families:
                continue
            if index > 0 and families[index - 1] == candidate:
                continue
            if index + 1 < len(families) and families[index + 1] == candidate:
                continue
            if counts.get(candidate, 0) >= self._family_repeat_soft_cap(
                candidate,
                len(families),
            ):
                continue
            return candidate
        return None

    def _rhythm_repair_candidates(
        self,
        outline: SlideOutline,
        require_non_card: bool,
    ) -> list[str]:
        content = outline.content_json
        layout = outline.layout_json
        role = str(content.get("narrative_role") or layout.get("narrative_role") or "")
        normalized_role = role.strip().lower().replace("-", "_")
        current_layout = str(layout.get("layout") or "").strip().lower().replace("-", "_")
        exhibit = content.get("exhibit_spec")
        exhibit_type = str(exhibit.get("type") or "") if isinstance(exhibit, dict) else ""
        if exhibit_type == "comparison_table" or current_layout == "comparison_table":
            candidates = [
                "reframe_comparison",
                "architecture_layers",
                "operating_map",
                "statement_canvas",
                "evidence_wall",
                "proof_strip",
            ]
        elif exhibit_type in {"checklist", "reference_table"} or current_layout in {
            "checklist",
            "process",
            "table_reference",
        }:
            candidates = [
                "operating_map",
                "decision_ladder",
                "lifecycle_timeline",
                "architecture_layers",
                "statement_canvas",
                "proof_strip",
            ]
        elif normalized_role in {"problem", "risk", "challenge"}:
            candidates = [
                "reframe_split",
                "architecture_layers",
                "operating_map",
                "statement_canvas",
                "evidence_wall",
                "challenge_cards",
            ]
        elif normalized_role in {"decision", "recommendation"}:
            candidates = [
                "spotlight_quote",
                "decision_ladder",
                "statement_canvas",
                "reframe_split",
                "operating_map",
            ]
        else:
            candidates = [
                "statement_canvas",
                "architecture_layers",
                "operating_map",
                "decision_ladder",
                "lifecycle_timeline",
                "spotlight_quote",
                "reframe_split",
                "evidence_wall",
                "proof_strip",
                "why_it_matters_cards",
            ]
        if not require_non_card:
            return candidates
        return [
            family
            for family in candidates
            if family not in self.card_like_families
        ]

    def _retarget_composition(
        self,
        outline: SlideOutline,
        family: str,
        index: int,
        reason: str,
    ) -> None:
        content = outline.content_json
        layout = outline.layout_json
        role = str(content.get("narrative_role") or layout.get("narrative_role") or "")
        exhibit = content.get("exhibit_spec")
        exhibit_type = str(exhibit.get("type") or "") if isinstance(exhibit, dict) else ""
        chosen_layout = str(layout.get("layout") or "callouts")
        variant = f"{family}-{index % 4}"
        layout["composition_family"] = family
        layout["composition_variant"] = variant
        layout["composition_signature"] = "|".join(
            part
            for part in (
                family,
                variant,
                role or "content",
                exhibit_type or chosen_layout,
                self._density_bucket(content),
            )
            if part
        )
        layout["rhythm_repair"] = {"applied": True, "reason": reason}
        content["visual_intent"] = self._visual_intent(
            role=role,
            family=family,
            exhibit_type=exhibit_type,
        )
        content["composition_family"] = family
        content["composition_variant"] = variant
        content["composition_signature"] = layout["composition_signature"]

    def _composition_for(
        self,
        current: str,
        role: str,
        exhibit_type: str,
        content: dict[str, Any],
        index: int,
        total: int,
        history: list[str],
        family_counts: dict[str, int],
    ) -> tuple[str, str]:
        normalized = current.strip().lower().replace("-", "_")
        if (
            normalized == "cover"
            or role == "cover"
            or (index == 0 and not role and normalized in {"", "two_column"})
        ):
            return "editorial_cover", "cover"
        if (
            normalized == "closing_recommendation"
            or role == "closing"
            or (
                total > 1
                and index == total - 1
                and not role
                and normalized in {"", "two_column", "callouts", "icon_rows"}
            )
        ):
            return "path_forward_close", "closing_recommendation"
        if normalized == "executive_summary" or role == "executive_summary":
            return "editorial_spread", "executive_summary"
        if self._has_quantitative_metrics(content) or (
            normalized == "chart" and self._has_chart_payload(content)
        ):
            return "metric_signal", "chart"
        display_item_count = self._display_item_count(content)
        if display_item_count <= 2 and (
            normalized in {"callouts", "checklist", "icon_grid", "icon_rows", "process"}
            or exhibit_type in {"callouts", "checklist", "icon_rows"}
        ):
            family = self._choose_family(
                [
                    "statement_canvas",
                    "spotlight_quote",
                    "reframe_split",
                    "architecture_layers",
                    "lifecycle_timeline",
                    "proof_strip",
                    "evidence_wall",
                    "why_it_matters_cards",
                ],
                history,
                family_counts,
                preferred="statement_canvas" if display_item_count <= 1 else "reframe_split",
            )
            return family, "callouts"
        if exhibit_type == "comparison_table":
            family = self._choose_family(
                [
                    "reframe_comparison",
                    "evidence_wall",
                    "proof_strip",
                    "architecture_layers",
                ],
                history,
                family_counts,
                preferred="reframe_comparison",
            )
            return family, "comparison_table"
        if exhibit_type == "reference_table":
            family = self._choose_family(
                ["architecture_layers", "evidence_wall", "proof_strip", "operating_map"],
                history,
                family_counts,
                preferred="architecture_layers",
            )
            return family, "table_reference"
        if exhibit_type == "checklist":
            if self._has_long_display_prose(content):
                family = self._choose_family(
                    [
                        "proof_strip",
                        "evidence_wall",
                        "statement_canvas",
                        "reframe_split",
                        "why_it_matters_cards",
                    ],
                    history,
                    family_counts,
                    preferred="proof_strip",
                )
                return family, "callouts"
            family = self._choose_family(
                [
                    "statement_canvas",
                    "operating_map",
                    "decision_ladder",
                    "toolkit_grid",
                    "lifecycle_timeline",
                    "proof_strip",
                ],
                history,
                family_counts,
                preferred="operating_map",
            )
            return family, "checklist"
        if normalized == "code_panel" and not self._has_usable_code_panel(content):
            family = self._degraded_composition_family(index)
            self._mark_degraded_visual(
                content,
                from_family="code_panel",
                to_family=family,
                reason="Weak code/reference panel degraded before rendering.",
            )
            return family, "callouts"
        if exhibit_type == "matrix_2x2" and self._has_usable_matrix(content):
            return "decision_matrix", "matrix_2x2"
        if exhibit_type == "matrix_2x2":
            family = self._degraded_composition_family(index, history, family_counts)
            self._mark_degraded_visual(
                content,
                from_family="decision_matrix",
                to_family=family,
                reason="Weak or generic matrix spec degraded before rendering.",
            )
            return family, "callouts"
        if normalized in {"dependency_map", "framework_cycle"} and self._has_usable_diagram(content):
            return "source_backed_diagram", normalized
        if normalized in {"dependency_map", "framework_cycle"}:
            family = self._degraded_composition_family(index, history, family_counts)
            self._mark_degraded_visual(
                content,
                from_family=normalized,
                to_family=family,
                reason="Weak or generic diagram spec degraded before rendering.",
            )
            return family, "callouts"
        if normalized == "anti_patterns":
            return "circular_trap", "anti_patterns"
        if normalized == "chart":
            family = self._degraded_composition_family(index, history, family_counts)
            self._mark_degraded_visual(
                content,
                from_family="metric_signal",
                to_family=family,
                reason="Weak or incidental metric payload degraded before rendering.",
            )
            return family, "callouts"
        if role == "problem":
            return "challenge_cards", normalized if normalized else "callouts"
        if normalized == "quote_sidebar" or role == "decision":
            family = self._choose_family(
                ["spotlight_quote", "reframe_split", "statement_canvas"],
                history,
                family_counts,
                preferred="spotlight_quote",
            )
            return family, "quote_sidebar" if family == "reframe_split" else "callouts"
        if normalized in {"icon_grid", "icon_rows", "callouts"}:
            return (
                self._card_composition_family(
                    index,
                    role,
                    content,
                    history,
                    family_counts,
                ),
                normalized,
            )
        if normalized == "process":
            family = self._choose_family(
                [
                    "operating_map",
                    "decision_ladder",
                    "lifecycle_timeline",
                    "architecture_layers",
                ],
                history,
                family_counts,
                preferred="operating_map",
            )
            return family, "process"
        return (
            self._card_composition_family(
                index,
                role,
                content,
                history,
                family_counts,
            ),
            normalized if normalized else "two_column",
        )

    def _card_composition_family(
        self,
        index: int,
        role: str,
        content: dict[str, Any],
        history: list[str] | None = None,
        family_counts: dict[str, int] | None = None,
    ) -> str:
        history = history or []
        family_counts = family_counts or {}
        normalized_role = role.strip().lower().replace("-", "_")
        if normalized_role in {"problem", "risk", "challenge"}:
            return self._choose_family(
                ["challenge_cards", "reframe_split", "evidence_wall"],
                history,
                family_counts,
                preferred="challenge_cards",
            )
        if normalized_role in {"decision", "recommendation"}:
            return self._choose_family(
                [
                    "spotlight_quote",
                    "statement_canvas",
                    "reframe_split",
                    "decision_ladder",
                    "operating_map",
                ],
                history,
                family_counts,
                preferred="spotlight_quote",
            )
        if content.get("source_refs") and normalized_role in {"evidence", "reference"}:
            families = [
                "proof_strip",
                "evidence_wall",
                "reframe_split",
                "why_it_matters_cards",
                "architecture_layers",
                "operating_map",
                "statement_canvas",
                "spotlight_quote",
                "decision_ladder",
            ]
            return self._choose_family(families, history, family_counts)
        families = [
            "why_it_matters_cards",
            "toolkit_grid",
            "challenge_cards",
            "evidence_wall",
            "proof_strip",
            "reframe_split",
            "operating_map",
            "statement_canvas",
            "spotlight_quote",
            "decision_ladder",
            "lifecycle_timeline",
        ]
        return self._choose_family(families, history, family_counts)

    def _display_item_count(self, content: dict[str, Any]) -> int:
        return len(self._display_items(content))

    def _display_items(self, content: dict[str, Any]) -> list[str]:
        exhibit = content.get("exhibit_spec")
        raw_items: list[Any] = []
        raw_items.extend(content.get("bullets") or [])
        blocks = content.get("content_blocks")
        if isinstance(blocks, list):
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                body = block.get("body")
                if isinstance(body, list):
                    raw_items.extend(body)
                elif body:
                    raw_items.append(body)
        if isinstance(exhibit, dict):
            for key in ("items", "points", "supporting_points", "next_steps", "lines", "rules"):
                value = exhibit.get(key)
                if isinstance(value, list):
                    raw_items.extend(value)
            rows = exhibit.get("rows")
            if isinstance(rows, list):
                raw_items.extend(rows)

        seen: set[str] = set()
        items: list[str] = []
        for item in raw_items:
            text = self._display_item_text(item)
            if not text or self._looks_like_renderer_filler(text):
                continue
            key = re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()
            if key and key not in seen:
                seen.add(key)
                items.append(text)
        return items

    def _has_long_display_prose(self, content: dict[str, Any]) -> bool:
        items = self._display_items(content)
        if not items:
            return False
        word_counts = [len(item.split()) for item in items]
        return max(word_counts) >= 12 or sum(word_counts) / len(word_counts) >= 9

    def _display_item_text(self, item: Any) -> str:
        if isinstance(item, dict):
            parts = [
                str(item.get(key) or "").strip()
                for key in ("action", "label", "title", "text", "body", "description")
                if str(item.get(key) or "").strip()
            ]
            if not parts:
                values = item.get("values")
                if isinstance(values, list):
                    parts = [str(value).strip() for value in values if str(value).strip()]
            text = " ".join(parts)
        elif isinstance(item, (list, tuple)):
            text = " ".join(str(value).strip() for value in item if str(value).strip())
        else:
            text = str(item or "")
        return " ".join(text.split()).strip(" -:;")

    def _looks_like_renderer_filler(self, text: str) -> bool:
        normalized = re.sub(r"[^a-z0-9]+", " ", str(text).casefold())
        normalized = " ".join(normalized.split())
        if not normalized:
            return True
        filler_phrases = {
            "tie the claim to a source backed evaluation artifact",
            "tie the claim source backed evaluation artifact",
            "connect the source evidence to the decision before scaling",
            "make the handoff inspectable before the decision moves",
            "each step should pair evidence ownership and timing",
            "make the next move visible enough to own inspect and revise",
            "name the review gate before expanding the benchmark",
            "update the benchmark when source evidence changes",
            "make the operating implication explicit",
            "assign the next review gate before scaling",
            "track what changes when the source evidence moves",
            "evidence tension",
            "reliability risk",
            "operating move",
            "evidence gap",
            "validation risk",
            "operating choice",
            "deterministic beat for evidence",
            "deterministic beat for implementation",
            "deterministic beat for reference",
            "deterministic beat for decision",
            "deterministic beat for closing",
        }
        if normalized in filler_phrases:
            return True
        if len(normalized.split()) < 3:
            return True
        return bool(
            re.search(
                r"\bconnect\b.{0,90}\b(?:to\s+)?an explicit review gate\b|"
                r"\bmake\b.{0,90}\bvisible before execution starts\b|"
                r"\buse the model to decide what must be explicit\b|"
                r"\bdeterministic beat for\b",
                normalized,
            )
        )

    def _degraded_composition_family(
        self,
        index: int,
        history: list[str] | None = None,
        family_counts: dict[str, int] | None = None,
    ) -> str:
        families = [
            "spotlight_quote",
            "proof_strip",
            "statement_canvas",
            "reframe_split",
            "evidence_wall",
            "why_it_matters_cards",
            "architecture_layers",
        ]
        return self._choose_family(
            families,
            history or [],
            family_counts or {},
            preferred="proof_strip",
        )

    def _choose_family(
        self,
        candidates: list[str],
        history: list[str],
        family_counts: dict[str, int],
        preferred: str | None = None,
    ) -> str:
        viable = [candidate for candidate in candidates if candidate]
        if not viable:
            return preferred or "evidence_wall"
        recent = history[-3:]
        total_so_far = sum(family_counts.values())
        card_like_so_far = sum(
            count
            for family, count in family_counts.items()
            if family in self.card_like_families
        )
        has_non_card_candidate = any(
            candidate not in self.card_like_families for candidate in viable
        )
        card_ratio_so_far = card_like_so_far / total_so_far if total_so_far else 0

        def score(candidate: str) -> tuple[int, int, int]:
            recent_penalty = 0
            if recent and candidate == recent[-1]:
                recent_penalty += 8
            if candidate in recent[-2:]:
                recent_penalty += 4
            if recent.count(candidate) > 1:
                recent_penalty += 3
            count_penalty = family_counts.get(candidate, 0) * 2
            repeat_cap_penalty = (
                10
                if family_counts.get(candidate, 0)
                >= self._family_repeat_soft_cap(candidate, total_so_far + 1)
                else 0
            )
            card_budget_penalty = (
                12
                if (
                    has_non_card_candidate
                    and candidate in self.card_like_families
                    and total_so_far >= 4
                    and card_ratio_so_far >= 0.4
                )
                else 0
            )
            preferred_bonus = -1 if preferred and candidate == preferred and candidate not in recent[-2:] else 0
            return (
                recent_penalty
                + count_penalty
                + repeat_cap_penalty
                + card_budget_penalty
                + preferred_bonus,
                count_penalty + repeat_cap_penalty + card_budget_penalty,
                viable.index(candidate),
            )
        return min(viable, key=score)

    def _family_repeat_soft_cap(self, family: str, total: int) -> int:
        if total < 10:
            return 2
        if family in {"statement_canvas", "operating_map", "decision_ladder"}:
            return 3
        return 2

    def _has_quantitative_metrics(self, content: dict[str, Any]) -> bool:
        metric_exhibit_types = {
            "metric_chart",
            "line_chart",
            "bar_chart",
            "chart",
            "metrics",
        }
        exhibit = content.get("exhibit_spec")
        if isinstance(exhibit, dict):
            exhibit_type = str(exhibit.get("type") or "").strip().lower()
            exhibit_metrics = exhibit.get("metrics")
            if exhibit_type in metric_exhibit_types and isinstance(exhibit_metrics, list):
                return any(
                    isinstance(metric, dict) and self._is_quantitative_metric(metric)
                    for metric in exhibit_metrics
                )
        metrics = content.get("metrics")
        return isinstance(metrics, list) and sum(
            1
            for metric in metrics
            if isinstance(metric, dict) and self._is_quantitative_metric(metric)
        ) >= 2

    def _has_chart_payload(self, content: dict[str, Any]) -> bool:
        chart_spec = content.get("chart_spec")
        if isinstance(chart_spec, dict) and chart_spec:
            chart_metrics = chart_spec.get("metrics") or chart_spec.get("data")
            if isinstance(chart_metrics, list):
                return any(
                    isinstance(metric, dict) and self._is_quantitative_metric(metric)
                    for metric in chart_metrics
                )
            return False
        metrics = content.get("metrics")
        if isinstance(metrics, list) and any(
            isinstance(metric, dict) and self._is_quantitative_metric(metric)
            for metric in metrics
        ):
            return True
        exhibit = content.get("exhibit_spec")
        if isinstance(exhibit, dict):
            exhibit_type = str(exhibit.get("type") or "").strip().lower()
            if exhibit_type not in {"metric_chart", "line_chart", "bar_chart", "chart"}:
                return False
            exhibit_metrics = exhibit.get("metrics")
            return isinstance(exhibit_metrics, list) and any(
                isinstance(metric, dict) and self._is_quantitative_metric(metric)
                for metric in exhibit_metrics
            )
        return False

    def _is_quantitative_metric(self, metric: dict[str, Any]) -> bool:
        unit = str(metric.get("unit") or "").strip()
        label = str(metric.get("label") or metric.get("name") or "").strip().casefold()
        try:
            number = float(str(metric.get("value", "")).replace(",", "").rstrip("%"))
        except (TypeError, ValueError):
            number = None
        if unit and number is not None and abs(number) <= 2 and label in {
            "prediction",
            "predictions",
            "item",
            "items",
        }:
            return False
        if unit:
            return True
        if number is None:
            return False
        return abs(number) >= 10

    def _has_usable_diagram(self, content: dict[str, Any]) -> bool:
        diagram = content.get("diagram_spec")
        if not isinstance(diagram, dict):
            return False
        kind = str(diagram.get("kind") or "").lower()
        if kind == "dependency_flow":
            nodes = diagram.get("middle_nodes") or diagram.get("nodes")
            labels = [str(node) for node in nodes or [] if str(node).strip()]
            labels.extend([str(diagram.get("left_node") or ""), str(diagram.get("right_outcome") or "")])
            return (
                len(labels) >= 2
                and not self._is_generic_diagram(labels)
                and not self._is_question_prompt_diagram(labels)
            )
        if kind == "cycle":
            steps = diagram.get("steps")
            labels = [
                str(step.get("label") or step.get("description") or "")
                for step in steps or []
                if isinstance(step, dict)
            ]
            return (
                len([label for label in labels if label.strip()]) >= 4
                and not self._is_generic_diagram(labels)
                and not self._is_question_prompt_diagram(labels)
            )
        return False

    def _has_usable_matrix(self, content: dict[str, Any]) -> bool:
        exhibit = content.get("exhibit_spec")
        if not isinstance(exhibit, dict):
            return False
        quadrants = exhibit.get("quadrants")
        if not isinstance(quadrants, list) or len(quadrants) < 4:
            return False
        labels = [
            str(item.get("label") if isinstance(item, dict) else item).strip()
            for item in quadrants[:4]
        ]
        if len([label for label in labels if label]) < 4:
            return False
        normalized = {" ".join(label.casefold().split()) for label in labels}
        generic = {
            "high impact / high readiness",
            "high impact / low readiness",
            "low impact / high readiness",
            "low impact / low readiness",
        }
        return len(normalized.intersection(generic)) < 2

    def _has_usable_code_panel(self, content: dict[str, Any]) -> bool:
        exhibit = content.get("exhibit_spec")
        if not isinstance(exhibit, dict):
            return False
        if str(exhibit.get("type") or "").lower() != "code_panel":
            return False
        title = str(exhibit.get("title") or "")
        lines = [
            " ".join(str(line).split())
            for line in exhibit.get("lines", [])
            if str(line).strip()
        ]
        if len(lines) < 3 or not re.search(r"\.(md|yml|yaml|json|txt)$", title, re.IGNORECASE):
            return False
        return not any(self._has_bad_content_artifact(line) for line in lines)

    def _has_bad_content_artifact(self, text: str) -> bool:
        return bool(
            re.search(
                r"\bconvert\b.{0,180}\binto an(?: owned)?(?: action)?|"
                r"\(\s*owner\s*/\s*next\s*\)|\bowner\s*/\s*next\b|"
                r"\w\s*\|\s*\w",
                str(text),
                re.IGNORECASE,
            )
        )

    def _mark_degraded_visual(
        self,
        content: dict[str, Any],
        from_family: str,
        to_family: str,
        reason: str,
    ) -> None:
        exhibit = content.get("exhibit_spec")
        original_exhibit_type = (
            str(exhibit.get("type") or "") if isinstance(exhibit, dict) else ""
        )
        content["visual_degradation"] = {
            "from": from_family,
            "to": to_family,
            "original_exhibit_type": original_exhibit_type,
            "reason": reason,
        }
        content["archetype"] = "callouts"
        content["exhibit_spec"] = {
            "type": "callouts",
            "points": self._degraded_callout_points(content),
        }

    def _degraded_callout_points(self, content: dict[str, Any]) -> list[str]:
        candidates: list[str] = []
        bullets = content.get("bullets")
        if isinstance(bullets, list):
            candidates.extend(str(item) for item in bullets)
        blocks = content.get("content_blocks")
        if isinstance(blocks, list):
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                body = block.get("body")
                if isinstance(body, list):
                    candidates.extend(str(item) for item in body)
        fallback = content.get("subheading") or content.get("summary") or content.get("action_title")
        if fallback:
            candidates.append(str(fallback))
        cleaned: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            text = " ".join(str(candidate).split()).strip(" -:;")
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(text[:180])
            if len(cleaned) >= 4:
                break
        return cleaned or ["Use source-backed evidence instead of a generic visual fallback."]

    def _is_generic_diagram(self, labels: list[str]) -> bool:
        generic = {
            "frame",
            "ground",
            "build",
            "prime",
            "generate",
            "review",
            "update",
            "reset",
            "persist",
            "source context",
            "rules",
            "memory",
            "reliable output",
            "operating loop",
        }
        normalized = {" ".join(label.casefold().split()) for label in labels if label.strip()}
        return len(normalized.intersection(generic)) >= 3

    def _is_question_prompt_diagram(self, labels: list[str]) -> bool:
        normalized = [
            " ".join(str(label).casefold().split()).strip(" .:-")
            for label in labels
            if str(label).strip()
        ]
        if not normalized:
            return False
        prompt_like = {
            "what goes in",
            "what comes out",
            "what is allowed",
            "what is measured",
            "beyond output format",
            "the questions",
        }
        hits = sum(
            1
            for label in normalized
            if label in prompt_like or label.startswith("what ")
        )
        return hits >= 2

    def _density_bucket(self, content: dict[str, Any]) -> str:
        text = " ".join(self._flatten(content.get(key)) for key in ("subheading", "content_blocks", "exhibit_spec"))
        words = len(text.split())
        if words > 110:
            return "dense"
        if words > 45:
            return "medium"
        return "light"

    def _visual_intent(self, role: str, family: str, exhibit_type: str) -> dict[str, str]:
        return {
            "role": role or "content",
            "composition_family": family,
            "exhibit_type": exhibit_type,
            "purpose": "Match visual treatment to the slide claim before rendering.",
        }

    def _flatten(self, value: Any) -> str:
        if isinstance(value, dict):
            return " ".join(self._flatten(item) for item in value.values())
        if isinstance(value, list):
            return " ".join(self._flatten(item) for item in value)
        return str(value or "")
