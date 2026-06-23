import re

from app.models.generation import DeckSpec, GeneratedSlideSpec
from app.models.outline import SlideOutline
from app.models.qa import QAIssue


GENERIC_TITLE_PATTERNS = {
    "overview",
    "market overview",
    "revenue analysis",
    "competitive analysis",
    "financial projections",
    "next steps",
    "summary",
    "background",
    "introduction",
}

ACTION_VERBS = {
    "accelerate",
    "adopt",
    "are",
    "build",
    "capture",
    "clarify",
    "clarifies",
    "codify",
    "commit",
    "compare",
    "create",
    "contrast",
    "deliver",
    "demonstrate",
    "define",
    "diagnose",
    "deploy",
    "enforce",
    "establish",
    "fail",
    "fails",
    "explain",
    "expand",
    "focus",
    "form",
    "forms",
    "grow",
    "highlight",
    "identify",
    "improve",
    "implement",
    "introduce",
    "introduces",
    "increase",
    "is",
    "keep",
    "keeps",
    "make",
    "makes",
    "manage",
    "map",
    "occur",
    "occurs",
    "outpace",
    "outpaces",
    "prioritize",
    "prevent",
    "persist",
    "persists",
    "provide",
    "provides",
    "quantify",
    "recognize",
    "reduce",
    "reframe",
    "replace",
    "replaces",
    "require",
    "requires",
    "reset",
    "reveal",
    "revealed",
    "reveals",
    "review",
    "reviews",
    "run",
    "secure",
    "show",
    "shows",
    "shift",
    "specify",
    "specifies",
    "standardize",
    "structure",
    "target",
    "treat",
    "translate",
    "transition",
    "undermine",
    "unlock",
    "update",
    "use",
    "visualize",
    "visualizes",
    "work",
    "works",
}

GENERIC_FILLER_PATTERNS = {
    "preserve context before work begins",
    "make review criteria explicit before execution",
    "keep decisions traceable across handoffs",
    "turn lessons into durable operating rules",
    "assign one clear owner for each step of the workflow",
    "validate every output against the original intent",
    "capture assumptions so they can be revisited later",
    "close the loop with a short, honest retrospective",
}


class ConsultingQA:
    def inspect(self, deck: DeckSpec) -> tuple[DeckSpec, list[dict]]:
        warnings: list[dict] = []
        for slide in deck.slides:
            slide_issues = self.inspect_slide(slide)
            if slide_issues:
                slide.qa.consulting_status = "warning"
                slide.qa.issues.extend(slide_issues)
                warnings.extend(
                    {
                        "slide_index": slide.slide_number - 1,
                        "field": "consulting_qa",
                        "message": issue["message"],
                    }
                    for issue in slide_issues
                )
            else:
                slide.qa.consulting_status = "pass"
        flow_issue = self._inspect_horizontal_flow(deck)
        if flow_issue:
            warnings.append(flow_issue)
        return deck, warnings

    def inspect_outlines(
        self,
        outlines: list[SlideOutline],
        has_source_material: bool = True,
    ) -> list[QAIssue]:
        issues: list[QAIssue] = []
        flexible = [outline for outline in outlines if outline.mode == "flexible"]
        titles: dict[str, int] = {}
        title_frames: dict[str, int] = {}
        bullets_seen: dict[str, int] = {}
        slide_fingerprints: list[tuple[int, set[str]]] = []
        roles = []
        for outline in flexible:
            content = outline.content_json
            title = str(
                content.get("action_title") or content.get("title") or outline.label
            ).strip()
            roles.append(str(content.get("narrative_role") or "").lower())
            issues.extend(self._outline_title_issues(outline, title))
            normalized_title = self._normalize_text(title)
            if normalized_title:
                if normalized_title in titles:
                    issues.append(
                        QAIssue(
                            severity="WARNING",
                            category="horizontal_flow",
                            message="Repeated or near-duplicate action title weakens the storyline.",
                            slide_index=outline.slide_index,
                        )
                    )
                titles[normalized_title] = outline.slide_index
            title_frame = self._title_frame_key(title)
            if title_frame:
                if title_frame in title_frames:
                    issues.append(
                        QAIssue(
                            severity="WARNING",
                            category="horizontal_flow",
                            message=(
                                "Repeated action-title sentence frame weakens the storyline."
                            ),
                            slide_index=outline.slide_index,
                        )
                    )
                title_frames[title_frame] = outline.slide_index
            bullets = self._outline_bullets(outline)
            issues.extend(self._outline_content_issues(outline, title, bullets))
            for bullet in bullets:
                normalized_bullet = self._repeated_evidence_key(bullet)
                if not normalized_bullet:
                    continue
                if normalized_bullet in bullets_seen:
                    issues.append(
                        QAIssue(
                            severity="WARNING",
                            category="repeated_bullet",
                            message="Repeated evidence bullet appears on multiple slides.",
                            slide_index=outline.slide_index,
                        )
                    )
                    break
                bullets_seen[normalized_bullet] = outline.slide_index
            fingerprint = self._outline_slide_fingerprint(outline, title, bullets)
            duplicate_index = self._duplicate_slide_index(
                fingerprint,
                slide_fingerprints,
            )
            if duplicate_index is not None:
                issues.append(
                    QAIssue(
                        severity="WARNING",
                        category="duplicate_slide",
                        message=(
                            "Slide substantially duplicates the message and evidence "
                            f"from slide {duplicate_index + 1}."
                        ),
                        slide_index=outline.slide_index,
                    )
                )
            slide_fingerprints.append((outline.slide_index, fingerprint))
            if has_source_material and not self._outline_source_refs(outline):
                issues.append(
                    QAIssue(
                        severity="WARNING",
                        category="source_refs",
                        message="Source-backed slide is missing canonical source references.",
                        slide_index=outline.slide_index,
                    )
                )
            if self._needs_exhibit(outline) and not self._has_primary_exhibit(outline):
                issues.append(
                    QAIssue(
                        severity="WARNING",
                        category="missing_exhibit",
                        message="Non-cover slide is missing a primary exhibit spec.",
                        slide_index=outline.slide_index,
                    )
                )
        issues.extend(self._outline_flow_issues(flexible, roles))
        return issues

    def inspect_slide(self, slide: GeneratedSlideSpec) -> list[dict]:
        issues: list[dict] = []
        title = slide.action_title.strip()
        if not title:
            issues.append({"category": "action_title", "message": "Missing action title."})
        if title.lower() in GENERIC_TITLE_PATTERNS:
            issues.append(
                {
                    "category": "action_title",
                    "message": "Action title is a generic topic label.",
                }
            )
        if len(title.split()) > 16:
            issues.append(
                {
                    "category": "action_title",
                    "message": "Action title should be 15 words or fewer.",
                }
            )
        if " and " in title.lower():
            issues.append(
                {
                    "category": "one_message",
                    "message": "Title may contain multiple messages; consider splitting.",
                }
            )
        if not self._has_action_signal(title):
            issues.append(
                {
                    "category": "action_title",
                    "message": "Action title should state a conclusion with a verb.",
                }
            )
        numeric_claim = bool(re.search(r"\b\d+(\.\d+)?%?\b", title + " " + str(slide.content_blocks)))
        if numeric_claim and not slide.sources:
            issues.append(
                {
                    "category": "source_coverage",
                    "message": "Numeric claim needs a source or [source needed].",
                }
            )
        return issues

    def _has_action_signal(self, title: str) -> bool:
        words = {re.sub(r"[^a-z]", "", word.lower()) for word in title.split()}
        if words & ACTION_VERBS:
            return True
        return False

    def _outline_title_issues(
        self, outline: SlideOutline, title: str
    ) -> list[QAIssue]:
        issues: list[QAIssue] = []
        if not title:
            issues.append(
                QAIssue(
                    severity="WARNING",
                    category="action_title",
                    message="Missing action title.",
                    slide_index=outline.slide_index,
                )
            )
            return issues
        if self._outline_is_cover(outline):
            return issues
        if title.lower() in GENERIC_TITLE_PATTERNS:
            issues.append(
                QAIssue(
                    severity="WARNING",
                    category="action_title",
                    message="Action title is a generic topic label.",
                    slide_index=outline.slide_index,
                )
            )
        if len(title.split()) > 16:
            issues.append(
                QAIssue(
                    severity="WARNING",
                    category="action_title",
                    message="Action title should be 15 words or fewer.",
                    slide_index=outline.slide_index,
                )
            )
        if " and " in title.lower():
            issues.append(
                QAIssue(
                    severity="WARNING",
                    category="one_message",
                    message="Title may contain multiple messages; split or sharpen it.",
                    slide_index=outline.slide_index,
                )
            )
        if self._has_dangling_connector(title):
            issues.append(
                QAIssue(
                    severity="WARNING",
                    category="action_title",
                    message="Action title has a dangling connector phrase.",
                    slide_index=outline.slide_index,
                )
            )
        if not self._has_action_signal(title):
            issues.append(
                QAIssue(
                    severity="WARNING",
                    category="action_title",
                    message="Action title should state a conclusion with a verb.",
                    slide_index=outline.slide_index,
                )
            )
        return issues

    def _has_dangling_connector(self, title: str) -> bool:
        normalized = " ".join(str(title).split())
        if re.search(
            r"\b(?:as|at|by|for|from|in|into|of|on|to|with|without)\s+"
            r"(?:as|at|by|for|from|in|into|of|on|to|with|without)\b",
            normalized,
            flags=re.IGNORECASE,
        ):
            return True
        words = normalized.rstrip(".,;:").split()
        return bool(
            words
            and words[-1].lower()
            in {"as", "for", "into", "of", "optimal", "prior", "to", "with"}
        )

    def _title_frame_key(self, title: str) -> str:
        words = self._normalize_text(title).split()
        if len(words) < 6:
            return ""
        for connector in ("so", "before", "after", "through", "with", "into", "as", "to"):
            if connector not in words:
                continue
            index = words.index(connector)
            tail = words[index + 1 :]
            if index >= 2 and len(tail) >= 3:
                return " ".join([words[0], connector, *tail])
        return ""

    def _outline_content_issues(
        self, outline: SlideOutline, title: str, bullets: list[str]
    ) -> list[QAIssue]:
        issues: list[QAIssue] = []
        if self._outline_is_cover(outline):
            return issues
        title_tokens = self._meaningful_tokens(title)
        body_text = self._outline_support_text(outline, bullets)
        body_tokens = self._meaningful_tokens(body_text)
        if (
            title_tokens
            and body_tokens
            and len(title_tokens & body_tokens) == 0
            and not self._has_semantic_support(title_tokens, body_tokens)
        ):
            issues.append(
                QAIssue(
                    severity="WARNING",
                    category="title_body_support",
                    message="Slide body does not clearly support the action title.",
                    slide_index=outline.slide_index,
                )
            )
        for bullet in bullets:
            if self._normalize_text(bullet) in GENERIC_FILLER_PATTERNS:
                issues.append(
                    QAIssue(
                        severity="WARNING",
                        category="generic_filler",
                        message="Generic filler bullet should be replaced with source-specific evidence.",
                        slide_index=outline.slide_index,
                    )
                )
                break
        issues.extend(self._outline_exhibit_match_issues(outline, title, body_text))
        return issues

    def _outline_exhibit_match_issues(
        self,
        outline: SlideOutline,
        title: str,
        body_text: str,
    ) -> list[QAIssue]:
        exhibit = outline.content_json.get("exhibit_spec")
        if not isinstance(exhibit, dict):
            return []
        exhibit_type = str(exhibit.get("type") or "").lower().replace("-", "_")
        title_text = title.lower()
        expected: str | None = None
        if re.search(
            r"\b(directed dependency graph|dependency graph|file hierarchy|"
            r"dependencies|relationship map)\b",
            title_text,
        ):
            expected = "dependency_map"
        elif re.search(r"\b(six[- ]phase loop|cycle|operating loop)\b", title_text):
            expected = "cycle"
        elif re.search(
            r"\b(six core files|core files|rules files|specification files|"
            r"reference table)\b",
            title_text,
        ):
            expected = "reference_table"
        if expected is None:
            return []
        compatible = {
            "dependency_map": {"dependency_map"},
            "cycle": {"cycle", "checklist"},
            "reference_table": {"reference_table", "code_panel"},
        }[expected]
        if exhibit_type in compatible:
            return []
        return [
            QAIssue(
                severity="WARNING",
                category="exhibit_structure",
                message=(
                    "Primary exhibit type does not match the action title's implied "
                    "visual structure."
                ),
                slide_index=outline.slide_index,
            )
        ]

    def _outline_support_text(self, outline: SlideOutline, bullets: list[str]) -> str:
        content = outline.content_json
        parts = [
            str(content.get("subheading") or ""),
            str(content.get("design_intent") or ""),
            *bullets,
        ]
        exhibit = content.get("exhibit_spec")
        if exhibit:
            parts.append(self._flatten_for_similarity(exhibit))
        return " ".join(parts)

    def _has_semantic_support(
        self,
        title_tokens: set[str],
        body_tokens: set[str],
    ) -> bool:
        families = [
            {
                "unverified",
                "claim",
                "claims",
                "quality",
                "risk",
                "hallucination",
                "hallucinations",
                "fabricate",
                "fabricated",
                "ambiguity",
                "ambiguous",
                "vague",
                "evidence",
                "checked",
                "verify",
            },
            {
                "agent",
                "agents",
                "teammate",
                "teammates",
                "managed",
                "manager",
                "managers",
                "manage",
                "employee",
                "employees",
                "paradigm",
                "developer",
                "developers",
            },
            {
                "context",
                "memory",
                "persistent",
                "external",
                "brain",
                "window",
                "windows",
                "reset",
                "session",
            },
            {
                "specification",
                "specifications",
                "criteria",
                "acceptance",
                "requirements",
                "prompt",
                "prompts",
                "rules",
            },
            {
                "cycle",
                "cycles",
                "loop",
                "loops",
                "phase",
                "phases",
                "workflow",
                "workflows",
                "review",
                "reviews",
                "reset",
                "reliability",
                "repeatable",
            },
        ]
        return any(title_tokens & family and body_tokens & family for family in families)

    def _outline_is_cover(self, outline: SlideOutline) -> bool:
        content = outline.content_json
        layout = str(outline.layout_json.get("layout") or "").lower()
        archetype = str(content.get("archetype") or outline.layout_json.get("archetype") or "").lower()
        role = str(content.get("narrative_role") or "").lower()
        return layout == "cover" or archetype == "cover" or role == "cover"

    def _outline_flow_issues(
        self, outlines: list[SlideOutline], roles: list[str]
    ) -> list[QAIssue]:
        if len(outlines) < 6:
            return []
        compact_roles = [role for role in roles if role]
        issues: list[QAIssue] = []
        if compact_roles and compact_roles[0] not in {"cover", "executive_summary"}:
            issues.append(
                QAIssue(
                    severity="WARNING",
                    category="scr_flow",
                    message="Deck should open with a cover or executive summary beat.",
                )
            )
        if len(outlines) >= 8 and "closing" not in compact_roles[-2:]:
            issues.append(
                QAIssue(
                    severity="WARNING",
                    category="scr_flow",
                    message="Deck should end with a recommendation or decision beat.",
                )
            )
        return issues

    def _outline_bullets(self, outline: SlideOutline) -> list[str]:
        content = outline.content_json
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
                    if isinstance(item, str) and item.strip():
                        collected.append(item)
                    elif isinstance(item, list):
                        text = " | ".join(str(value) for value in item)
                        if text.strip():
                            collected.append(text)
        return collected

    def _outline_source_refs(self, outline: SlideOutline) -> list[str]:
        refs = outline.content_json.get("source_refs")
        if not isinstance(refs, list):
            return []
        return [
            str(ref)
            for ref in refs
            if str(ref).strip()
            and "source needed" not in str(ref).lower()
            and str(ref).strip() != "Uploaded source"
        ]

    def _needs_exhibit(self, outline: SlideOutline) -> bool:
        role = str(outline.content_json.get("narrative_role") or "").lower()
        archetype = str(outline.content_json.get("archetype") or "").lower()
        return role != "cover" and archetype != "cover"

    def _has_primary_exhibit(self, outline: SlideOutline) -> bool:
        exhibit = outline.content_json.get("exhibit_spec")
        return isinstance(exhibit, dict) and bool(exhibit.get("type"))

    def _outline_slide_fingerprint(
        self,
        outline: SlideOutline,
        title: str,
        bullets: list[str],
    ) -> set[str]:
        content = outline.content_json
        exhibit = content.get("exhibit_spec")
        exhibit_text = self._flatten_for_similarity(exhibit) if exhibit else ""
        return self._meaningful_tokens(" ".join([title, *bullets, exhibit_text]))

    def _duplicate_slide_index(
        self,
        fingerprint: set[str],
        previous: list[tuple[int, set[str]]],
    ) -> int | None:
        if len(fingerprint) < 6:
            return None
        for slide_index, prior in previous:
            if len(prior) < 6:
                continue
            shared = len(fingerprint & prior)
            if shared < 6:
                continue
            union = len(fingerprint | prior)
            smaller = min(len(fingerprint), len(prior))
            jaccard = shared / union if union else 0
            containment = shared / smaller if smaller else 0
            if jaccard >= 0.72 or containment >= 0.86:
                return slide_index
        return None

    def _flatten_for_similarity(self, value) -> str:
        if isinstance(value, dict):
            return " ".join(
                self._flatten_for_similarity(item)
                for item in value.values()
            )
        if isinstance(value, list):
            return " ".join(self._flatten_for_similarity(item) for item in value)
        return str(value)

    def _normalize_text(self, text: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", " ", str(text).lower())
        return " ".join(normalized.split())

    def _repeated_evidence_key(self, text: str) -> str:
        normalized = self._normalize_text(text)
        tokens = normalized.split()
        if not tokens:
            return ""
        low_signal = {
            "action",
            "current",
            "dimension",
            "implication",
            "item",
            "owner",
            "signal",
            "state",
            "target",
            "timing",
            "trigger",
            "update",
            "when",
            "conditions",
            "change",
        }
        meaningful = [token for token in tokens if token not in low_signal]
        if len(meaningful) < 5:
            return ""
        return normalized

    def _meaningful_tokens(self, text: str) -> set[str]:
        stop = {
            "a",
            "an",
            "and",
            "as",
            "by",
            "for",
            "from",
            "in",
            "into",
            "of",
            "on",
            "or",
            "the",
            "to",
            "with",
            "without",
            "should",
            "must",
            "can",
            "will",
            "use",
            "uses",
            "using",
            "make",
            "makes",
            "slide",
            "source",
            "evidence",
        }
        return {
            token
            for token in self._normalize_text(text).split()
            if len(token) > 3 and token not in stop
        }

    def _inspect_horizontal_flow(self, deck: DeckSpec) -> dict | None:
        if len(deck.slides) < 3:
            return None
        titles = [slide.action_title.lower() for slide in deck.slides]
        unique = set(titles)
        if len(unique) < len(titles):
            return {
                "slide_index": None,
                "field": "horizontal_flow",
                "message": "Repeated action titles weaken the deck storyline.",
            }
        return None
