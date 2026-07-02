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
    "rather", "versus", "vs", "instead", "toward", "towards", "across", "between",
    "against", "unlike", "via", "per", "such", "either", "neither", "both",
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
    """Split a string into a bold lead + body ONLY on an explicit delimiter
    (— – - :). With no delimiter, keep the whole sentence as the body (no lead).

    The model authors real ``{title, body}`` pairs when it wants a lead; we no
    longer GUESS a lead by verb-splitting prose, which produced awkward fragments
    like "Memory Bank" / "Is a folder…". This keeps short "Term: definition"
    points readable while leaving full sentences intact.
    """
    s = _clean_sentence(text)
    if not s:
        return "", ""
    for delim in (" — ", " – ", " - ", ": "):
        if delim in s:
            head, _, tail = s.partition(delim)
            if 1 <= len(head.split()) <= 7 and tail.strip():
                return _cap(head.strip()), _cap(tail.strip())
    return "", _cap(s)


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
            # Reference-table row {label, values:[desc, trigger]}: map label->title,
            # first value->body, drop the trailing trigger column (don't concatenate
            # the whole row, which produced "In Cursor these In Cursor, these...").
            if not body and isinstance(entry.get("values"), list) and entry["values"]:
                body = _clean_sentence(_as_text(entry["values"][0]))
            if not body and not title:
                body = _as_text(entry)
            if title and not body:
                title, body = _lead_body(title)
            elif body and not title:
                title, body = _lead_body(body)
            else:
                title, body = _cap(_clean_sentence(title)), _cap(_clean_sentence(body))
        elif isinstance(entry, (list, tuple)):
            # Bare table row [cell0, cell1, ...]: cell0->title, cell1->body, drop rest.
            cells = [_clean_sentence(_as_text(c)) for c in entry if _as_text(c).strip()]
            title = _cap(cells[0]) if cells else ""
            body = _cap(cells[1]) if len(cells) > 1 else ""
            icon_hint = None
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
