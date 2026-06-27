# ruff: noqa: F401
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from app.models.document import DocumentBundle, DocumentSection
from app.models.generation import ContentBlock, DeckBlueprint, DeckSpec, GeneratedSlideSpec
from app.models.outline import SlideOutline
from app.models.planning import EvidenceUnit, SourceCompression, StoryBeat, StoryMap
from app.models.template import SlideSpec, TemplateProfile
from app.services.planning.constants import (
    PLANNER_SYSTEM_PROMPT,
    SOURCE_NEEDED_LABEL,
    UPLOADED_SOURCE_LABEL,
    build_planner_system_prompt,
)
from app.services.presentation_styles import get_style


class ContextPlanningMixin:
    def _build_source_compression(
        self,
        bundle: DocumentBundle,
        quality_profile: str,
    ) -> SourceCompression:
        budget = self._compression_section_budget(quality_profile)
        summary_limit = self._compression_summary_limit(quality_profile)
        representative = self._representative_source_sections(bundle.sections, budget)
        evidence_units = [
            EvidenceUnit(
                id=self._source_ref(section, index),
                title=section.title,
                source_doc_id=section.source_doc_id,
                summary=self._source_excerpt(section.content, summary_limit),
                key_points=self._source_key_points(section.content)[:6],
                source_refs=[self._source_ref(section, index)],
            )
            for index, section in enumerate(representative)
        ]
        key_claims = self._compression_key_claims(evidence_units, bundle)
        tensions = self._compression_tensions(bundle.sections)
        metrics = [
            {
                "id": getattr(metric, "source_id", ""),
                "label": metric.label,
                "value": metric.value,
                "unit": metric.unit,
                "source_doc_id": metric.source_doc_id,
            }
            for metric in bundle.metrics[: self._compression_metric_budget(quality_profile)]
        ]
        tables = [
            {
                "id": getattr(table, "source_id", ""),
                "title": table.title or "Untitled table",
                "headers": table.headers[:8],
                "row_count": len(table.rows),
                "sample_rows": table.rows[:3],
                "source_doc_id": table.source_doc_id,
            }
            for table in bundle.tables[: self._compression_table_budget(quality_profile)]
        ]
        payload_for_estimate = {
            "evidence_units": [unit.model_dump() for unit in evidence_units],
            "key_claims": key_claims,
            "tensions": tensions,
            "metrics": metrics,
            "tables": tables,
        }
        return SourceCompression(
            quality_profile=quality_profile,
            section_count=len(bundle.sections),
            included_section_count=len(evidence_units),
            omitted_section_count=max(0, len(bundle.sections) - len(evidence_units)),
            coverage="full" if len(evidence_units) == len(bundle.sections) else "representative"
            if evidence_units
            else "none",
            estimated_tokens=max(
                1,
                round(len(json.dumps(payload_for_estimate, ensure_ascii=True)) / 4),
            ),
            document_manifest=self._planner_document_manifest(bundle),
            evidence_units=evidence_units,
            key_claims=key_claims,
            tensions=tensions,
            metrics=metrics,
            tables=tables,
            source_refs=[
                ref
                for unit in evidence_units
                for ref in unit.source_refs
                if ref and "source needed" not in ref.lower()
            ],
        )

    def _build_story_map(
        self,
        bundle: DocumentBundle,
        instructions: str,
        blueprint: DeckBlueprint,
        source_compression: SourceCompression,
        quality_profile: str,
    ) -> StoryMap:
        self._last_story_map_error = None
        story_map = self._story_map_with_llm(
            instructions,
            blueprint,
            source_compression,
            quality_profile,
        )
        if story_map is not None:
            return story_map
        if self.llm_client is not None:
            reason = self._last_story_map_error or "LLM story map was unavailable or malformed."
            return StoryMap(
                status="unavailable",
                thesis=blueprint.core_thesis,
                narrative_arc="Situation -> Complication -> Resolution",
                recommendation=self._fallback_recommendation(
                    source_compression.key_claims, instructions
                ),
                beats=[],
                source_refs=source_compression.source_refs,
                fallback_reason=reason,
            )
        reason = (
            "LLM story map was not configured."
        )
        return self._fallback_story_map(
            bundle,
            instructions,
            blueprint,
            source_compression,
            reason,
        )

    def _story_map_with_llm(
        self,
        instructions: str,
        blueprint: DeckBlueprint,
        source_compression: SourceCompression,
        quality_profile: str,
    ) -> StoryMap | None:
        if self.llm_client is None:
            return None
        prompt = (
            f"Create a {get_style(self._presentation_style).label} story map as strict JSON. Use this exact shape: "
            "{\"thesis\":\"string\",\"narrative_arc\":\"Situation -> Complication -> Resolution\","
            "\"recommendation\":\"string\",\"beats\":[{\"beat_number\":1,\"role\":\"cover|executive_summary|problem|evidence|framework|implementation|reference|decision|closing\","
            "\"claim\":\"complete action-oriented claim\",\"source_refs\":[\"source id\"],"
            "\"preferred_exhibit\":\"comparison_table|dependency_map|framework_cycle|checklist|code_panel|anti_patterns|quote_sidebar|metric_chart|table_reference|matrix_2x2|callouts|icon_rows|two_column\","
            "\"rationale\":\"short reason\"}]}. "
            "Create exactly one beat per target slide. Use the source refs from compression. "
            "Avoid duplicate claims. Prefer exhibits that fit the evidence. "
            "Do not include markdown or text outside JSON. "
            f"Quality profile: {quality_profile}. Instructions: {instructions or 'No extra instructions.'}\n"
            f"Blueprint: {json.dumps(blueprint.model_dump(), ensure_ascii=True)}\n"
            f"Source compression: {source_compression.model_dump_json()}"
        )
        try:
            payload = self.llm_client.complete_json(
                system_prompt=build_planner_system_prompt(quality_profile, self._presentation_style),
                user_prompt=prompt,
                max_tokens=self._story_map_max_tokens(quality_profile, blueprint.target_slide_count),
                temperature=0.1,
            )
        except Exception as exc:
            self._last_story_map_error = f"{type(exc).__name__}: {exc}"
            return None
        if not isinstance(payload, dict):
            self._last_story_map_error = "story map response did not contain a JSON object"
            return None
        try:
            story_map = StoryMap.model_validate(
                {
                    **payload,
                    "status": "llm",
                    "source_refs": payload.get("source_refs")
                    or self._story_source_refs(payload.get("beats", [])),
                    "fallback_reason": None,
                }
            )
        except Exception as exc:
            self._last_story_map_error = f"StoryMap validation failed: {exc}"
            return None
        if not story_map.beats:
            self._last_story_map_error = "story map contained no beats"
            return None
        story_map.beats = self._normalize_story_beats(
            story_map.beats,
            blueprint,
            source_compression,
        )
        story_map.source_refs = self._story_source_refs(
            [beat.model_dump() for beat in story_map.beats]
        )
        return story_map

    def _fallback_story_map(
        self,
        bundle: DocumentBundle,
        instructions: str,
        blueprint: DeckBlueprint,
        source_compression: SourceCompression,
        fallback_reason: str,
    ) -> StoryMap:
        evidence_units = source_compression.evidence_units
        claims = source_compression.key_claims or [
            unit.summary or unit.title for unit in evidence_units
        ]
        if not claims:
            claims = [instructions or blueprint.core_thesis or "Clarify the recommendation."]
        roles = self._narrative_roles_for_sequence(blueprint.archetype_sequence)
        beats: list[StoryBeat] = []
        for index in range(max(1, blueprint.target_slide_count)):
            role = roles[index] if index < len(roles) else "evidence"
            unit = evidence_units[index % len(evidence_units)] if evidence_units else None
            claim_source = claims[index % len(claims)]
            if role == "cover":
                claim = blueprint.core_thesis or claim_source
            elif role == "executive_summary":
                claim = self._executive_summary_claim(claims)
            elif role == "closing":
                claim = source_compression.key_claims[-1] if source_compression.key_claims else claim_source
            else:
                claim = claim_source
            refs = unit.source_refs if unit else [SOURCE_NEEDED_LABEL]
            rationale = self._phrase(
                (unit.summary if unit else "") or claim,
                "",
                limit=130,
            )
            beats.append(
                StoryBeat(
                    beat_number=index + 1,
                    role=role,
                    claim=self._truncate_title(self._claim_to_action_title(claim, role)),
                    source_refs=refs,
                    preferred_exhibit=self._preferred_exhibit_for_claim(
                        claim,
                        role,
                        blueprint.archetype_sequence[index]
                        if index < len(blueprint.archetype_sequence)
                        else "",
                        bundle,
                    ),
                    rationale=rationale,
                )
            )
        return StoryMap(
            status="fallback",
            thesis=blueprint.core_thesis or claims[0],
            narrative_arc="Situation -> Complication -> Resolution",
            recommendation=self._fallback_recommendation(claims, instructions),
            beats=self._normalize_story_beats(beats, blueprint, source_compression),
            source_refs=[
                ref
                for beat in beats
                for ref in beat.source_refs
                if ref and "source needed" not in ref.lower()
            ],
            fallback_reason=fallback_reason,
        )

    def _normalize_story_beats(
        self,
        beats: list[StoryBeat],
        blueprint: DeckBlueprint,
        source_compression: SourceCompression,
    ) -> list[StoryBeat]:
        normalized: list[StoryBeat] = []
        valid_exhibits = {
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
        }
        fallback_refs = source_compression.source_refs or [SOURCE_NEEDED_LABEL]
        roles = self._narrative_roles_for_sequence(blueprint.archetype_sequence)
        # source_ref -> substantive key points, so each beat can carry its evidence
        evidence_by_ref: dict[str, list[str]] = {}
        for unit in source_compression.evidence_units:
            points = [p for p in (unit.key_points or ([unit.summary] if unit.summary else [])) if p]
            for ref in unit.source_refs:
                evidence_by_ref[str(ref)] = points
        for index in range(max(1, blueprint.target_slide_count)):
            beat = beats[index] if index < len(beats) else None
            role = (
                beat.role
                if beat and beat.role
                else roles[index]
                if index < len(roles)
                else "evidence"
            )
            refs = [
                str(ref)
                for ref in (beat.source_refs if beat else [])
                if str(ref).strip()
            ] or [fallback_refs[index % len(fallback_refs)]]
            exhibit = (
                beat.preferred_exhibit
                if beat and beat.preferred_exhibit in valid_exhibits
                else blueprint.archetype_sequence[index]
                if index < len(blueprint.archetype_sequence)
                else "callouts"
            )
            if exhibit == "cycle":
                exhibit = "framework_cycle"
            evidence: list[str] = list(beat.evidence) if beat and beat.evidence else []
            for ref in refs:
                evidence.extend(evidence_by_ref.get(str(ref), []))
            evidence = list(dict.fromkeys(e for e in evidence if e))[:6]
            normalized.append(
                StoryBeat(
                    beat_number=index + 1,
                    role=role,
                    claim=self._truncate_title(
                        self._claim_to_action_title(
                            beat.claim if beat else blueprint.core_thesis,
                            role,
                        )
                    ),
                    source_refs=refs,
                    preferred_exhibit=exhibit,
                    rationale=beat.rationale if beat else "Filled from blueprint.",
                    evidence=evidence,
                )
            )
        return normalized

    def _compression_section_budget(self, quality_profile: str) -> int:
        if quality_profile == "fast":
            return 40
        if quality_profile == "showcase":
            return 120
        return 80

    def _compression_summary_limit(self, quality_profile: str) -> int:
        if quality_profile == "fast":
            return 220
        if quality_profile == "showcase":
            return 480
        return 320

    def _compression_metric_budget(self, quality_profile: str) -> int:
        return 12 if quality_profile == "fast" else 24 if quality_profile == "showcase" else 18

    def _compression_table_budget(self, quality_profile: str) -> int:
        return 4 if quality_profile == "fast" else 10 if quality_profile == "showcase" else 6

    def _story_map_max_tokens(self, quality_profile: str, target_slide_count: int) -> int:
        if quality_profile == "fast":
            return max(4000, min(7000, target_slide_count * 450))
        if quality_profile == "showcase":
            return max(9000, min(14000, target_slide_count * 900))
        return max(6000, min(10000, target_slide_count * 650))

    def _compression_key_claims(
        self,
        evidence_units: list[EvidenceUnit],
        bundle: DocumentBundle,
    ) -> list[str]:
        claims: list[str] = []
        for unit in evidence_units:
            for point in unit.key_points or [unit.summary]:
                claim = self._phrase(point, "", limit=130)
                if claim and claim not in claims:
                    claims.append(claim)
                if len(claims) >= 24:
                    return claims
        for item in bundle.content_inventory:
            claim = self._phrase(item, "", limit=130)
            if claim and claim not in claims:
                claims.append(claim)
            if len(claims) >= 24:
                break
        return claims

    def _compression_tensions(self, sections: list[DocumentSection]) -> list[str]:
        tensions: list[str] = []
        pattern = re.compile(
            r"\b(risk|problem|challenge|barrier|constraint|gap|however|but|unless|without|versus|vs\.?)\b",
            re.IGNORECASE,
        )
        for section in sections:
            for sentence in re.split(r"(?<=[.!?])\s+", section.content):
                cleaned = self._phrase(sentence, "", limit=145)
                if cleaned and pattern.search(cleaned) and cleaned not in tensions:
                    tensions.append(cleaned)
                if len(tensions) >= 12:
                    return tensions
        return tensions

    def _story_source_refs(self, beats: list[Any]) -> list[str]:
        refs: list[str] = []
        for beat in beats:
            if isinstance(beat, StoryBeat):
                raw_refs = beat.source_refs
            elif isinstance(beat, dict):
                raw_refs = beat.get("source_refs", [])
            else:
                raw_refs = []
            for ref in raw_refs:
                ref = str(ref)
                if ref and ref not in refs and "source needed" not in ref.lower():
                    refs.append(ref)
        return refs

    def _claim_to_action_title(self, claim: str, role: str) -> str:
        cleaned = self._phrase(claim, "Clarify the recommendation.", limit=120)
        if self._has_action_verb(cleaned):
            return cleaned
        prefixes = {
            "problem": "Diagnose",
            "evidence": "Use",
            "framework": "Structure",
            "implementation": "Adopt",
            "reference": "Codify",
            "decision": "Prioritize",
            "closing": "Commit to",
            "executive_summary": "Focus",
            "cover": "Translate",
        }
        prefix = prefixes.get(role, "Translate")
        return f"{prefix} {cleaned[:1].lower() + cleaned[1:]}"

    def _has_action_verb(self, text: str) -> bool:
        first = re.sub(r"[^A-Za-z]", "", str(text).split(" ", 1)[0]).lower()
        return first in {
            "adopt",
            "build",
            "codify",
            "commit",
            "compare",
            "define",
            "diagnose",
            "focus",
            "map",
            "prioritize",
            "quantify",
            "reduce",
            "reframe",
            "run",
            "standardize",
            "structure",
            "translate",
            "use",
        }

    def _executive_summary_claim(self, claims: list[str]) -> str:
        if len(claims) >= 2:
            return f"Focus the story on {claims[0][:70]} and {claims[1][:70]}"
        return claims[0] if claims else "Focus the story on the operating decision"

    def _fallback_recommendation(self, claims: list[str], instructions: str) -> str:
        if instructions:
            return self._phrase(instructions, "Commit to the recommended path.", limit=140)
        if claims:
            return self._phrase(claims[-1], "Commit to the recommended path.", limit=140)
        return "Commit to the recommended path with clear owners and evidence."

    def _preferred_exhibit_for_claim(
        self,
        claim: str,
        role: str,
        blueprint_archetype: str,
        bundle: DocumentBundle,
    ) -> str:
        text = f"{claim} {role} {blueprint_archetype}".lower()
        if role in {"cover", "executive_summary", "closing"}:
            return blueprint_archetype or "two_column"
        if blueprint_archetype in {"callouts", "icon_rows", "two_column"}:
            return blueprint_archetype
        if bundle.metrics and re.search(r"\b(metric|quant|percent|%|tokens?|revenue|cost|growth)\b", text):
            return "metric_chart"
        if bundle.tables and re.search(r"\b(compare|versus|vs|current|target|table)\b", text):
            return "comparison_table"
        if re.search(r"\b(trade[- ]?off|priorit|impact|readiness|matrix)\b", text):
            return "matrix_2x2"
        if re.search(r"\b(depend|flow|cause|driver|constraint|map)\b", text):
            return "dependency_map"
        if re.search(r"\b(cycle|loop|workflow|operating model|phase)\b", text):
            return "framework_cycle"
        if re.search(r"\b(step|checklist|sequence|adopt|implementation|owner)\b", text):
            return "checklist"
        if re.search(r"\b(rule|code|reference|standard|artifact)\b", text):
            return "code_panel"
        if re.search(r"\b(mindset|reframe|role|quote)\b", text):
            return "quote_sidebar"
        if blueprint_archetype in {
            "comparison_table",
            "dependency_map",
            "framework_cycle",
            "checklist",
            "code_panel",
            "anti_patterns",
            "metric_chart",
            "table_reference",
            "matrix_2x2",
            "callouts",
            "icon_rows",
            "two_column",
        }:
            return blueprint_archetype
        return "callouts"
