import re

from app.models.generation import DeckSpec, GeneratedSlideSpec


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
    "build",
    "capture",
    "create",
    "contrast",
    "deliver",
    "demonstrate",
    "define",
    "diagnose",
    "deploy",
    "enforce",
    "establish",
    "explain",
    "expand",
    "focus",
    "grow",
    "highlight",
    "identify",
    "improve",
    "implement",
    "increase",
    "manage",
    "prioritize",
    "recognize",
    "reduce",
    "reframe",
    "secure",
    "shift",
    "standardize",
    "target",
    "transition",
    "undermine",
    "unlock",
    "use",
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
        return any(word.endswith(("ing", "ed", "es")) for word in words if len(word) > 4)

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
