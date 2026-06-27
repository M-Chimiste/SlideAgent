# ruff: noqa: F401
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from app.models.document import DocumentBundle, DocumentSection
from app.models.generation import ContentBlock, DeckBlueprint, DeckSpec, GeneratedSlideSpec
from app.models.outline import SlideOutline
from app.models.planning import SourceCompression, SpecGateIssue, SpecGateRepair, SpecGateReport, StoryMap
from app.models.template import SlideSpec, TemplateProfile
from app.services.planning.constants import (
    PLANNER_SYSTEM_PROMPT,
    SOURCE_NEEDED_LABEL,
    UPLOADED_SOURCE_LABEL,
)


class SpecGateMixin:
    def _run_spec_gate(
        self,
        deck: DeckSpec,
        bundle: DocumentBundle,
        source_compression: SourceCompression,
        story_map: StoryMap,
    ) -> SpecGateReport:
        issues: list[SpecGateIssue] = []
        repairs: list[SpecGateRepair] = []
        seen_titles: set[str] = set()
        seen_fingerprints: list[tuple[int, str, set[str], str]] = []
        seen_source_refs: set[str] = set()
        seen_metric_keys: set[str] = set()
        heavy_counts: dict[str, int] = {}
        thin_to_drop: set[int] = set()
        for slide in deck.slides:
            self._gate_repair_sources(slide, bundle, issues, repairs)
            self._gate_repair_title(slide, seen_titles, issues, repairs)
            self._gate_repair_exhibit(slide, bundle, story_map, issues, repairs)
            self._gate_repair_metric_repetition(slide, bundle, seen_metric_keys, issues, repairs)
            self._gate_repair_supported_source_placeholders(
                slide,
                bundle,
                issues,
                repairs,
            )
            # Density gate runs BEFORE the budget gate so a converted slide gets
            # the right per-primitive budget.
            self._gate_repair_sparse_slide(slide, story_map, thin_to_drop, issues, repairs)
            self._gate_repair_content_budget(slide, issues, repairs)
            self._gate_repair_heavy_repetition(slide, bundle, heavy_counts, issues, repairs)
            self._gate_repair_bad_copy(slide, bundle, issues, repairs)
            self._gate_repair_duplicate(
                slide,
                bundle,
                seen_fingerprints,
                seen_source_refs,
                issues,
                repairs,
            )
            self._gate_track_source_refs(slide, seen_source_refs)
            fingerprint = self._gate_slide_fingerprint(slide)
            seen_fingerprints.append(
                (
                    slide.slide_number,
                    self._normalize_archetype(slide.archetype or ""),
                    fingerprint,
                    self._gate_exhibit_signature(slide),
                )
            )
        # Drop slides that stayed below their density floor after enrichment, so a
        # thin source yields fewer, denser, finished slides (down to a floor).
        self._drop_thin_slides(deck, thin_to_drop, repairs)
        issues.extend(self._gate_unresolved_issues(deck, bundle))
        repaired_count = sum(1 for issue in issues if issue.repaired)
        unresolved_count = sum(1 for issue in issues if not issue.repaired)
        status = "pass"
        if unresolved_count:
            status = "warn"
        elif repaired_count:
            status = "repaired"
        return SpecGateReport(
            status=status,
            issues=issues,
            repairs=repairs,
            issue_count=len(issues),
            repaired_count=repaired_count,
            unresolved_count=unresolved_count,
            summary={
                "slide_count": len(deck.slides),
                "source_coverage": {
                    "section_count": source_compression.section_count,
                    "included_section_count": source_compression.included_section_count,
                    "omitted_section_count": source_compression.omitted_section_count,
                    "estimated_tokens": source_compression.estimated_tokens,
                },
            },
            )

    def _gate_repair_sparse_slide(
        self,
        slide: GeneratedSlideSpec,
        story_map: StoryMap,
        thin_to_drop: set[int],
        issues: list[SpecGateIssue],
        repairs: list[SpecGateRepair],
    ) -> None:
        """Ensure each slide meets its slide-type density floor: enrich from the
        beat's bound evidence, else mark the slide to be dropped/merged so the deck
        has fewer, denser, finished slides instead of half-empty grids or filler."""
        from app.services.slide_types import get_slide_type

        # Statement-shaped / title kinds are intentionally sparse — leave them.
        if slide.slide_type in {
            "cover", "section", "closing", "quote", "stat", "statement", "decision",
        }:
            return
        stype = get_slide_type(slide.slide_type)
        count = self._substantive_item_count(slide)
        if count >= stype.min_points:
            return
        before_count = count
        beat = self._beat_for_slide(slide, story_map)
        if beat and beat.evidence:
            self._enrich_slide_from_evidence(slide, beat.evidence, stype.min_points - count)
            count = self._substantive_item_count(slide)
        if count < stype.min_points:
            thin_to_drop.add(slide.slide_number)
            issues.append(SpecGateIssue(
                slide_number=slide.slide_number, category="sparse_content",
                message=f"Thin slide ({before_count} pts) below density floor; dropped for a denser deck.",
                repaired=True,
            ))
            repairs.append(SpecGateRepair(
                slide_number=slide.slide_number, action="drop_thin_slide",
                before=str(before_count), after="dropped",
            ))
        elif count > before_count:
            issues.append(SpecGateIssue(
                slide_number=slide.slide_number, category="sparse_content",
                message=f"Thin slide enriched from source evidence ({before_count} -> {count} pts).",
                repaired=True,
            ))
            repairs.append(SpecGateRepair(
                slide_number=slide.slide_number, action="enrich_from_evidence",
                before=str(before_count), after=str(count),
            ))

    def _substantive_item_count(self, slide: GeneratedSlideSpec) -> int:
        count = 0
        for block in slide.content_blocks:
            for item in block.body:
                if isinstance(item, str) and len(item.split()) >= 3:
                    count += 1
        ex = slide.exhibit_spec or {}
        if isinstance(ex, dict):
            for key in ("points", "items", "rows", "steps", "cards", "metrics"):
                value = ex.get(key)
                if isinstance(value, list):
                    count = max(count, len([x for x in value if x]))
        return count

    def _beat_for_slide(self, slide: GeneratedSlideSpec, story_map: StoryMap):
        beats = story_map.beats or []
        idx = slide.slide_number - 1
        if 0 <= idx < len(beats):
            return beats[idx]
        refs = set(slide.source_refs or [])
        for beat in beats:
            if refs & set(beat.source_refs or []):
                return beat
        return None

    def _enrich_slide_from_evidence(
        self, slide: GeneratedSlideSpec, evidence: list[str], need: int
    ) -> None:
        if need <= 0:
            return
        existing = {
            " ".join(str(b).lower().split())
            for block in slide.content_blocks for b in block.body if isinstance(b, str)
        }
        additions = [
            e for e in evidence
            if " ".join(str(e).lower().split()) not in existing and len(str(e).split()) >= 3
        ][:need]
        if not additions:
            return
        block = next((b for b in slide.content_blocks if b.type == "bullets"), None)
        if block is None:
            block = ContentBlock(type="bullets", body=[])
            slide.content_blocks.append(block)
        block.body.extend(additions)
        ex = slide.exhibit_spec
        if isinstance(ex, dict) and isinstance(ex.get("points"), list):
            ex["points"].extend(additions)

    def _slide_has_metrics(self, slide: GeneratedSlideSpec) -> bool:
        chart = slide.chart_spec if isinstance(slide.chart_spec, dict) else None
        if chart and chart.get("data_points"):
            return True
        ex = slide.exhibit_spec or {}
        if isinstance(ex, dict):
            if ex.get("type") in {"metric_chart", "chart", "kpi"}:
                return True
            if isinstance(ex.get("metrics"), list) and ex["metrics"]:
                return True
        return False

    # Keep at least this many slides even if several are thin, so a sparse source
    # still yields a real deck rather than a stub.
    _MIN_DECK_SLIDES = 5

    def _drop_thin_slides(
        self, deck: DeckSpec, thin_to_drop: set[int], repairs: list[SpecGateRepair]
    ) -> None:
        """Drop slides that stayed below their density floor after enrichment, down
        to a floor — fewer, denser, finished slides instead of half-empty ones.
        Cover and closing slides are never dropped."""
        if not thin_to_drop:
            return
        protected = {"cover", "closing_recommendation"}
        droppable = [
            slide.slide_number
            for slide in deck.slides
            if slide.slide_number in thin_to_drop
            and self._normalize_archetype(slide.archetype or "") not in protected
        ]
        max_drop = max(0, len(deck.slides) - self._MIN_DECK_SLIDES)
        drop_ids = set(droppable[:max_drop])
        if not drop_ids:
            return
        before_count = len(deck.slides)
        kept = [slide for slide in deck.slides if slide.slide_number not in drop_ids]
        for number, slide in enumerate(kept, 1):
            slide.slide_number = number
        deck.slides = kept
        repairs.append(SpecGateRepair(
            slide_number=None, action="drop_thin_slides",
            before=str(before_count), after=str(len(kept)),
        ))

    def _gate_repair_bad_copy(
        self,
        slide: GeneratedSlideSpec,
        bundle: DocumentBundle,
        issues: list[SpecGateIssue],
        repairs: list[SpecGateRepair],
    ) -> None:
        if self._normalize_archetype(slide.archetype or "") in {
            "cover",
            "executive_summary",
            "closing_recommendation",
        }:
            return
        reasons = self._gate_bad_copy_reasons(slide)
        if not reasons:
            return
        before = self._slide_claim_text(slide)[:260]
        section = self._section_for_slide_sources(slide, bundle)
        archetype = self._gate_safe_rewrite_archetype(slide)
        if section is not None:
            slide.source_refs = [self._source_ref(section, slide.slide_number - 1)]
            slide.sources = self._source_labels_for_refs(slide.source_refs, bundle) or [
                UPLOADED_SOURCE_LABEL
            ]
            slide.action_title = self._clean_action_title_candidate(
                self._fallback_action_title(archetype, section.title, section)
            )
            slide.subheading = self._clean_section_title(section.title)
        self._apply_selected_exhibit(slide, archetype, section, bundle)
        slide.diagram_spec = None
        issues.append(
            SpecGateIssue(
                slide_number=slide.slide_number,
                category="bad_copy",
                message=(
                    "Malformed source-fragment copy was rebuilt from source before rendering: "
                    + "; ".join(reasons[:3])
                ),
                repaired=True,
            )
        )
        repairs.append(
            SpecGateRepair(
                slide_number=slide.slide_number,
                action="rebuild_bad_copy",
                before=before,
                after=self._slide_claim_text(slide)[:260],
            )
        )

    def _gate_bad_copy_reasons(self, slide: GeneratedSlideSpec) -> list[str]:
        reasons: list[str] = []
        for text in self._gate_text_values(slide):
            cleaned = " ".join(str(text).split()).strip()
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if self._gate_has_source_fragment_artifact(lowered):
                reasons.append(self._truncate_at_word(cleaned, 72))
            elif (
                len(cleaned.split()) >= 4
                and "..." not in cleaned
                and "…" not in cleaned
                and (
                    self._ends_with_dangling_token(cleaned)
                    or re.match(r"^(?:to|or|and|but)\s+\w", lowered)
                )
            ):
                reasons.append(self._truncate_at_word(cleaned, 72))
        deduped: list[str] = []
        seen: set[str] = set()
        for reason in reasons:
            key = reason.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(reason)
        return deduped

    def _gate_text_values(self, slide: GeneratedSlideSpec) -> list[str]:
        values = [slide.action_title, slide.subheading]
        for block in slide.content_blocks:
            values.extend(self._gate_flatten_text(block.body))
            values.extend(block.annotations)
            values.extend(block.callouts)
        values.extend(self._gate_flatten_text(slide.exhibit_spec))
        values.extend(self._gate_flatten_text(slide.chart_spec))
        values.extend(self._gate_flatten_text(slide.diagram_spec))
        return [str(value) for value in values if str(value).strip()]

    def _gate_flatten_text(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, dict):
            return [
                item
                for nested in value.values()
                for item in self._gate_flatten_text(nested)
            ]
        if isinstance(value, list):
            return [
                item
                for nested in value
                for item in self._gate_flatten_text(nested)
            ]
        return [str(value)]

    def _gate_has_source_fragment_artifact(self, lowered: str) -> bool:
        return any(
            marker in lowered
            for marker in (
                "rather than asking how do we",
                "instead of looking at using models",
                "turns existing",
                "make closing remarks an explicit",
                "or a human review",
                "this white paper",
                "a reframing of",
                "development of evaluation",
                "tie the claim to a source-backed evaluation artifact",
                "name the review gate before expanding the benchmark",
                "update the benchmark when source evidence changes",
                "make the next move visible enough",
                "adopt the operating model through a named pilot and review gate",
                "confirm owner, scope, and timing",
                "confirm ownership and timing",
            )
        ) or bool(
            re.search(
                r"\b(?:rather than|instead of|while this|by shifting|the key|"
                r"this white paper|a reframing of)\b[^.?!]{0,120}$|"
                r"\bconnect\b.{0,80}\bto an explicit review gate\b|"
                r"\bmake\b.{0,80}\bvisible before execution starts\b",
                lowered,
            )
        )

    def _gate_safe_rewrite_archetype(self, slide: GeneratedSlideSpec) -> str:
        text = self._slide_claim_text(slide).lower()
        current = self._normalize_archetype(slide.archetype or "")
        if "question" in text or "checklist" in text:
            return "checklist"
        if current in {"metric_chart", "chart"}:
            return "callouts"
        return "icon_rows" if slide.slide_number % 2 else "callouts"

    def _gate_repair_sources(
        self,
        slide: GeneratedSlideSpec,
        bundle: DocumentBundle,
        issues: list[SpecGateIssue],
        repairs: list[SpecGateRepair],
    ) -> None:
        refs = [
            str(ref)
            for ref in slide.source_refs
            if str(ref).strip()
        ]
        invalid = [
            ref
            for ref in refs
            if ref != SOURCE_NEEDED_LABEL and not self._source_ref_is_valid(ref, bundle)
        ]
        if refs and not invalid:
            return
        before = ", ".join(refs)
        repaired_refs = self._fallback_source_refs_for_slide(slide, bundle)
        slide.source_refs = repaired_refs
        slide.sources = self._source_labels_for_refs(repaired_refs, bundle) or [UPLOADED_SOURCE_LABEL]
        issues.append(
            SpecGateIssue(
                slide_number=slide.slide_number,
                category="source_refs",
                message="Missing or invalid source refs were replaced before rendering.",
                repaired=True,
            )
        )
        repairs.append(
            SpecGateRepair(
                slide_number=slide.slide_number,
                action="replace_source_refs",
                before=before,
                after=", ".join(repaired_refs),
            )
        )

    def _gate_repair_title(
        self,
        slide: GeneratedSlideSpec,
        seen_titles: set[str],
        issues: list[SpecGateIssue],
        repairs: list[SpecGateRepair],
    ) -> None:
        before = slide.action_title
        title_key = self._gate_normalize(before)
        weak = self._gate_title_is_weak(before)
        repeated = bool(title_key and title_key in seen_titles)
        if not weak and not repeated:
            seen_titles.add(title_key)
            return
        # On the LLM path, weak (non-repeated) titles are deferred to the narrative +
        # refine passes (and a final deterministic backstop); the gate only dedups
        # repeated titles here. Deterministic weak-rewrite stays for the no-LLM path.
        if weak and not repeated and self.llm_client is not None:
            seen_titles.add(title_key)
            return
        if repeated:
            repaired = self._unique_action_title(slide, seen_titles)
        else:
            repaired = self._clean_action_title_candidate(
                self._repair_weak_action_title(slide, before)
            )
        slide.action_title = repaired
        issues.append(
            SpecGateIssue(
                slide_number=slide.slide_number,
                category="action_title",
                message="Weak or repeated action title was repaired before rendering.",
                repaired=True,
            )
        )
        repairs.append(
            SpecGateRepair(
                slide_number=slide.slide_number,
                action="repair_action_title",
                before=before,
                after=slide.action_title,
            )
        )
        seen_titles.add(self._gate_normalize(slide.action_title))

    def _gate_repair_exhibit(
        self,
        slide: GeneratedSlideSpec,
        bundle: DocumentBundle,
        story_map: StoryMap,
        issues: list[SpecGateIssue],
        repairs: list[SpecGateRepair],
    ) -> None:
        before = str((slide.exhibit_spec or {}).get("type") or "")
        if isinstance(slide.exhibit_spec, dict) and not self._exhibit_is_incomplete(slide):
            return
        self._apply_exhibit_selection(DeckSpec(deck_title="gate", slides=[slide]), bundle, story_map)
        issues.append(
            SpecGateIssue(
                slide_number=slide.slide_number,
                category="missing_exhibit",
                message="Missing or underfilled exhibit was rebuilt before rendering.",
                repaired=True,
            )
        )
        repairs.append(
            SpecGateRepair(
                slide_number=slide.slide_number,
                action="rebuild_exhibit",
                before=before,
                after=str((slide.exhibit_spec or {}).get("type") or ""),
            )
        )

    def _gate_repair_metric_repetition(
        self,
        slide: GeneratedSlideSpec,
        bundle: DocumentBundle,
        seen_metric_keys: set[str],
        issues: list[SpecGateIssue],
        repairs: list[SpecGateRepair],
    ) -> None:
        exhibit = slide.exhibit_spec if isinstance(slide.exhibit_spec, dict) else {}
        if str(exhibit.get("type") or "") not in {"metric_chart", "line_chart"}:
            return
        metrics = [metric for metric in (exhibit.get("metrics") or []) if isinstance(metric, dict)]
        if not metrics:
            return
        fresh: list[dict[str, Any]] = []
        duplicates = 0
        for metric in metrics:
            key = self._metric_key(metric.get("label"), metric.get("value"), metric.get("unit"))
            if key in seen_metric_keys:
                duplicates += 1
            else:
                fresh.append(metric)
        if duplicates == 0:
            for metric in metrics:
                seen_metric_keys.add(
                    self._metric_key(metric.get("label"), metric.get("value"), metric.get("unit"))
                )
            return
        before = str(exhibit.get("type") or "")
        if len(fresh) >= 2:
            exhibit["metrics"] = fresh
            if isinstance(slide.chart_spec, dict):
                slide.chart_spec["metrics"] = fresh
            for metric in fresh:
                seen_metric_keys.add(
                    self._metric_key(metric.get("label"), metric.get("value"), metric.get("unit"))
                )
            after = f"{before} (-{duplicates} repeated metric)"
        else:
            # Too few distinct metrics remain; rebuild as a non-metric exhibit.
            section = self._section_for_slide_sources(slide, bundle)
            replacement = self._gate_replacement_archetype(slide, bundle)
            if self._normalize_archetype(replacement) in {"metric_chart", "chart"}:
                replacement = "callouts"
            self._apply_selected_exhibit(slide, replacement, section, bundle)
            after = self._normalize_archetype(slide.archetype or "")
        issues.append(
            SpecGateIssue(
                slide_number=slide.slide_number,
                category="repeated_metrics",
                message="Metric(s) already shown on an earlier slide were removed before rendering.",
                repaired=True,
            )
        )
        repairs.append(
            SpecGateRepair(
                slide_number=slide.slide_number,
                action="dedupe_metrics",
                before=before,
                after=after,
            )
        )

    def _gate_repair_content_budget(
        self,
        slide: GeneratedSlideSpec,
        issues: list[SpecGateIssue],
        repairs: list[SpecGateRepair],
    ) -> None:
        # Budget the content to the slide's pinned render primitive (its real
        # capacity) instead of a blind one-size 145-char trim. Fitting content in
        # roomy primitives survives untouched; tight ones stay bounded.
        from app.services.slide_types import get_slide_type

        cap = get_slide_type(slide.slide_type).budget()
        body_cap = cap.body.max_chars
        before = json.dumps([block.model_dump() for block in slide.content_blocks], ensure_ascii=True)
        for block in slide.content_blocks:
            limit = cap.max_items
            if block.type in {"table", "chart"}:
                # Table rows are lists and chart bodies are metric dicts; never
                # coerce these to ``str`` here or a dict reaches the slide as its
                # raw ``{'label': ...}`` repr. Tables still get a row trim.
                if block.type == "table":
                    block.body = self._gate_trim_table(block.body)
            else:
                block.body = [
                    self._truncate_at_word(str(item), body_cap)
                    for item in block.body[:limit]
                    if isinstance(item, str) and item.strip()
                ]
            if block.annotations:
                block.annotations = [
                    self._truncate_at_word(str(item), 100)
                    for item in block.annotations[:3]
                    if str(item).strip()
                ]
            if block.callouts:
                block.callouts = [
                    self._truncate_at_word(str(item), 100)
                    for item in block.callouts[:3]
                    if str(item).strip()
                ]
        after = json.dumps([block.model_dump() for block in slide.content_blocks], ensure_ascii=True)
        changed = before != after
        if not changed:
            return
        issues.append(
            SpecGateIssue(
                slide_number=slide.slide_number,
                category="content_budget",
                message="Over-budget content was condensed before rendering.",
                repaired=True,
            )
        )
        repairs.append(
            SpecGateRepair(
                slide_number=slide.slide_number,
                action="condense_content",
                before=before[:240],
                after=after[:240],
            )
        )

    def _gate_repair_supported_source_placeholders(
        self,
        slide: GeneratedSlideSpec,
        bundle: DocumentBundle,
        issues: list[SpecGateIssue],
        repairs: list[SpecGateRepair],
    ) -> None:
        claim_text = self._slide_claim_text(slide)
        if SOURCE_NEEDED_LABEL.lower() not in claim_text.lower():
            return
        cleaned_claim_text = self._strip_source_needed_marker(claim_text)
        numeric_tokens = self._numeric_tokens(cleaned_claim_text)
        if numeric_tokens:
            unsupported = numeric_tokens - self._supported_numeric_tokens(bundle)
            if unsupported:
                return
        elif not self._gate_slide_has_real_source(slide, bundle):
            return
        before = claim_text[:240]
        slide.action_title = self._strip_source_needed_marker(slide.action_title)
        slide.subheading = self._strip_source_needed_marker(slide.subheading)
        for block in slide.content_blocks:
            block.body = [
                self._strip_source_needed_from_value(item) for item in block.body
            ]
            block.annotations = [
                self._strip_source_needed_marker(item) for item in block.annotations
            ]
            block.callouts = [
                self._strip_source_needed_marker(item) for item in block.callouts
            ]
        if slide.chart_spec:
            slide.chart_spec = self._strip_source_needed_from_value(slide.chart_spec)
        if slide.exhibit_spec:
            slide.exhibit_spec = self._strip_source_needed_from_value(slide.exhibit_spec)
        if slide.diagram_spec:
            slide.diagram_spec = self._strip_source_needed_from_value(slide.diagram_spec)
        slide.sources = [
            source for source in slide.sources if source != SOURCE_NEEDED_LABEL
        ]
        slide.source_refs = [
            ref for ref in slide.source_refs if ref != SOURCE_NEEDED_LABEL
        ]
        if not slide.source_refs and self._has_uploaded_source_material(bundle):
            slide.source_refs = self._fallback_source_refs_for_slide(slide, bundle)
        if not slide.sources:
            slide.sources = self._source_labels_for_refs(slide.source_refs, bundle) or [
                UPLOADED_SOURCE_LABEL
            ]
        issues.append(
            SpecGateIssue(
                slide_number=slide.slide_number,
                category="unsupported_numeric_claim",
                message="Model-inserted [source needed] marker was removed from a source-backed claim.",
                repaired=True,
            )
        )
        repairs.append(
            SpecGateRepair(
                slide_number=slide.slide_number,
                action="remove_supported_source_placeholder",
                before=before,
                after=self._slide_claim_text(slide)[:240],
            )
        )

    def _gate_slide_has_real_source(
        self,
        slide: GeneratedSlideSpec,
        bundle: DocumentBundle,
    ) -> bool:
        return any(
            ref != SOURCE_NEEDED_LABEL and self._source_ref_is_valid(ref, bundle)
            for ref in slide.source_refs
        )

    def _strip_source_needed_from_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._strip_source_needed_marker(value)
        if isinstance(value, list):
            return [self._strip_source_needed_from_value(item) for item in value]
        if isinstance(value, dict):
            return {
                key: self._strip_source_needed_from_value(item)
                for key, item in value.items()
            }
        return value

    def _strip_source_needed_marker(self, text: str) -> str:
        return re.sub(
            r"\s*\[source needed\]",
            "",
            str(text),
            flags=re.IGNORECASE,
        ).strip()

    def _gate_repair_heavy_repetition(
        self,
        slide: GeneratedSlideSpec,
        bundle: DocumentBundle,
        heavy_counts: dict[str, int],
        issues: list[SpecGateIssue],
        repairs: list[SpecGateRepair],
    ) -> None:
        archetype = self._normalize_archetype(slide.archetype or "")
        heavy = {
            "anti_patterns",
            "dependency_map",
            "framework_cycle",
            "code_panel",
            "table_reference",
            "matrix_2x2",
            "quote_sidebar",
        }
        if archetype not in heavy:
            return
        count = heavy_counts.get(archetype, 0)
        heavy_counts[archetype] = count + 1
        if count == 0:
            return
        replacement = self._gate_replacement_archetype(slide, bundle)
        before = archetype
        self._apply_selected_exhibit(
            slide,
            replacement,
            self._section_for_slide_sources(slide, bundle),
            bundle,
        )
        issues.append(
            SpecGateIssue(
                slide_number=slide.slide_number,
                category="repeated_heavy_archetype",
                message="Repeated heavy visual archetype was demoted before rendering.",
                repaired=True,
            )
        )
        repairs.append(
            SpecGateRepair(
                slide_number=slide.slide_number,
                action="demote_repeated_archetype",
                before=before,
                after=replacement,
            )
        )

    def _gate_repair_duplicate(
        self,
        slide: GeneratedSlideSpec,
        bundle: DocumentBundle,
        previous: list[tuple[int, str, set[str], str]],
        seen_source_refs: set[str],
        issues: list[SpecGateIssue],
        repairs: list[SpecGateRepair],
    ) -> None:
        duplicate = self._gate_duplicate_slide_number(slide, previous)
        if duplicate is None:
            return
        section = self._gate_unused_section(bundle, seen_source_refs, slide.slide_number)
        if section is None:
            before = self._normalize_archetype(slide.archetype or "")
            replacement = self._gate_replacement_archetype(slide, bundle)
            if replacement == before:
                replacement = "callouts" if before != "callouts" else "icon_rows"
            self._apply_selected_exhibit(
                slide,
                replacement,
                self._section_for_slide_sources(slide, bundle),
                bundle,
            )
            issues.append(
                SpecGateIssue(
                    slide_number=slide.slide_number,
                    category="duplicate_slide",
                    message=(
                        f"Slide duplicated slide {duplicate}; exhibit focus was "
                        "changed because no unused source section remained."
                    ),
                    repaired=True,
                )
            )
            repairs.append(
                SpecGateRepair(
                    slide_number=slide.slide_number,
                    action="diversify_duplicate_slide",
                    before=before,
                    after=replacement,
                )
            )
            return
        before = slide.action_title
        archetype = self._normalize_archetype(slide.archetype or "callouts")
        slide.source_refs = [self._source_ref(section, slide.slide_number - 1)]
        slide.sources = self._source_labels_for_refs(slide.source_refs, bundle) or [UPLOADED_SOURCE_LABEL]
        slide.action_title = self._clean_action_title_candidate(
            self._fallback_action_title(archetype, section.title, section)
        )
        self._apply_selected_exhibit(slide, archetype, section, bundle)
        issues.append(
            SpecGateIssue(
                slide_number=slide.slide_number,
                category="duplicate_slide",
                message=f"Slide duplicated slide {duplicate} and was moved to unused source evidence.",
                repaired=True,
            )
        )
        repairs.append(
            SpecGateRepair(
                slide_number=slide.slide_number,
                action="repair_duplicate_slide",
                before=before,
                after=slide.action_title,
            )
        )

    def _gate_unresolved_issues(
        self,
        deck: DeckSpec,
        bundle: DocumentBundle,
    ) -> list[SpecGateIssue]:
        issues: list[SpecGateIssue] = []
        for slide in deck.slides:
            claim_text = self._slide_claim_text(slide).lower()
            if "[source needed]" in claim_text:
                issues.append(
                    SpecGateIssue(
                        slide_number=slide.slide_number,
                        category="unsupported_numeric_claim",
                        message="Slide still contains [source needed] after numeric grounding.",
                        repaired=False,
                    )
                )
            invalid_refs = [
                ref
                for ref in slide.source_refs
                if ref != SOURCE_NEEDED_LABEL and not self._source_ref_is_valid(ref, bundle)
            ]
            if invalid_refs:
                issues.append(
                    SpecGateIssue(
                        slide_number=slide.slide_number,
                        category="source_refs",
                        message="Slide still has invalid source refs after gate repair.",
                        repaired=False,
                    )
                )
        return issues

    # Imperative openers that, glued onto a clause with its own finite verb, read as
    # an ungrammatical graft ("Adopt specifications must precede", "Prioritize
    # developers must shift") — the fingerprint of the old verb-prefix rewriter.
    _GRAFT_OPENERS = frozenset({
        "adopt", "prioritize", "ground", "codify", "standardize", "map", "build",
        "commit", "define", "quantify", "reduce", "reframe", "run", "structure",
        "translate", "focus", "use", "implement", "diagnose", "compare",
    })
    _FINITE_FOLLOWERS = frozenset({
        "is", "are", "was", "were", "must", "should", "can", "could", "will",
        "would", "needs", "need", "has", "have",
    })

    def _gate_title_is_weak(self, title: str) -> bool:
        """Weak == not a finished, grammatical claim. Tests grammar/completeness,
        NOT 'starts with a whitelisted verb' — so a clean declarative
        ('Memory rot compounds across handoffs') passes and the LLM narrative pass
        is no longer rejected, while verb-grafts and scaffolding are caught."""
        cleaned = " ".join(str(title).split())
        words = cleaned.split()
        if len(words) < 4 or len(words) > 16:
            return True
        lowered = cleaned.lower()
        meta_markers = (
            "to strengthen the recommendation",
            "shows measurable impact that should guide the decision",
        )
        if any(marker in lowered for marker in meta_markers):
            return True
        if re.match(r"^use the (case|need|argument|notion|idea)\b", lowered):
            return True
        if re.match(r"^use the .{2,40}\bview\b", lowered):
            return True
        # verb-prefix graft: imperative opener + a later finite verb/modal.
        if words[0].lower() in self._GRAFT_OPENERS and any(
            w.lower().strip(",.;:") in self._FINITE_FOLLOWERS for w in words[1:]
        ):
            return True
        return False

    def _gate_trim_table(self, body: list[Any]) -> list[Any]:
        trimmed: list[Any] = []
        for row in body[:6]:
            if isinstance(row, list):
                trimmed.append([self._truncate_at_word(str(cell), 64) for cell in row[:4]])
            else:
                trimmed.append(self._truncate_at_word(str(row), 120))
        return trimmed

    def _gate_replacement_archetype(
        self,
        slide: GeneratedSlideSpec,
        bundle: DocumentBundle,
    ) -> str:
        selected = self._select_exhibit_archetype(
            slide,
            self._section_for_slide_sources(slide, bundle),
            bundle,
            None,
        )
        if selected not in {
            "anti_patterns",
            "dependency_map",
            "framework_cycle",
            "code_panel",
            "table_reference",
            "matrix_2x2",
            "quote_sidebar",
        }:
            return selected
        for fallback in ["callouts", "icon_rows", "comparison_table", "checklist", "two_column"]:
            if fallback != selected:
                return fallback
        return "callouts"

    def _gate_duplicate_slide_number(
        self,
        slide: GeneratedSlideSpec,
        previous: list[tuple[int, str, set[str], str]],
    ) -> int | None:
        archetype = self._normalize_archetype(slide.archetype or "")
        exhibit_sig = self._gate_exhibit_signature(slide)
        sig_parts = exhibit_sig.count(";") + 1 if exhibit_sig else 0
        fingerprint = self._gate_slide_fingerprint(slide)
        for slide_number, prior_archetype, prior, prior_sig in previous:
            if archetype != prior_archetype:
                continue
            # Identical exhibit content (>=3 metrics/rows) is a duplicate even
            # when the action titles differ — e.g. the same KPI stat block reused.
            if exhibit_sig and exhibit_sig == prior_sig and sig_parts >= 3:
                return slide_number
            if len(fingerprint) < 6 or len(prior) < 6:
                continue
            shared = len(fingerprint & prior)
            if shared < 6:
                continue
            union = len(fingerprint | prior)
            smaller = min(len(fingerprint), len(prior))
            if (shared / union if union else 0) >= 0.72 or (shared / smaller if smaller else 0) >= 0.86:
                return slide_number
        return None

    def _gate_exhibit_signature(self, slide: GeneratedSlideSpec) -> str:
        """Stable signature of an exhibit's metrics/rows for duplicate detection."""
        exhibit = slide.exhibit_spec if isinstance(slide.exhibit_spec, dict) else {}
        parts: list[str] = []
        metrics = exhibit.get("metrics")
        if isinstance(metrics, list):
            for metric in metrics:
                if isinstance(metric, dict):
                    parts.append(
                        f"{str(metric.get('label', '')).strip().lower()}"
                        f"|{metric.get('value', '')}"
                        f"|{str(metric.get('unit', '')).strip().lower()}"
                    )
        rows = exhibit.get("rows")
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    values = "|".join(str(value) for value in row.get("values", []))
                    parts.append(f"{str(row.get('label', '')).strip().lower()}|{values}")
                elif isinstance(row, list):
                    parts.append("|".join(str(value) for value in row).lower())
        return ";".join(sorted(parts))

    def _gate_slide_fingerprint(self, slide: GeneratedSlideSpec) -> set[str]:
        text = self._slide_claim_text(slide)
        return {
            token
            for token in self._gate_normalize(text).split()
            if len(token) > 3
            and token
            not in {
                "with",
                "from",
                "that",
                "this",
                "into",
                "source",
                "evidence",
                "uploaded",
                "slide",
            }
        }

    def _gate_unused_section(
        self,
        bundle: DocumentBundle,
        seen_source_refs: set[str],
        slide_number: int,
    ) -> DocumentSection | None:
        if not bundle.sections:
            return None
        start = max(0, min(slide_number - 1, len(bundle.sections) - 1))
        ordered = bundle.sections[start:] + bundle.sections[:start]
        for index, section in enumerate(ordered):
            ref = self._source_ref(section, index)
            if ref not in seen_source_refs:
                return section
        return None

    def _gate_track_source_refs(
        self,
        slide: GeneratedSlideSpec,
        seen_source_refs: set[str],
    ) -> None:
        for ref in slide.source_refs:
            if ref and ref != SOURCE_NEEDED_LABEL:
                seen_source_refs.add(ref)

    def _gate_normalize(self, text: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", " ", str(text).lower())
        return " ".join(normalized.split())
