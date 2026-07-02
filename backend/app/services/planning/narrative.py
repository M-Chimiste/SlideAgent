"""Narrative editor pass — rewrite the deck's action-title ladder.

The planner already builds a story map (one beat per slide) and shapes titles
with deterministic rules, but nothing makes the titles, read top to bottom, tell
one coherent Situation -> Complication -> Resolution story. This single small LLM
pass does exactly that: it rewrites the title ladder from the deck's thesis and
per-slide roles, then runs each rewrite back through the existing deterministic
polishers and weak-title gate so a bad rewrite can never degrade the deck. With
no client (or any failure) it is a graceful no-op.
"""

from __future__ import annotations

import json

from app.models.document import DocumentBundle
from app.models.generation import DeckSpec
from app.models.planning import StoryMap
from app.services.planning.constants import build_planner_system_prompt
from app.services.presentation_styles import get_style


class NarrativeEditorMixin:
    def _rewrite_title_ladder_for_narrative(
        self,
        deck: DeckSpec,
        story_map: StoryMap | None,
        bundle: DocumentBundle,
    ) -> None:
        original = [slide.action_title for slide in deck.slides]
        thesis = story_map.thesis if story_map else ""
        if self.llm_client is None or len(deck.slides) < 3:
            self._record_narrative_artifact(original, original, thesis, "skipped")
            return

        arc = (story_map.narrative_arc if story_map else "") or "Situation -> Complication -> Resolution"
        ladder = [
            {
                "n": slide.slide_number,
                "role": slide.narrative_role or slide.slide_type or "",
                "archetype": slide.archetype or "",
                "title": slide.action_title,
            }
            for slide in deck.slides
        ]
        prompt = (
            f"Rewrite the ACTION TITLES of this {get_style(self._presentation_style).label} deck so that, read top to bottom, they tell ONE "
            f"coherent story following the arc: {arc}. Each title must be a single assertion that advances the "
            "argument: a complete sentence with a verb, 15 words or fewer, no use of the word 'and', unique across "
            "the deck, and faithful to that slide's role and the meaning of its current title. Keep the cover "
            "(slide 1) title unchanged. Do not change the number of slides or their order. "
            'Return strict JSON exactly as {"titles":[{"n":1,"title":"..."}, ...]} with one entry per slide. '
            "No markdown, comments, reasoning, or text outside the JSON.\n"
            f"Deck thesis: {thesis}\n"
            f"Slides: {json.dumps(ladder, ensure_ascii=True)}"
        )
        try:
            payload = self.llm_client.complete_json(
                system_prompt=build_planner_system_prompt("balanced", self._presentation_style),
                user_prompt=prompt,
                max_tokens=min(3000, 500 + len(deck.slides) * 90),
                temperature=0.2,
            )
        except Exception as exc:  # noqa: BLE001 - any failure is a safe no-op
            self._record_narrative_artifact(original, original, thesis, f"error: {type(exc).__name__}")
            return
        if not isinstance(payload, dict):
            self._record_narrative_artifact(original, original, thesis, "no JSON object")
            return

        by_number: dict[int, str] = {}
        for item in payload.get("titles") or []:
            if isinstance(item, dict) and item.get("title"):
                try:
                    by_number[int(item.get("n"))] = str(item["title"])
                except (TypeError, ValueError):
                    continue
        if not by_number:
            self._record_narrative_artifact(original, original, thesis, "empty titles")
            return

        applied = 0
        for slide in deck.slides:
            candidate = by_number.get(slide.slide_number)
            if not candidate:
                continue
            role = (slide.narrative_role or slide.slide_type or "").lower()
            if role == "cover" or (slide.archetype or "").lower() == "cover":
                continue
            cleaned = self._truncate_title(self._clean_action_title_candidate(candidate))
            if not cleaned or self._gate_title_is_weak(cleaned):
                continue
            if cleaned == slide.action_title:
                continue
            slide.action_title = cleaned
            applied += 1

        # A rewrite can introduce collisions; reuse the existing de-dup pass.
        if applied:
            self._repair_repeated_action_titles(deck)
        # Normalize Title-Cased titles (from generation or the rewrite) to a
        # consistent sentence case, preserving proper nouns. Skip the cover.
        for slide in deck.slides:
            role = (slide.narrative_role or slide.slide_type or "").lower()
            if role == "cover" or (slide.archetype or "").lower() == "cover":
                continue
            slide.action_title = self._sentence_case_title(slide.action_title)
        new_titles = [slide.action_title for slide in deck.slides]
        self._record_narrative_artifact(
            original, new_titles, thesis, f"applied {applied}/{len(deck.slides)}"
        )

    def _record_narrative_artifact(
        self,
        before: list[str],
        after: list[str],
        thesis: str,
        status: str,
    ) -> None:
        artifacts = getattr(self, "last_planning_artifacts", None)
        if isinstance(artifacts, dict):
            artifacts["narrative-pass"] = {
                "status": status,
                "thesis": thesis,
                "before": before,
                "after": after,
            }
