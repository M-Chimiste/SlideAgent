# ruff: noqa: F401
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from app.models.document import DocumentBundle, DocumentMetric, DocumentSection
from app.models.generation import ContentBlock, DeckBlueprint, DeckSpec, GeneratedSlideSpec
from app.models.outline import SlideOutline
from app.models.template import SlideSpec, TemplateProfile
from app.services.planning.constants import (
    PLANNER_SYSTEM_PROMPT,
    SOURCE_NEEDED_LABEL,
    UPLOADED_SOURCE_LABEL,
)


class PlanningRepairMixin:
    def _repair_dangling_fragment(self, text: str) -> str:
        cleaned = " ".join(str(text).split()).strip(" -:;")
        if not cleaned:
            return ""
        adjacent_connector = re.search(
            r"\b(?:as|at|by|for|from|in|into|of|on|to|with|without)\s+"
            r"(?:as|at|by|for|from|in|into|of|on|to|with|without)\b",
            cleaned,
            flags=re.IGNORECASE,
        )
        if adjacent_connector and adjacent_connector.start() >= 12:
            cleaned = cleaned[: adjacent_connector.start()].rstrip(" ,;:")
        clause_match = re.search(
            r",\s+(?:which|that|where|while|because|as)\b[^,.;:]*$",
            cleaned,
            flags=re.IGNORECASE,
        )
        if clause_match and self._ends_with_dangling_token(cleaned[clause_match.start() :]):
            cleaned = cleaned[: clause_match.start()].rstrip(" ,;:")
        incomplete_quality_goal = re.search(
            r"\s+to\s+(?:ensure|enable|keep|make)\s+"
            r"(?:reliable|scalable|effective|successful|consistent|repeatable)"
            r"(?:,\s*(?:traceable|reliable|scalable|effective|successful|consistent|repeatable))*$",
            cleaned,
            flags=re.IGNORECASE,
        )
        if incomplete_quality_goal and incomplete_quality_goal.start() >= 12:
            cleaned = cleaned[: incomplete_quality_goal.start()].rstrip(" ,;:")
        words = cleaned.split()
        while len(words) > 4 and self._is_dangling_token(words[-1]):
            words.pop()
        cleaned = " ".join(words).rstrip(" ,;:")
        return cleaned

    def _ends_with_dangling_token(self, text: str) -> bool:
        words = str(text).split()
        return bool(words and self._is_dangling_token(words[-1]))

    def _is_dangling_token(self, token: str) -> bool:
        cleaned = re.sub(r"[^A-Za-z]", "", token).lower()
        return cleaned in {
            "a",
            "an",
            "the",
            "as",
            "of",
            "to",
            "for",
            "from",
            "with",
            "without",
            "into",
            "onto",
            "in",
            "on",
            "at",
            "by",
            "has",
            "have",
            "and",
            "or",
            "but",
            "need",
            "needs",
            "provide",
            "provides",
            "which",
            "that",
            "where",
            "when",
            "while",
            "because",
            "than",
            "prior",
            "optimal",
            # comparative/prepositional stragglers a 15-word cut leaves behind
            # ("...where validated truth already exists rather")
            "rather",
            "versus",
            "vs",
            "instead",
            "toward",
            "towards",
            "across",
            "between",
            "against",
            "unlike",
            "via",
            "per",
            "through",
            "such",
            "either",
            "neither",
            "both",
        }

    def _truncate_title(self, title: str) -> str:
        words = title.rstrip(".").split()
        truncated = " ".join(words[:15] if len(words) > 15 else words).rstrip(".,;:")
        repaired = self._repair_dangling_fragment(truncated)
        repaired = self._normalize_title_acronyms(repaired)
        return self._normalize_title_case(repaired)

    # Minor words a headline lowercases (matches the reference deck's AP-style
    # titles, e.g. "The Problem with Vibe Coding"), unless they lead the title.
    _TITLE_MINOR_WORDS = frozenset(
        {
            "a", "an", "the", "and", "but", "or", "nor", "for", "so", "yet",
            "as", "at", "by", "in", "of", "on", "to", "up", "off", "per",
            "via", "vs", "with", "from", "into", "onto", "over", "than",
            "while", "when", "where", "plus", "versus", "without", "across",
        }
    )

    def _normalize_title_case(self, title: str) -> str:
        """Lowercase over-capitalized minor words so a Title-Cased model title
        reads as a refined headline. Sentence-case titles and acronyms/coined
        terms are left untouched."""
        words = title.split()
        if len(words) < 3:
            return title
        capitalized = sum(1 for word in words if word[:1].isupper())
        # Only touch titles the model rendered in Title Case; leave sentence case.
        if capitalized < max(3, int(len(words) * 0.6)):
            return title
        normalized: list[str] = []
        for index, word in enumerate(words):
            stripped = word.strip(",.;:!?()").lower()
            keep_caps = (
                index == 0
                or index == len(words) - 1
                or stripped not in self._TITLE_MINOR_WORDS
                or (index > 0 and words[index - 1].endswith(":"))
                # Preserve acronyms / mixed-caps tokens (AI, JWT, McKinsey), but
                # not a lone capital "A", which is just an over-capitalized article.
                or (len(stripped) >= 2 and word.isupper())
                or any(char.isupper() for char in word[1:])
            )
            if keep_caps:
                normalized.append(word)
            else:
                normalized.append(word.lower())
        return " ".join(normalized)

    def _normalize_title_acronyms(self, title: str) -> str:
        replacements = {
            "ai": "AI",
            "api": "API",
            "llm": "LLM",
            "ui": "UI",
            "ux": "UX",
        }
        normalized = title
        for token, replacement in replacements.items():
            normalized = re.sub(
                rf"\b{token}\b",
                replacement,
                normalized,
                flags=re.IGNORECASE,
            )
        return normalized

    def _default_pattern(self, index: int) -> str:
        return [
            "Important context disappears between handoffs.",
            "Recommendations look plausible before evidence is checked.",
            "Teams cannot reproduce the reasoning behind decisions.",
        ][index]

    def _enrich_deck_specs(
        self, deck: DeckSpec, blueprint: DeckBlueprint, bundle: DocumentBundle
    ) -> None:
        sequence = blueprint.archetype_sequence or []
        roles = self._narrative_roles_for_sequence(sequence)
        source_metrics = self._pick_metrics(bundle.metrics, count=4)
        for index, slide in enumerate(deck.slides):
            if not slide.archetype:
                slide.archetype = self._archetype_from_layout(self._layout_for_slide(slide))
            slide.archetype = self._normalize_archetype(slide.archetype)
            if not slide.narrative_role:
                slide.narrative_role = (
                    self._role_for_archetype(slide.archetype)
                    or (roles[index] if index < len(roles) else "evidence")
                )
            if not slide.source_refs:
                slide.source_refs = blueprint.source_coverage_map.get(
                    str(index + 1),
                    slide.sources or [UPLOADED_SOURCE_LABEL],
                )
            if not slide.design_intent:
                slide.design_intent = self._design_intent(slide.archetype)
            if not slide.exhibit_spec or self._exhibit_is_incomplete(slide):
                slide.exhibit_spec = self._derive_exhibit_spec(slide)
            self._remove_placeholder_text(slide)
            self._repair_underfilled_exhibit(slide, source_metrics)
            self._sync_diagram_spec(slide)
            self._sync_content_blocks_from_exhibit(slide)

    def _normalize_archetype(self, archetype: str) -> str:
        normalized = archetype.strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "cycle": "framework_cycle",
            "process": "framework_cycle",
            "reference_table": "table_reference",
            "table": "comparison_table",
            "comparison": "comparison_table",
            "metric": "metric_chart",
            "chart": "metric_chart",
            "matrix": "matrix_2x2",
            "2x2": "matrix_2x2",
            "2x2_matrix": "matrix_2x2",
            "anti_pattern": "anti_patterns",
            "quote": "quote_sidebar",
            "closing": "closing_recommendation",
            "recommendation": "closing_recommendation",
        }
        return aliases.get(normalized, normalized or "two_column")

    def _archetype_from_layout(self, layout: str) -> str:
        mapping = {
            "chart": "metric_chart",
            "process": "table_reference",
            "two_column": "two_column",
            "icon_grid": "two_column",
            "icon_rows": "two_column",
        }
        return mapping.get(layout, layout)

    def _role_for_archetype(self, archetype: str) -> str | None:
        role_map = dict(
            zip(
                self._archetype_sequence(16),
                self._narrative_roles_for_sequence(self._archetype_sequence(16)),
            )
        )
        return role_map.get(archetype)

    def _repair_model_titles(self, deck: DeckSpec) -> None:
        for slide in deck.slides:
            title = " ".join(slide.action_title.split())
            title = title.rstrip(".")
            title = self._strip_meta_title_text(title)
            if self._normalize_archetype(slide.archetype or "") == "cover":
                title = self._repair_cover_title(title, deck.deck_title)
                if title.casefold() == " ".join(str(deck.deck_title).split()).casefold():
                    slide.action_title = title
                    continue
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
            # Canned weak-title rewriting is no-LLM-fallback-only now; on the LLM
            # path titles are owned by the author + narrative + refine passes (with
            # a final deterministic backstop), never grafted from canned banks here.
            if self.llm_client is None:
                title = self._repair_weak_action_title(slide, title)
            slide.action_title = self._clean_action_title_candidate(title)

    def _repair_cover_title(self, title: str, deck_title: str) -> str:
        cleaned_title = " ".join(str(title).split())
        cleaned_deck_title = " ".join(str(deck_title).split())
        if not cleaned_title or not cleaned_deck_title:
            return cleaned_title
        # Cover slides should carry the deck name, not an action-title fragment
        # or subtitle that the model promoted into the title field.
        return cleaned_deck_title

    def _title_has_awkward_frame(self, title: str) -> bool:
        """Narrow check for scaffolding-style openers (not the broad weak-title
        heuristic, which over-flags perfectly good assertions)."""
        lowered = " ".join(str(title).lower().split())
        return bool(
            re.match(r"^use the (case|need|argument|notion|idea)\b", lowered)
            or re.match(r"^use the .{2,40}\bview\b", lowered)
            or re.match(r"^make the case for\b", lowered)
        )

    def _finalize_action_titles(self, deck: DeckSpec) -> None:
        """Final guard run after source polish and the narrative pass — those
        stages run after the earlier dedup, so they can introduce a near-duplicate
        subject or an awkward framing title that nothing else catches. Triggers
        only on the specific signals (shared four-word subject prefix, awkward
        scaffolding opener), not the broad weak-title heuristic.
        """
        seen: set[str] = set()
        seen_prefixes: set[str] = set()
        for slide in deck.slides:
            archetype = self._normalize_archetype(slide.archetype or "")
            role = (slide.narrative_role or slide.slide_type or "").lower()
            is_cover = role == "cover" or archetype == "cover"
            title = slide.action_title.strip()
            key = title.casefold()
            prefix = self._title_subject_prefix(title)
            awkward = (not is_cover) and self._title_has_awkward_frame(title)
            collides = key in seen or bool(prefix and prefix in seen_prefixes)
            if awkward or collides:
                replacement = self._unique_action_title(slide, seen, seen_prefixes)
                if replacement and not self._title_has_awkward_frame(replacement):
                    slide.action_title = self._truncate_title(replacement)
            seen.add(slide.action_title.casefold())
            final_prefix = self._title_subject_prefix(slide.action_title)
            if final_prefix:
                seen_prefixes.add(final_prefix)

    def _repair_repeated_action_titles(self, deck: DeckSpec) -> None:
        seen: set[str] = set()
        seen_prefixes: set[str] = set()
        for slide in deck.slides:
            key = slide.action_title.strip().casefold()
            prefix = self._title_subject_prefix(slide.action_title)
            if key not in seen and not (prefix and prefix in seen_prefixes):
                seen.add(key)
                if prefix:
                    seen_prefixes.add(prefix)
                continue
            replacement = self._unique_action_title(slide, seen, seen_prefixes)
            slide.action_title = self._truncate_title(replacement)
            seen.add(slide.action_title.casefold())
            new_prefix = self._title_subject_prefix(slide.action_title)
            if new_prefix:
                seen_prefixes.add(new_prefix)

    def _title_subject_prefix(self, title: str) -> str:
        """The leading four-word subject phrase. Two slides that open with the
        same four words make the same point and read as near-duplicates."""
        words = str(title or "").lower().split()
        if len(words) < 5:
            return ""
        return " ".join(word.strip(",.;:\"'") for word in words[:4])

    def _unique_action_title(
        self,
        slide: GeneratedSlideSpec,
        seen: set[str],
        seen_prefixes: set[str] | None = None,
    ) -> str:
        seen_prefixes = seen_prefixes or set()
        for candidate in self._action_title_candidates(slide):
            replacement = self._clean_action_title_candidate(candidate)
            if not replacement or replacement.casefold() in seen:
                continue
            prefix = self._title_subject_prefix(replacement)
            if prefix and prefix in seen_prefixes:
                continue
            return replacement
        archetype = self._normalize_archetype(slide.archetype or "")
        role = (slide.narrative_role or archetype or "decision").replace("_", " ")
        return self._clean_action_title_candidate(
            f"Use {role} evidence to choose the next step"
        )

    def _action_title_candidates(self, slide: GeneratedSlideSpec) -> list[str]:
        candidates: list[str] = []
        if self.llm_client is not None:
            # LLM path: reuse the slide's own authored sentences as replacement
            # titles so dedup stays grounded in model content instead of
            # reaching for canned vocabulary.
            candidates.extend(self._authored_title_candidates(slide))
        candidates.extend(self._alternate_action_titles(slide))
        candidates.extend(
            [
                self._repair_weak_action_title(slide, self._distinct_action_title(slide)),
                self._distinct_action_title(slide),
            ]
        )
        return candidates

    def _authored_title_candidates(self, slide: GeneratedSlideSpec) -> list[str]:
        """Complete sentences already authored on the slide (exhibit point bodies,
        content-block bullets) that can stand alone as an action title."""
        texts: list[str] = []
        exhibit = slide.exhibit_spec if isinstance(slide.exhibit_spec, dict) else {}
        for key in ("points", "items", "steps", "cards", "rows"):
            seq = exhibit.get(key)
            if isinstance(seq, list) and seq:
                for entry in seq:
                    if isinstance(entry, dict):
                        texts.append(
                            str(
                                entry.get("body")
                                or entry.get("text")
                                or entry.get("description")
                                or ""
                            )
                        )
                    else:
                        texts.append(str(entry))
                break
        for block in slide.content_blocks:
            texts.extend(str(item) for item in block.body if isinstance(item, str))
        candidates: list[str] = []
        for text in texts:
            cleaned = " ".join(str(text).split()).rstrip(".")
            if 5 <= len(cleaned.split()) <= 16 and not self._gate_title_is_weak(cleaned):
                candidates.append(cleaned)
        return candidates

    def _clean_action_title_candidate(self, title: str) -> str:
        cleaned = self._strip_meta_title_text(title).strip()
        cleaned = cleaned.replace("...", " ").replace("…", " ")
        cleaned = " ".join(cleaned.split())
        cleaned = self._repair_dangling_fragment(cleaned)
        if " and " in cleaned.lower():
            left, right = cleaned.split(" and ", 1)
            if len(left.split()) >= 4 and len(right.split()) >= 3:
                cleaned = left
        return self._truncate_title(cleaned)

    def _alternate_action_titles(self, slide: GeneratedSlideSpec) -> list[str]:
        archetype = self._normalize_archetype(slide.archetype or "")
        intent = self._slide_intent_text(slide)
        context = self._slide_context_label(slide)
        candidates: list[str] = []
        if any(token in intent for token in ("acceptance criteria", "specification")):
            candidates.extend(self._acceptance_criteria_titles(archetype))
        if any(
            token in intent
            for token in ("context window", "token", "finite", "limit", "memory")
        ):
            candidates.extend(
                self._context_limit_titles(archetype)
            )
        if self._is_memory_text(intent):
            candidates.extend(self._memory_action_titles(archetype))
        candidates.extend(
            {
                "checklist": [
                    "Turn next steps into an executable transition checklist",
                    "Make implementation gates explicit before work starts",
                ],
                "code_panel": [
                    "Codify the operating rule where teams already work",
                    "Translate source evidence into reusable team rules",
                ],
                "table_reference": [
                    "Standardize core artifacts for persistent context",
                    "Standardize recurring decisions as a reusable reference",
                ],
                "comparison_table": [
                    "Compare the current model with the target operating model",
                    "Show why managed execution beats ad hoc prompting",
                ],
                "dependency_map": [
                    "Map the dependencies that determine reliable output",
                    "Expose context handoffs before the workflow breaks",
                ],
                "framework_cycle": [
                    "Run the operating cycle with explicit review gates",
                    "Reset the workflow before context begins to drift",
                ],
                "section_divider": [
                    "Shift From Prompting to Management",
                    "Shift From Diagnosis to Execution",
                ],
                "quote_sidebar": [
                    "Reframe the operating model around persistent context",
                    "Translate the mindset shift into management behavior",
                ],
                "closing_recommendation": [
                    "Commit to the recommendation with named ownership",
                    "Move from pilot enthusiasm to an operating mandate",
                ],
                "metric_chart": [
                    "Quantify context-window limits before relying on model memory",
                    "Use context limits to justify persistent memory",
                ],
                "chart": [
                    "Quantify context-window limits before relying on model memory",
                    "Use context limits to justify persistent memory",
                ],
            }.get(archetype, [])
        )
        if context:
            candidates.append(
                f"Ground the next decision in {self._clean_title_subject(context)}"
            )
        candidates.append("Anchor the recommendation in the source evidence")
        return candidates

    def _acceptance_criteria_titles(self, archetype: str) -> list[str]:
        by_archetype = {
            "checklist": [
                "Use acceptance criteria as pre-execution review gates",
                "Use acceptance criteria to make work reviewable before execution",
            ],
            "code_panel": [
                "Codify acceptance criteria as reusable team rules",
                "Translate specifications into rules the agent can follow",
            ],
            "table_reference": [
                "Standardize acceptance criteria as a reusable reference",
            ],
            "comparison_table": [
                "Compare implicit prompts with explicit acceptance criteria",
            ],
        }
        return by_archetype.get(
            archetype,
            [
                "Define acceptance criteria before execution begins",
                "Use acceptance criteria to make work reviewable before execution",
                "Translate specifications into rules the agent can follow",
            ],
        )

    def _memory_action_titles(self, archetype: str) -> list[str]:
        by_archetype = {
            "checklist": [
                "Implement memory-bank upkeep through a short checklist",
                "Keep context current through explicit update gates",
            ],
            "code_panel": [
                "Codify memory-bank upkeep where teams already work",
                "Translate memory rules into reusable team instructions",
            ],
            "table_reference": [
                "Standardize memory-bank files around update triggers",
            ],
            "dependency_map": [
                "Map memory handoffs before context begins to decay",
            ],
        }
        return by_archetype.get(
            archetype,
            ["Use memory bank files so teams inherit context"],
        )

    def _context_limit_titles(self, archetype: str) -> list[str]:
        by_archetype = {
            "chart": [
                "Quantify context-window limits before relying on model memory",
                "Use context limits to justify persistent memory",
            ],
            "metric_chart": [
                "Quantify context-window limits before relying on model memory",
                "Use context limits to justify persistent memory",
            ],
            "comparison_table": [
                "Compare finite model context with persistent team memory",
            ],
            "code_panel": [
                "Codify memory rules before model context expires",
            ],
        }
        return by_archetype.get(
            archetype,
            ["Use finite context limits to justify persistent memory"],
        )

    def _distinct_action_title(self, slide: GeneratedSlideSpec) -> str:
        archetype = self._normalize_archetype(slide.archetype or "")
        intent = self._slide_intent_text(slide)
        context = self._slide_context_label(slide)
        if archetype in {"code_panel", "reference"}:
            if any(token in intent for token in ("cycle", "loop", "phase", "workflow")):
                return "Codify the operating cycle as reusable rules"
            if any(token in intent for token in ("update", "stale", "reset")):
                return "Codify memory updates before context goes stale"
            if any(token in intent for token in ("markdown", "specification", "rules file")):
                return "Codify markdown rules where teams already work"
            if context:
                return f"Codify {context.lower()} into reusable operating rules"
            return "Codify the next reference artifact for the team"
        if archetype == "dependency_map":
            if any(token in intent for token in ("update", "stale", "protocol")):
                return "Map context updates to preserve workflow reliability"
            if context:
                return f"Map {context.lower()} into context dependencies"
        if archetype == "comparison_table":
            if any(token in intent for token in ("cycle", "loop", "phase")):
                return "Contrast the operating loop with ad hoc execution"
            if context:
                return f"Contrast {context.lower()} with the target operating model"
        if archetype == "section_divider":
            return self._section_divider_title(intent)
        if archetype == "table_reference":
            if self._is_memory_text(intent):
                return "Standardize Memory Bank files as a reusable reference"
            if context:
                return f"Standardize {context.lower()} as a reusable reference"
        if archetype in {"chart", "metric_chart"}:
            if any(
                token in intent
                for token in ("context window", "token", "finite", "limit", "memory")
            ):
                return "Quantify context-window limits before relying on model memory"
            return "Quantify the operating signal before scaling AI work"
        if context:
            return f"Ground the next decision in {self._clean_title_subject(context)}"
        return "Anchor the recommendation in the source evidence"

    def _clean_title_subject(self, text: str) -> str:
        """Trim leading framing ('the case for ...', bare articles) so the subject
        reads naturally when interpolated mid-title."""
        subject = " ".join(str(text or "").split()).strip().strip(".")
        subject = re.sub(
            r"^(the case for|the need for|a case for|the view on|the|a|an)\s+",
            "",
            subject,
            flags=re.I,
        )
        return subject or "the source evidence"

    def _sentence_case_title(self, title: str) -> str:
        """Normalize a Title-Cased title to sentence case for a consistent voice.

        Only titles that are *mostly* capitalized (a styling artifact from the
        model) are converted; titles that are already sentence case with a few
        capitalized words are left alone, so proper nouns like "Memory Bank" or
        "Agentic Coding" survive. Acronyms (all-caps) and internal-caps names
        (GitHub, iOS) are preserved within converted titles.
        """
        words = str(title or "").split()
        if len(words) < 3:
            return title
        minor = {
            "a", "an", "the", "and", "or", "but", "for", "nor", "of", "to", "in",
            "on", "at", "by", "as", "vs", "via", "with", "from", "into", "over",
            "is", "are", "that", "than",
        }
        significant = [
            w for w in words[1:]
            if len(w.strip(".,;:'\"")) > 3 and w.lower().strip(".,;:'\"") not in minor
        ]
        if not significant:
            return title
        capped = sum(1 for w in significant if w[:1].isupper())
        if capped / len(significant) < 0.65:
            return title
        out = [words[0]]
        for word in words[1:]:
            core = word.strip(".,;:'\"")
            is_acronym = (core.isupper() and len(core) >= 2) or bool(re.fullmatch(r"[A-Z0-9]{2,}s", core))
            if is_acronym or re.search(r"[a-z][A-Z]", core):
                out.append(word)  # acronym (incl. plural) or internal-caps name
            elif word[:1].isupper():
                out.append(word[0].lower() + word[1:])
            else:
                out.append(word)
        return " ".join(out)

    def _slide_context_label(self, slide: GeneratedSlideSpec) -> str:
        candidates = [slide.subheading, slide.design_intent or ""]
        # Fall back to the lead exhibit item so the subject stays grounded in the
        # slide's own content instead of dropping to a generic last-resort title.
        exhibit = slide.exhibit_spec or {}
        if isinstance(exhibit, dict):
            for key in ("points", "items", "cards", "rows", "steps"):
                seq = exhibit.get(key)
                if isinstance(seq, list) and seq:
                    first = seq[0]
                    label = (
                        (first.get("title") or first.get("label") or first.get("name") or "")
                        if isinstance(first, dict)
                        else str(first)
                    )
                    if label:
                        candidates.append(str(label))
                    break
        for candidate in candidates:
            cleaned = re.sub(r"^evidence\s+from\s+", "", candidate, flags=re.IGNORECASE)
            cleaned = self._clean_section_title(cleaned)
            if cleaned and cleaned.lower() not in {"uploaded source", "source"}:
                return self._truncate_at_word(cleaned, 42).removesuffix("...")
        return ""

    def _repair_weak_action_title(self, slide: GeneratedSlideSpec, title: str) -> str:
        normalized = self._strip_meta_title_text(title).strip()
        intent = f"{normalized} {self._slide_intent_text(slide)}"
        intent_lower = intent.lower()
        word_count = len(normalized.split())
        archetype = self._normalize_archetype(slide.archetype or "")
        benchmark_repair = self._benchmark_title_repair(intent_lower)
        if benchmark_repair:
            return benchmark_repair
        section_divider_needs_repair = archetype == "section_divider" and (
            word_count > 6
            or bool(
                re.match(
                    r"^(translate|turn|explain)\s+why\b",
                    normalized,
                    flags=re.IGNORECASE,
                )
            )
        )
        table_reference_needs_repair = archetype == "table_reference" and bool(
            re.search(
                r"\b(?:core files|six[- ]file|six core|memory bank)\b"
                r".*\b(?:as|hierarchy|reference)\b",
                normalized,
                flags=re.IGNORECASE,
            )
        )
        closing_needs_repair = (
            archetype == "closing_recommendation"
            and not bool(
                re.match(
                    r"^(commit|adopt|approve|launch|move|recommend)\b",
                    normalized,
                    flags=re.IGNORECASE,
                )
            )
        ) or (
            archetype == "closing_recommendation"
            and bool(
                re.match(
                    r"^commit\s+to\s+the\s+recommendation\b",
                    normalized,
                    flags=re.IGNORECASE,
                )
            )
            and bool(
                re.search(
                    r"\b(benchmark|harness|model contract|ground truth|evaluation)\b",
                    intent_lower,
                    flags=re.IGNORECASE,
                )
            )
        )
        generic = (
            self._title_contains_meta_instruction(normalized)
            or word_count <= 4
            or "..." in normalized
            or section_divider_needs_repair
            or table_reference_needs_repair
            or closing_needs_repair
            or bool(re.match(r"^use\s+.*\bguide\b", normalized, flags=re.IGNORECASE))
            or bool(
                re.match(
                    r"^(turn\s+reference|reference)\b",
                    normalized,
                    flags=re.IGNORECASE,
                )
            )
            or self._has_embedded_clause_title(normalized)
            or bool(
                re.match(
                    r"^(provide|support|end|name|make|detail)\b",
                    normalized,
                    flags=re.IGNORECASE,
                )
            )
            or bool(re.match(r"^review\s+reviewer\s+mode\b", normalized, flags=re.IGNORECASE))
            or bool(
                re.match(
                    r"^(define|quantify|enforce|structure|create|build|show|explain|"
                    r"execute|operationalize|reference|use)\b",
                    normalized,
                    flags=re.IGNORECASE,
                )
                and not re.search(
                    r"\b(to|so|because|with|before|after|through|into|against|across)\b",
                    normalized,
                    flags=re.IGNORECASE,
                )
            )
        )
        if not generic and not normalized.lower().endswith((" for reliable", " for scalable")):
            return normalized
        if archetype == "section_divider":
            return self._section_divider_title(intent_lower)
        if archetype == "closing_recommendation":
            if normalized.lower().startswith("end with"):
                return "Commit to the recommendation with named ownership"
            return self._closing_recommendation_title(intent_lower)
        if archetype == "table_reference" and self._is_memory_text(intent_lower):
            return "Standardize Memory Bank files as a reusable reference"
        if self._has_embedded_clause_title(normalized):
            replacement = self._distinct_action_title(slide)
            if replacement.casefold() != normalized.casefold():
                return self._truncate_title(replacement)
        if archetype == "table_reference":
            context = self._slide_context_label(slide)
            if context:
                return f"Standardize {context.lower()} as a reusable reference"
        if "specification" in intent_lower or "acceptance criteria" in intent_lower:
            return "Define acceptance criteria before execution begins"
        if archetype in {"code_panel", "reference"} and (
            self._is_memory_text(intent_lower)
        ):
            return "Codify memory rules where teams already work"
        if archetype in {"code_panel", "reference"} and (
            "cycle" in intent_lower or "loop" in intent_lower or "phase" in intent_lower
        ):
            return "Codify the operating cycle as reusable rules"
        if "agentic cycle" in intent_lower or "operating cycle" in intent_lower:
            return "Run the operating cycle with explicit review gates"
        if archetype == "framework_cycle":
            return "Run the operating cycle with explicit review gates"
        if archetype == "checklist" and (
            self._is_memory_text(intent_lower)
        ):
            return "Implement the memory bank through a short operating checklist"
        if archetype == "checklist":
            return "Implement next steps through a short operating checklist"
        if archetype == "code_panel":
            return "Codify operating rules where teams already work"
        if archetype == "quote_sidebar":
            if "reviewer mode" in intent_lower:
                return "Use reviewer mode as the default quality gate"
            return "Reframe the operating model around persistent context"
        if archetype == "table_reference" and self._is_memory_text(intent_lower):
            return "Standardize Memory Bank roles through refresh-triggered files"
        if self._is_memory_text(intent_lower):
            return "Use memory bank files so teams inherit context"
        if "industry shift" in intent_lower or "adoption" in intent_lower:
            return "Quantify adoption pressure before redesigning delivery"
        if archetype == "comparison_table":
            return "Compare the current model with the target operating model"
        if archetype == "table_reference":
            return "Standardize core artifacts for persistent context"
        if archetype == "closing_recommendation":
            return "Commit to the recommendation with named ownership"
        replacement = self._distinct_action_title(slide)
        if replacement.casefold() != normalized.casefold():
            return self._truncate_title(replacement)
        return "Use the source evidence to choose the next step"

    def _benchmark_title_repair(self, intent: str) -> str:
        if (
            "instead of looking at using models" in intent
            or "harness-centric view" in intent
            or "harness centric view" in intent
        ):
            return "Harness-centric design turns existing workflows into evaluation evidence"
        if "introduction" in intent and (
            "benchmark" in intent or "frontier model" in intent or "leaderboard" in intent
        ):
            return "Static benchmarks need operational validity beyond leaderboards"
        if "benchmarks are foundational" in intent:
            return "Current benchmarks need harnesses that discover operational truth"
        if "this white paper proposes" in intent:
            return "Harness-centric design turns existing workflows into evaluation evidence"
        if "if we have capable frontier models" in intent:
            return "Synthetic benchmarks cannot substitute for validated operating evidence"
        if "with the proliferation of large language models" in intent:
            return "Five harness layers connect contracts, data, execution, and review"
        if "a harness-centric approach inverts this problem" in intent:
            return "Implicit ground truth discovery turns existing evidence into benchmarks"
        if "the proliferation of ai models across enterprise applications" in intent:
            return "Shift leaders from manual labeling to systematic discovery"
        if "executive summary" in intent and (
            "benchmark" in intent or "evaluation" in intent or "harness" in intent
        ):
            return "Current benchmarks need harnesses that discover operational truth"
        if "generic benchmarks" in intent or "generic public evaluations" in intent:
            return "Use real use-case benchmarks instead of generic public evaluations"
        if "operationalizing evaluation" in intent or "evaluation lifecycle" in intent:
            return "Harness interfaces standardize benchmark execution across domains"
        if "commit to the recommendation" in intent and (
            "benchmark" in intent
            or "evaluation" in intent
            or "harness" in intent
            or "ground truth" in intent
            or "model contract" in intent
        ):
            return "Build evaluation systems around real use cases"
        if "conclusion and future directions" in intent:
            return "Govern agent-assisted benchmark discovery before deployment"
        if "future directions" in intent and (
            "data catalog" in intent
            or "confidence calibration" in intent
            or "benchmark" in intent
        ):
            return "Data catalogs shape benchmark governance through confidence calibration"
        if "case for implicit ground truth" in intent:
            return "Implicit ground truth discovery turns existing evidence into benchmarks"
        if "harness interface" in intent:
            return "Harness interfaces standardize benchmark execution across domains"
        if "manual labeling" in intent and "systematic discovery" in intent:
            return "Shift leaders from manual labeling to systematic discovery"
        if ("business case" in intent or "shifting from manual" in intent) and (
            "manual" in intent or "labeling" in intent or "discovery" in intent
        ):
            return "Shift leaders from manual labeling to systematic discovery"
        if "confidence calibration" in intent or "ground truth certainty" in intent:
            return "Calibrate confidence against varying ground-truth certainty"
        if "organizations must build evaluation systems" in intent or (
            "real use cases" in intent and "static" in intent
        ):
            return "Build evaluation systems around real use cases"
        if "benchmark governance" in intent:
            return "Build evaluation systems around real use cases"
        if "future deployment" in intent and "data catalog" in intent:
            return "Connect enterprise data catalogs to benchmark discovery"
        return ""

    def _section_divider_title(self, intent: str) -> str:
        intent_lower = intent.lower()
        if any(token in intent_lower for token in ("chatbot", "employee", "manager")):
            return "Shift From Prompting to Management"
        if any(
            token in intent_lower
            for token in ("ephemeral", "conversation", "reproducibility")
        ):
            return "Shift From Ephemeral Chat to Persistent Context"
        if any(token in intent_lower for token in ("execution", "implementation")):
            return "Shift From Diagnosis to Execution"
        return "Shift From Insight to Operating Model"

    def _closing_recommendation_title(self, intent: str) -> str:
        intent_lower = intent.lower()
        if any(token in intent_lower for token in ("benchmark", "ground truth", "model contract", "harness")):
            return "Build evaluation systems around real use cases"
        if any(token in intent_lower for token in ("memory", "context", "external brain")):
            return "Commit to persistent context as the operating default"
        if any(token in intent_lower for token in ("cycle", "loop", "reset")):
            return "Commit to the agentic cycle for reliable delivery"
        if "agentic coding" in intent_lower:
            return "Commit to Agentic Coding for production-grade reliability"
        return "Commit to the recommendation with named ownership"

    def _has_embedded_clause_title(self, title: str) -> bool:
        return bool(
            re.search(
                r"\b(?:turn|translate|convert|standardize)\s+.+\b"
                r"(?:is|are|was|were|has|have|can|should|must|consists?|arranged)\b"
                r".+\b(?:into|as)\b",
                title,
                flags=re.IGNORECASE,
            )
        )

    def _strip_meta_title_text(self, title: str) -> str:
        cleaned = re.sub(
            r"\s+(?:as|for)\s+(?:a\s+)?(?:distinct|primary|structured)\s+exhibit\b.*$",
            "",
            title,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"\b(?:distinct|primary|structured)\s+exhibit\b",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = " ".join(cleaned.split()).strip(" -:;,.")
        return cleaned or title

    def _title_contains_meta_instruction(self, title: str) -> bool:
        return bool(
            re.search(
                r"\b(?:distinct|primary|structured)\s+exhibit\b"
                r"|\badvance\s+the\s+storyline\b"
                r"|\bsource[-\s]+grounded\s+evidence\b"
                r"|\bsource[-\s]+backed\s+exhibit\b"
                r"|\bevidence\s+from\s+uploaded\s+source\b"
                r"|\bfocused\s+recommendation\b",
                title,
                flags=re.IGNORECASE,
            )
        )
