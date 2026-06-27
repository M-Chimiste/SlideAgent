"""Content-shaping helpers (renderer-agnostic).

Pure text/data utilities shared by the native renderer and the planner: derive a
short bold lead + supporting body from a plain sentence, normalize exhibit/bullet
content into ``[{title, body, icon}]`` items, pick an eyebrow label, and trim a
body to a complete thought. Extracted from the old HTML ``templates.py`` so they
no longer depend on any HTML/CSS code.
"""

from __future__ import annotations

import re
from typing import Any

# Narrative role -> eyebrow label (used when no clean section label is present).
_ROLE_EYEBROW = {
    "cover": "",
    "executive_summary": "Executive Summary",
    "problem": "The Challenge",
    "complication": "The Challenge",
    "evidence": "The Evidence",
    "insight": "The Core Insight",
    "reframe": "The Reframe",
    "decision": "The Decision",
    "implementation": "How It Works",
    "reference": "In Practice",
    "process": "The Process",
    "closing": "The Path Forward",
    "recommendation": "The Recommendation",
    "section": "",
}

_VERBS = {
    "is", "are", "was", "were", "can", "could", "should", "must", "will", "would",
    "make", "makes", "made", "turn", "turns", "create", "creates", "evaluate",
    "evaluates", "improve", "improves", "improved", "determine", "determines",
    "matter", "matters", "exist", "exists", "scale", "scales", "discover",
    "discovers", "enable", "enables", "reduce", "reduces", "drive", "drives",
    "come", "comes", "give", "gives", "help", "helps", "let", "lets", "need",
    "needs", "require", "requires", "provide", "provides", "reflect", "reflects",
    "move", "moves", "shift", "shifts", "remain", "remains", "become", "becomes",
    "bind", "binds", "ground", "grounds", "treat", "treats", "answer", "answers",
}
_STOP_LEAD = {"the", "a", "an", "this", "these", "those", "that", "our", "your", "its"}
_TRAIL_ADV = {"already", "often", "also", "still", "now", "typically", "usually", "always"}
# Connectives/prepositions that signal an idiomatic verb ("in turn", "to make")
# rather than the sentence's main verb — splitting there yields dangling leads.
_CONNECTIVE = {
    "in", "on", "of", "to", "for", "with", "and", "or", "but", "as", "at", "by",
    "from", "into", "than", "then",
}


def _as_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("text", "body", "action", "description", "label", "title", "name", "value"):
            if value.get(key):
                return str(value[key])
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(_as_text(v) for v in value)
    return str(value or "")


def _clean_sentence(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    # strip bracketed source markers that should not render
    text = re.sub(r"\s*\[(source needed|insert content here)\]\s*", " ", text, flags=re.I)
    # strip model-emitted meta-layout prefixes ("Left Column:", "Panel 1 -", ...)
    text = re.sub(
        r"^(left|right|top|bottom|first|second|third|fourth|upper|lower)\s+"
        r"(column|panel|box|card|section|half|side)\s*[:\-–—.]\s*",
        "", text, flags=re.I,
    )
    text = re.sub(
        r"^(column|panel|slide|title|subtitle|heading|body|bullet|point|header|step|label)\s*\d*\s*[:\-–—]\s*",
        "", text, flags=re.I,
    )
    return text.strip()


# Bare connectives/articles/subordinators a finished thought never ends on. Mirrors
# rendered_slide_audit.TRAILING_FRAGMENT_RE so trimmed text never reads as dangling.
_TRAILING_DANGLING = {
    "a", "an", "and", "as", "by", "for", "from", "in", "into", "of", "or", "that",
    "the", "their", "through", "to", "which", "with", "but", "on", "at", "than",
    "then", "when", "while", "where", "because", "so", "if",
}


def _trim_dangling(text: str) -> str:
    """Drop a trailing incomplete fragment (a bare preposition/article/connective,
    e.g. a salvaged truncated model string ``"...experience goals, a"``) so the
    text reads as a finished thought instead of a mid-sentence cut-off. Terminal
    punctuation is preserved when nothing is trimmed (``"...persists."`` stays)."""
    t = " ".join(str(text or "").split())
    if not t:
        return t
    trimmed = False
    while True:
        stripped = t.rstrip(" ,;:.–—-")
        words = stripped.split()
        if len(words) >= 3 and words[-1].lower().strip(",.;:") in _TRAILING_DANGLING:
            t = " ".join(words[:-1])
            trimmed = True
            continue
        return stripped if trimmed else t


def _cap(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    return text[0].upper() + text[1:]


def _lead_body(text: str) -> tuple[str, str]:
    """Derive a short bold lead + supporting body from one sentence."""
    s = _clean_sentence(text)
    if not s:
        return "", ""
    # explicit delimiter wins
    for delim in (" — ", " – ", " - ", ": "):
        if delim in s:
            head, _, tail = s.partition(delim)
            if 1 <= len(head.split()) <= 7 and tail.strip():
                return _cap(head.strip()), _cap(tail.strip())
    tokens = s.split()
    lead_words = list(tokens)
    if tokens and tokens[0].lower() in _STOP_LEAD:
        lead_words = tokens[1:]
    cut = None
    for i, tok in enumerate(lead_words):
        if tok.lower().strip(",.;:") in _VERBS:
            cut = i
            break
    if cut is None or cut < 1 or cut > 5:
        # no clean verb boundary: keep the sentence whole as body, no lead
        return "", _cap(s)
    # The "verb" is idiomatic (e.g. "in turn", "to make") when the word right
    # before it is a connective/preposition — splitting there dangles the lead
    # ("Three files, in"). Keep the sentence whole instead.
    if lead_words[cut - 1].lower().strip(",.;:") in _CONNECTIVE:
        return "", _cap(s)
    lead = lead_words[:cut]
    while lead and lead[-1].lower().strip(",.;:") in (_TRAIL_ADV | _CONNECTIVE):
        lead = lead[:-1]
    if not (1 <= len(lead) <= 5):
        return "", _cap(s)
    lead_str = " ".join(lead)
    # Never split inside an unbalanced bracket/quote — that mangles the sentence
    # ("Tests pass (or there" | "are no tests)"). Keep it whole instead.
    if (
        lead_str.count("(") != lead_str.count(")")
        or lead_str.count("[") != lead_str.count("]")
        or lead_str.count('"') % 2
    ):
        return "", _cap(s)
    rest = lead_words[cut:]
    title = _cap(lead_str.strip(" ,.;:"))
    body = _cap(" ".join(rest).strip())
    if len(body.split()) < 3:
        return "", _cap(s)
    return title, body


def _content(outline) -> dict:
    return outline.content_json or {}


def _normalize_items(content: dict) -> list[dict]:
    """Return [{title, body, icon}] from the best available content source."""
    ex = content.get("exhibit_spec") or {}
    raw: list[Any] = []
    for key in ("points", "items", "steps", "cards", "rows"):
        if isinstance(ex.get(key), list) and ex[key]:
            raw = ex[key]
            break
    if not raw:
        bullets = content.get("bullets") or []
        raw = [b for b in bullets if _as_text(b).strip()]
    items: list[dict] = []
    for entry in raw:
        if isinstance(entry, dict):
            title = entry.get("title") or entry.get("heading") or entry.get("label") or entry.get("name") or ""
            body = entry.get("body") or entry.get("text") or entry.get("description") or entry.get("action") or ""
            icon_hint = entry.get("icon")
            if not body and not title:
                body = _as_text(entry)
            if title and not body:
                title, body = _lead_body(title)
            elif body and not title:
                title, body = _lead_body(body)
            else:
                title, body = _cap(_clean_sentence(title)), _cap(_clean_sentence(body))
        else:
            title, body = _lead_body(_as_text(entry))
            icon_hint = None
        title, body = _trim_dangling(title), _trim_dangling(body)
        if not (title or body):
            continue
        items.append({
            "title": title,
            "body": body,
            "icon": icon_hint or None,
            "text": (title + " " + body).strip(),
        })
    return items


def _eyebrow_text(content: dict) -> str:
    sub = _clean_sentence(content.get("subheading") or "")
    role = (content.get("narrative_role") or content.get("slide_type") or "").lower()
    # a short section label makes the best eyebrow
    if sub and 1 <= len(sub.split()) <= 6 and not sub.endswith("."):
        return sub.upper()
    label = _ROLE_EYEBROW.get(role, "")
    return label.upper() if label else ""


def _fit(text: str, max_chars: int) -> str:
    """Trim body text to a complete first sentence (or a clean word boundary) so
    it reads as a finished thought instead of a mid-sentence ellipsis."""
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    match = re.search(r"[.!?](\s|$)", t)
    if match and match.start() + 1 <= max_chars:
        return t[: match.start() + 1].strip()
    cut = t[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:—–-")
    return f"{cut}…"
