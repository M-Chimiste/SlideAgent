"""Critique-and-refine pass — the LLM improves the slides it already drafted.

After authoring + structural gating + the narrative title pass, this pass shows the
model, per slide, WHAT IT PRODUCED and WHAT IT WAS SUPPOSED TO BE (the story-beat
intent, the bound source evidence, the slide-type contract, and any defects the
spec gate detected) and asks it to reframe/enhance into a finished, consultant-grade
slide. It is the unified mechanism for both defect-repair and general enhancement,
and it helps on any model tier (a focused single-slide rewrite has more context than
the batched authoring call did).

Like the narrative pass it is defensive: a refinement is applied only if it passes
the weak-title gate, and with no client (or any failure) the whole pass is a graceful
no-op. Deterministic rewriting survives only as a last-resort backstop.
"""

from __future__ import annotations

import json

from app.models.document import DocumentBundle
from app.models.generation import ContentBlock, DeckSpec
from app.models.planning import SourceCompression, SpecGateReport, StoryMap
from app.services.planning.constants import build_planner_system_prompt
from app.services.presentation_styles import get_style
from app.services.slide_design.content import _normalize_items


class RefineMixin:
    def _refine_slides(
        self,
        deck: DeckSpec,
        story_map: StoryMap | None,
        source_compression: SourceCompression | None,
        spec_gate_report: SpecGateReport | None,
        bundle: DocumentBundle,
    ) -> None:
        slides = list(deck.slides)
        if self.llm_client is None or len(slides) < 2:
            self._record_refine_artifact(0, len(slides), "skipped")
            return

        # Unresolved, slide-scoped defects the spec gate deferred to the LLM.
        defects: dict[int, list[str]] = {}
        for issue in (getattr(spec_gate_report, "issues", None) or []):
            if issue.slide_number and not issue.repaired:
                defects.setdefault(issue.slide_number, []).append(issue.message)
        # Suspected mid-thought cuts: a long point with no terminal punctuation
        # usually means the author truncated a sentence to hit its char budget
        # ("...precisely because it reflects real"). Refine rewrites it whole.
        for slide in slides:
            for it in _normalize_items(slide.model_dump())[:6]:
                body_text = str(it.get("body") or "").strip()
                if len(body_text.split()) >= 8 and body_text[-1:] not in ".!?\"”)»":
                    defects.setdefault(slide.slide_number, []).append(
                        "a point appears cut mid-thought (ends without terminal "
                        f'punctuation): "...{body_text[-70:]}" — rewrite it as a '
                        "shorter COMPLETE sentence"
                    )
                    break

        allowed_numbers = self._supported_numeric_tokens(bundle)
        batch_size = 1 if getattr(self, "slide_generation_strategy", "batched") == "per_slide" else 4
        refined = 0
        for start in range(0, len(slides), batch_size):
            subset = slides[start : start + batch_size]
            try:
                results = self._refine_batch(subset, story_map, bundle, defects)
            except Exception:  # noqa: BLE001 - any failure is a safe no-op
                results = None
            for slide, result in zip(subset, results or []):
                if result and self._apply_refinement(slide, result, allowed_numbers):
                    refined += 1
        if refined:
            self._repair_repeated_action_titles(deck)
        self._record_refine_artifact(refined, len(slides), "ran")

    def _refine_batch(self, subset, story_map, bundle, defects) -> list | None:
        payloads = []
        for slide in subset:
            if self._refine_is_cover(slide):
                payloads.append(None)
                continue
            beat = self._beat_for_slide(slide, story_map) if story_map else None
            items = _normalize_items(slide.model_dump())
            payloads.append(
                {
                    "n": slide.slide_number,
                    "slide_type": slide.slide_type,
                    "produced": {
                        "action_title": slide.action_title,
                        "subheading": slide.subheading,
                        "points": [
                            {"title": it.get("title", ""), "body": it.get("body", "")}
                            for it in items[:6]
                        ],
                    },
                    "intent": {
                        "role": (beat.role if beat else slide.narrative_role) or "",
                        "claim": (beat.claim if beat else "") or "",
                        "rationale": (beat.rationale if beat else "") or "",
                    },
                    "evidence": (list(beat.evidence)[:6] if beat and getattr(beat, "evidence", None) else []),
                    "source": (self._beat_source_context([beat], bundle) if beat else []),
                    "contract": (self._beat_authoring_contract(beat) if beat else {}),
                    "fix": defects.get(slide.slide_number, []),
                }
            )
        active = [p for p in payloads if p]
        if not active:
            return [None] * len(subset)
        allowed_numbers = sorted(self._supported_numeric_tokens(bundle))[:40]
        prompt = (
            f"You are refining {get_style(self._presentation_style).label} slides you already drafted into "
            "finished, consultant-grade slides. For each slide you are given what you PRODUCED, the INTENT it "
            "must serve, the SOURCE EVIDENCE you may use, its CONTRACT (point count + char budgets), and any "
            "DEFECTS to fix.\n"
            "Rewrite each slide to be sharp and complete: action_title is ONE grammatical claim with a verb "
            "(15 words or fewer, avoid the word 'and'); subheading is a POSITIONING line — one short sentence of "
            "context framing why the claim matters to the audience, never a bare label; each point is a complete "
            "sentence grounded ONLY in the given evidence (invent no facts, names, or sources), and each body must "
            "ADD a mechanism, example, consequence, or allowed number beyond its lead — never restate the lead. "
            "Use ONLY numbers that appear in the allowed numeric tokens; never introduce a new statistic or "
            "percentage. Honor the contract's point count and char budgets — if a thought does not fit, write a "
            "SHORTER complete sentence, never a sentence cut mid-thought. Fix every listed defect. If a slide "
            "is already excellent, return it unchanged with changed=false.\n"
            'Return STRICT JSON exactly as {"slides":[{"n":<int>,"action_title":"...","subheading":"...",'
            '"items":[{"title":"2-5 word lead","body":"one complete sentence","icon":"optional 1-2 word visual concept"}],'
            '"changed":true,"reason":"..."}]} '
            "with one entry per input slide. No markdown, comments, or text outside the JSON.\n"
            f"Allowed numeric tokens: {allowed_numbers or ['none']}\n"
            f"Slides: {json.dumps(active, ensure_ascii=True)}"
        )
        response = self.llm_client.complete_json(
            system_prompt=build_planner_system_prompt("balanced", self._presentation_style),
            user_prompt=prompt,
            max_tokens=min(16000, 2000 + len(active) * 1800),
            temperature=0.2,
        )
        by_number: dict[int, dict] = {}
        for item in (response or {}).get("slides", []) if isinstance(response, dict) else []:
            if isinstance(item, dict) and item.get("n") is not None:
                try:
                    by_number[int(item["n"])] = item
                except (TypeError, ValueError):
                    continue
        return [by_number.get(slide.slide_number) for slide in subset]

    def _apply_refinement(self, slide, result: dict, allowed_numbers: set[str]) -> bool:
        """Defensive apply: only land a refinement that survives the weak-title gate
        AND introduces no ungrounded number — a bad refinement can never degrade the
        slide or invent an unsupported statistic."""

        def adds_unsupported_number(text: str) -> bool:
            return bool(self._numeric_tokens(text) - allowed_numbers)

        applied = False
        new_title = self._truncate_title(
            self._clean_action_title_candidate(str(result.get("action_title") or ""))
        )
        if (
            new_title
            and not self._refine_is_cover(slide)
            and not self._gate_title_is_weak(new_title)
            and not adds_unsupported_number(new_title)
            and new_title.casefold() != " ".join(str(slide.action_title).split()).casefold()
        ):
            slide.action_title = self._sentence_case_title(new_title)
            applied = True

        new_sub = " ".join(str(result.get("subheading") or "").split())
        if new_sub and len(new_sub.split()) >= 3 and new_sub != slide.subheading and not adds_unsupported_number(new_sub):
            slide.subheading = new_sub
            applied = True

        items = result.get("items")
        if isinstance(items, list) and items:
            clean = []
            for entry in items[:6]:
                if not isinstance(entry, dict):
                    continue
                title = " ".join(str(entry.get("title") or "").split())
                body = " ".join(str(entry.get("body") or "").split())
                icon = " ".join(str(entry.get("icon") or "").split())
                if (title or body) and not adds_unsupported_number(f"{title} {body}"):
                    point = {"title": title, "body": body}
                    if icon:
                        point["icon"] = icon
                    clean.append(point)
            if clean:
                exhibit = dict(slide.exhibit_spec) if isinstance(slide.exhibit_spec, dict) else {}
                exhibit["points"] = clean
                slide.exhibit_spec = exhibit
                # Mirror into a bullets content block so every renderer sees the
                # refined copy (keeps the spec self-consistent). Strip the lead's
                # terminal period before joining so a round-trip through the
                # reselection path never renders a "sources.: The framework" seam.
                refreshed = [
                    f"{c['title'].rstrip('.')}: {c['body']}" if c["title"] and c["body"]
                    else (c["title"] or c["body"])
                    for c in clean
                ]
                block = next((b for b in slide.content_blocks if b.type == "bullets"), None)
                if block is None:
                    block = ContentBlock(type="bullets", body=[])
                    slide.content_blocks.append(block)
                block.body = refreshed
                applied = True
        return applied

    # Layouts a user (or the model, steered by guidance) may switch a slide to.
    REGEN_LAYOUTS = (
        "callouts", "icon_rows", "two_column", "checklist", "comparison_table",
        "quote_sidebar", "matrix_2x2", "framework_cycle", "dependency_map",
        "table_reference", "metric_chart", "anti_patterns", "executive_summary",
        "closing_recommendation",
    )

    def regenerate_outline_slide(
        self,
        outline,
        bundle: DocumentBundle,
        guidance: str = "",
    ) -> dict | None:
        """LLM re-authors ONE rendered slide from its current content plus the
        user's free-text guidance. Returns validated replacement fields
        ({action_title, subheading, points, layout?}) or None (no client, bad
        response, or the rewrite failed the defensive gates)."""
        if self.llm_client is None:
            return None
        content = dict(outline.content_json or {})
        items = _normalize_items(content)
        produced = {
            "action_title": content.get("action_title") or content.get("title") or "",
            "subheading": content.get("subheading") or "",
            "layout": (outline.layout_json or {}).get("layout") or content.get("slide_type") or "",
            "points": [
                {"title": it.get("title", ""), "body": it.get("body", ""), "icon": it.get("icon") or ""}
                for it in items[:6]
            ],
        }
        source_context = self._outline_source_context(outline, bundle)
        # Numbers already on the slide stay legal even if the source bundle is
        # missing/stale, so a guided rewrite never loses an existing statistic.
        allowed_numbers = self._supported_numeric_tokens(bundle) | self._numeric_tokens(
            json.dumps(produced, ensure_ascii=True)
        )
        prompt = (
            f"You are revising ONE {get_style(self._presentation_style).label} slide the user flagged. "
            "You are given the slide as PRODUCED, its SOURCE EVIDENCE, and the USER GUIDANCE. "
            "Rewrite the slide to follow the guidance exactly while staying grounded in the evidence: "
            "action_title is ONE grammatical claim with a verb (15 words or fewer); subheading is a one-sentence "
            "positioning line; each point is {title: 2-5 word lead, body: one complete sentence that adds a "
            "mechanism/example/consequence, icon: optional 1-2 word visual concept}. "
            "Invent no facts, names, or sources; use only numbers in the allowed numeric tokens. "
            f"You may change the layout if the guidance asks for a different shape — pick from: {list(self.REGEN_LAYOUTS)}. "
            'Return STRICT JSON exactly as {"action_title":"...","subheading":"...",'
            '"points":[{"title":"...","body":"...","icon":"..."}],"layout":"one of the allowed layouts or the current one"}. '
            "No markdown or text outside the JSON.\n"
            f"USER GUIDANCE: {guidance or 'Improve this slide: sharper claim, more concrete evidence.'}\n"
            f"PRODUCED: {json.dumps(produced, ensure_ascii=True)}\n"
            f"SOURCE EVIDENCE: {json.dumps(source_context, ensure_ascii=True)}\n"
            f"Allowed numeric tokens: {sorted(allowed_numbers)[:40] or ['none']}"
        )
        try:
            response = self.llm_client.complete_json(
                system_prompt=build_planner_system_prompt("balanced", self._presentation_style),
                user_prompt=prompt,
                max_tokens=3500,
                temperature=0.3,
            )
        except Exception:  # noqa: BLE001 - regen must never crash the job
            return None
        if not isinstance(response, dict):
            return None

        def adds_unsupported_number(text: str) -> bool:
            return bool(self._numeric_tokens(text) - allowed_numbers)

        title = self._truncate_title(
            self._clean_action_title_candidate(str(response.get("action_title") or ""))
        )
        if not title or self._gate_title_is_weak(title) or adds_unsupported_number(title):
            return None
        subheading = " ".join(str(response.get("subheading") or "").split())
        points = []
        for entry in response.get("points") or []:
            if not isinstance(entry, dict):
                continue
            p_title = " ".join(str(entry.get("title") or "").split())
            p_body = " ".join(str(entry.get("body") or "").split())
            if not (p_title or p_body) or adds_unsupported_number(f"{p_title} {p_body}"):
                continue
            point = {"title": p_title, "body": p_body}
            icon = " ".join(str(entry.get("icon") or "").split())
            if icon:
                point["icon"] = icon
            points.append(point)
        if not points:
            return None
        layout = str(response.get("layout") or "").strip().lower()
        result = {
            "action_title": self._sentence_case_title(title),
            "subheading": subheading,
            "points": points[:6],
        }
        if layout in self.REGEN_LAYOUTS and layout != produced["layout"]:
            result["layout"] = layout
        return result

    def _outline_source_context(self, outline, bundle: DocumentBundle) -> list[dict]:
        refs = [
            str(ref)
            for ref in (outline.content_json or {}).get("source_refs", [])
            if str(ref).strip() and "source needed" not in str(ref).lower()
        ]
        context: list[dict] = []
        for section in bundle.sections if bundle else []:
            sid = getattr(section, "source_id", "")
            if sid and sid in refs:
                context.append({"title": section.title, "content": section.content[:900]})
        if not context and bundle and bundle.sections:
            context = [
                {"title": s.title, "content": s.content[:600]} for s in bundle.sections[:3]
            ]
        return context[:4]

    def _refine_is_cover(self, slide) -> bool:
        role = (slide.narrative_role or slide.slide_type or "").lower()
        return role == "cover" or str(slide.archetype or "").lower() == "cover"

    def _record_refine_artifact(self, refined: int, total: int, status: str) -> None:
        artifacts = getattr(self, "last_planning_artifacts", None)
        if isinstance(artifacts, dict):
            artifacts["refine-pass"] = {
                "status": status,
                "refined": refined,
                "slide_count": total,
            }
