"""Per-slide HTML builders (the layout primitives).

Each ``SlideOutline`` is mapped — by composition family, exhibit type, and
content shape — to one reusable primitive. Variety comes from primitive
*selection*; the shared CSS keeps every slide in one visual language. Planner
content is usually a list of plain sentences (no card titles), so we derive a
short bold lead from each sentence to get reference-style cards.
"""

from __future__ import annotations

import html
import re
from typing import Any

from .css import motif_svg
from .design_system import Theme
from .icons import icon_for, icon_svg

MAX_CARDS = 6
MAX_ROWS = 4
MAX_STEPS = 8

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


def esc(text: Any) -> str:
    return html.escape(str(text if text is not None else "").strip())


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


def _cap(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    return text[0].upper() + text[1:]


def _phrase_split(text: str, max_words: int = 9) -> tuple[str, str]:
    """Split a sentence into a punchy lead phrase + remainder for split panels."""
    s = _clean_sentence(text)
    if not s:
        return "", ""
    m = re.search(r"[,;:—–]", s)
    if m and 2 <= len(s[: m.start()].split()) <= max_words:
        return _cap(s[: m.start()].strip()), _cap(s[m.start() + 1:].strip(" ,;:—–"))
    words = s.split()
    if len(words) <= max_words:
        return _cap(s), ""
    return _cap(" ".join(words[:max_words])), _cap(" ".join(words[max_words:]))


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


def _maybe_subhead(content: dict, used_as_eyebrow: bool) -> str:
    sub = _clean_sentence(content.get("subheading") or "")
    if not sub:
        return ""
    if used_as_eyebrow:
        return ""
    if len(sub.split()) <= 6 and not sub.endswith("."):
        return ""  # it's a label, already shown as eyebrow
    return sub


def _title_class(title: str) -> str:
    n = len(title)
    if n <= 38:
        return "h-lg"
    if n <= 64:
        return "h-md"
    return "h-sm"


def _header(content: dict, *, size_override: str | None = None) -> str:
    eyebrow = _eyebrow_text(content)
    title = _clean_sentence(content.get("action_title") or content.get("title") or "")
    used = bool(eyebrow) and eyebrow == _clean_sentence(content.get("subheading") or "").upper()
    subhead = _maybe_subhead(content, used)
    cls = size_override or _title_class(title)
    parts = ['<div class="head-block">']
    if eyebrow:
        parts.append(f'<div class="eyebrow"><span class="tick"></span>{esc(eyebrow)}</div>')
    if title:
        parts.append(f'<h2 class="headline {cls}">{esc(title)}</h2>')
    if subhead:
        parts.append(f'<p class="subhead">{esc(subhead)}</p>')
    parts.append("</div>")
    return "".join(parts)


def _badge(icon_name_or_hint: str | None, text: str, idx: int, *, soft: bool = False) -> str:
    tone = "soft" if soft else ("teal", "gold")[idx % 2]
    svg = icon_for(icon_name_or_hint, text)
    return f'<div class="badge {tone}">{svg}</div>'


# --------------------------------------------------------------------------- #
# Primitives
# --------------------------------------------------------------------------- #
def _cover(content: dict, theme: Theme) -> str:
    title = _clean_sentence(content.get("action_title") or content.get("deck_title") or "")
    sub = _clean_sentence(content.get("subheading") or content.get("summary") or "")
    kicker = ""
    bullets = [_clean_sentence(_as_text(b)) for b in (content.get("bullets") or [])]
    pills = []
    for b in bullets[:3]:
        words = b.split()
        if 1 <= len(words) <= 4:
            pills.append(b)
        else:
            # short noun phrase from the lead
            lead, _ = _lead_body(b)
            pills.append(lead or " ".join(words[:3]))
    pills = [p for p in pills if p][:3]
    long = " long" if len(title) > 46 else ""
    html_parts = [motif_svg(theme, "cover")]
    html_parts.append('<div class="cover-inner">')
    if kicker:
        html_parts.append(f'<div class="c-eyebrow">{esc(kicker)}</div>')
    else:
        html_parts.append('<div class="c-eyebrow">Whitepaper &nbsp;·&nbsp; Executive Briefing</div>')
    html_parts.append(f'<h1 class="c-title{long}">{esc(title)}</h1>')
    if sub:
        html_parts.append(f'<p class="c-sub">{esc(sub)}</p>')
    if pills:
        html_parts.append('<div class="pills">' + "".join(f'<span class="pill">{esc(p)}</span>' for p in pills) + "</div>")
    html_parts.append("</div>")
    return "".join(html_parts)


def _closing(content: dict, theme: Theme) -> str:
    ex = content.get("exhibit_spec") or {}
    steps = ex.get("next_steps") or [_as_text(b) for b in (content.get("bullets") or [])]
    steps = [_clean_sentence(_as_text(s)) for s in steps if _as_text(s).strip()][:4]
    ask = _clean_sentence(ex.get("decision_ask") or "")
    out = [motif_svg(theme, "closing"), _header(content, size_override="h-md")]
    out.append('<div class="close-actions">')
    for i, s in enumerate(steps, 1):
        out.append(f'<div class="close-step"><span class="dotn">{i}</span><div class="ctext">{esc(s)}</div></div>')
    out.append("</div>")
    if ask:
        out.append(f'<div class="ask">{esc(ask)}</div>')
    return "".join(out)


def _lead_size(title: str) -> str:
    n = len(title)
    if n <= 26:
        return "lead-xl"
    if n <= 50:
        return "lead-lg"
    if n <= 86:
        return "lead-md"
    return "lead-sm"


def _statement(content: dict, theme: Theme) -> str:
    title = _clean_sentence(content.get("action_title") or "")
    items = _normalize_items(content)
    eyebrow = _eyebrow_text(content) or "The Big Idea"
    size = _lead_size(title)
    support = _maybe_subhead(content, False)
    motif = motif_svg(theme, "statement")
    if len(items) >= 2:
        ticks = []
        for it in items[:4]:
            mark = f'<span class="tk">{icon_svg("check-circle")}</span>'
            if it["title"] and it["body"]:
                tt = f'<b>{esc(it["title"])}.</b> {esc(it["body"])}'
            else:
                tt = esc(it["body"] or it["title"])
            ticks.append(f'<div class="tick-item">{mark}<div class="tt">{tt}</div></div>')
        claim = (
            '<div class="statement-claim">'
            f'<div class="eyebrow"><span class="tick"></span>{esc(eyebrow)}</div>'
            f'<div class="lead {size}">{esc(title)}</div>'
            + (f'<div class="support">{esc(support)}</div>' if support else "")
            + "</div>"
        )
        return motif + f'<div class="statement-grid">{claim}<div class="ticks">{"".join(ticks)}</div></div>'
    out = [f'<div class="eyebrow"><span class="tick"></span>{esc(eyebrow)}</div>', '<div class="statement">']
    out.append(f'<div class="lead {size}">{esc(title)}</div>')
    if support:
        out.append(f'<div class="support">{esc(support)}</div>')
    out.append("</div>")
    return motif + "".join(out)


def _quote(content: dict, theme: Theme) -> str:
    title = _clean_sentence(content.get("action_title") or "")
    quote = title
    if len(title) < 24:
        for b in content.get("bullets") or []:
            t = _clean_sentence(_as_text(b))
            if 24 <= len(t) <= 150:
                quote = t
                break
    attr = _clean_sentence(content.get("subheading") or "")
    out = ['<div class="quote">', '<div class="mark">&ldquo;</div>']
    out.append(f'<div class="qtext">{esc(quote)}</div>')
    if attr:
        out.append(f'<div class="qattr">{esc(attr)}</div>')
    out.append("</div>")
    return "".join(out)


def _fit(text: str, max_chars: int) -> str:
    """Trim body text to a complete first sentence (or a clean word boundary) so
    cards read as finished thoughts instead of a mid-sentence CSS ellipsis."""
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    match = re.search(r"[.!?](\s|$)", t)
    if match and match.start() + 1 <= max_chars:
        return t[: match.start() + 1].strip()
    cut = t[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:—–-")
    return f"{cut}…"


def _cards(content: dict, theme: Theme, *, max_n: int | None = None) -> str:
    family = (content.get("composition_family") or "").lower()
    if max_n is None:
        max_n = 9 if family == "toolkit_grid" else MAX_CARDS
    items = _normalize_items(content)[:max_n]
    n = len(items)
    if n <= 1:
        cols = "cols-1"
    elif n == 2:
        cols = "cols-2"
    elif n == 4:
        cols = "cols-2 rows-2"
    elif n in (3,):
        cols = "cols-3"
    else:  # 5-9 cards read best as a 3-wide grid
        cols = "cols-3"
    body_cap = 150 if n >= 3 else (230 if n == 2 else 320)
    cards = []
    for i, it in enumerate(items):
        badge = _badge(it["icon"], it["text"], i)
        title_html = f'<div class="card-title">{esc(it["title"])}</div>' if it["title"] else ""
        body_text = _fit(it["body"], body_cap)
        body_html = f'<div class="card-body">{esc(body_text)}</div>' if body_text else ""
        head = f'<div class="card-head">{badge}{title_html}</div>' if it["title"] else badge
        cards.append(f'<div class="card">{head}{body_html}</div>')
    return _header(content) + f'<div class="cards {cols}">' + "".join(cards) + "</div>"


def _rows(content: dict, theme: Theme) -> str:
    items = _normalize_items(content)[:MAX_ROWS]
    rows = []
    for i, it in enumerate(items):
        badge = _badge(it["icon"], it["text"], i)
        title = it["title"] or _fit(it["body"].split(".")[0] if it["body"] else "", 80)
        body = _fit(it["body"], 170) if it["title"] else ""
        rows.append(
            f'<div class="row">{badge}'
            f'<div class="row-title">{esc(title)}</div>'
            f'<div class="row-body">{esc(body)}</div></div>'
        )
    return _header(content) + '<div class="rows">' + "".join(rows) + "</div>"


def _steps(content: dict, theme: Theme) -> str:
    items = _normalize_items(content)[:MAX_STEPS]
    n = len(items)
    cols = "cols-3" if n <= 3 else ("cols-2 rows-2" if n == 4 else ("cols-3" if n <= 6 else "cols-4"))
    cards = []
    for i, it in enumerate(items, 1):
        tone = ("teal", "gold")[(i - 1) % 2]
        title = _fit(it["title"] or it["text"], 70)
        body = _fit(it["body"], 130) if it["title"] else ""
        cards.append(
            f'<div class="card tight"><div class="card-head"><span class="chip {tone}">{i}</span>'
            f'<div class="card-title">{esc(title)}</div></div>'
            + (f'<div class="card-body">{esc(body)}</div>' if body else "")
            + "</div>"
        )
    return _header(content) + f'<div class="cards {cols}">' + "".join(cards) + "</div>"


def _split(content: dict, theme: Theme) -> str:
    items = _normalize_items(content)
    ex = content.get("exhibit_spec") or {}
    left_k, right_k = "Today", "With the harness"
    if ex.get("type") == "comparison_table" and ex.get("columns"):
        cols = ex["columns"]
        if len(cols) >= 2:
            left_k, right_k = str(cols[-2]), str(cols[-1])
    left = items[0] if items else {"title": "", "body": ""}
    right = items[1] if len(items) > 1 else (items[0] if items else {"title": "", "body": ""})

    def lead_sub(item):
        if item["title"]:
            return item["title"], item["body"]
        return _phrase_split(item["body"])

    left_lead, left_sub = lead_sub(left)
    right_lead, right_sub = lead_sub(right)

    def panel(kicker, lead, sub, accent=False):
        cls = "panel accent" if accent else "panel"
        sub_html = f'<div class="panel-sub">{esc(sub)}</div>' if sub else ""
        return (
            f'<div class="{cls}"><div class="panel-kicker">{esc(kicker)}</div>'
            f'<div class="panel-lead">&ldquo;{esc(lead)}&rdquo;</div>{sub_html}</div>'
        )

    body = (
        '<div class="split">'
        + panel(left_k, left_lead, left_sub)
        + f'<div class="arrow"><span class="ring">{icon_svg("arrow-right")}</span></div>'
        + panel(right_k, right_lead, right_sub, accent=True)
        + "</div>"
    )
    return _header(content) + body


def _table(content: dict, theme: Theme) -> str:
    ex = content.get("exhibit_spec") or {}
    cols = ex.get("columns") or []
    rows = ex.get("rows") or []
    thead = "".join(f"<th>{esc(c)}</th>" for c in cols)
    body_rows = []
    for r in rows[:6]:
        if isinstance(r, dict):
            cells = [r.get("label", "")] + list(r.get("values", []))
        else:
            cells = list(r)
        tds = "".join(f"<td>{esc(_clean_sentence(c))}</td>" for c in cells[: len(cols) or len(cells)])
        body_rows.append(f"<tr>{tds}</tr>")
    table = f'<table class="cmp"><thead><tr>{thead}</tr></thead><tbody>{"".join(body_rows)}</tbody></table>'
    return _header(content) + table


def _callout_list(content: dict, theme: Theme) -> str:
    items = _normalize_items(content)
    if not items:
        return _cards(content, theme)
    feature = items[0]
    rest = items[1:5]
    f_title = _fit(feature["title"] or (feature["body"].split(".")[0] if feature["body"] else ""), 90)
    f_body = _fit(feature["body"], 240)
    feat_html = (
        f'<div class="feature">{_badge(feature["icon"], feature["text"], 1, soft=False)}'
        f'<div class="feature-title">{esc(f_title)}</div>'
        + (f'<div class="feature-body">{esc(f_body)}</div>' if f_body else "")
        + "</div>"
    )
    mini = []
    for i, it in enumerate(rest):
        badge = _badge(it["icon"], it["text"], i, soft=True)
        title = it["title"] or _fit(it["body"].split(".")[0] if it["body"] else "", 60)
        body = _fit(it["body"], 120) if it["title"] else ""
        mini.append(
            f'<div class="mini-row">{badge}<div><div class="mini-title">{esc(title)}</div>'
            + (f'<div class="mini-body">{esc(body)}</div>' if body else "")
            + "</div></div>"
        )
    grid = f'<div class="callout-grid">{feat_html}<div class="mini-rows">{"".join(mini)}</div></div>'
    return _header(content) + grid


def _metrics(content: dict, theme: Theme) -> str:
    metrics = content.get("metrics") or []
    chart = content.get("chart_spec") or {}
    data = []
    for m in metrics:
        if isinstance(m, dict):
            data.append((str(m.get("label") or m.get("name") or ""), m.get("value"), str(m.get("description") or "")))
    if not data and isinstance(chart, dict):
        for p in chart.get("data_points") or []:
            if isinstance(p, dict):
                data.append((str(p.get("label", "")), p.get("value"), ""))
    if not data:
        return _cards(content, theme)
    # Big-number treatment for <=3, bar chart otherwise.
    if len(data) <= 3:
        cells = []
        for label, value, desc in data[:3]:
            cells.append(
                f'<div class="metric"><div class="big">{esc(value)}</div>'
                f'<div class="mlabel">{esc(label)}</div>'
                + (f'<div class="mdesc">{esc(desc)}</div>' if desc else "")
                + "</div>"
            )
        return _header(content) + '<div class="metrics">' + "".join(cells) + "</div>"
    nums = []
    for _, v, _d in data:
        try:
            nums.append(float(re.sub(r"[^0-9.\-]", "", str(v)) or 0))
        except ValueError:
            nums.append(0.0)
    peak = max(nums) or 1.0
    cols = []
    for (label, value, _desc), num in list(zip(data, nums))[:6]:
        h = max(8, round(num / peak * 100))
        cols.append(
            f'<div class="bar-col"><div class="bar-val">{esc(value)}</div>'
            f'<div class="bar" style="height:{h}%"></div>'
            f'<div class="bar-lab">{esc(label)}</div></div>'
        )
    return _header(content) + '<div class="bars">' + "".join(cols) + "</div>"


_MATRIX_LABELS = ("Top-left", "Top-right", "Bottom-left", "Bottom-right")


def _matrix(content: dict, theme: Theme) -> str:
    ex = content.get("exhibit_spec") or {}
    labels = [str(x) for x in (ex.get("quadrant_labels") or [])][:4]
    items = _normalize_items(content)[:4]
    quads = []
    for i in range(4):
        it = items[i] if i < len(items) else {"title": "", "body": ""}
        label = labels[i] if i < len(labels) else _MATRIX_LABELS[i]
        title = it["title"] or _fit(it["body"].split(".")[0] if it["body"] else "", 60)
        body = _fit(it["body"], 130) if it["title"] else ""
        quads.append(
            f'<div class="quad"><div class="q-label">{esc(label)}</div>'
            f'<div class="q-title">{esc(title)}</div>'
            + (f'<div class="q-body">{esc(body)}</div>' if body else "")
            + "</div>"
        )
    return _header(content) + '<div class="matrix">' + "".join(quads) + "</div>"


def _timeline(content: dict, theme: Theme) -> str:
    items = _normalize_items(content)[:6]
    rows = []
    for i, it in enumerate(items, 1):
        title = _fit(it["title"] or it["text"], 70)
        body = _fit(it["body"], 150) if it["title"] else ""
        rows.append(
            f'<div class="tl-item"><span class="tl-dot">{i}</span>'
            f'<div class="tl-text"><div class="tl-title">{esc(title)}</div>'
            + (f'<div class="tl-body">{esc(body)}</div>' if body else "")
            + "</div></div>"
        )
    return _header(content) + '<div class="timeline">' + "".join(rows) + "</div>"


def _layers(content: dict, theme: Theme) -> str:
    items = _normalize_items(content)[:5]
    rows = []
    for it in items:
        title = it["title"] or _fit(it["body"].split(".")[0] if it["body"] else "", 70)
        body = _fit(it["body"], 160) if it["title"] else ""
        rows.append(
            f'<div class="layer"><div class="ly-title">{esc(title)}</div>'
            f'<div class="ly-body">{esc(body)}</div></div>'
        )
    return _header(content) + '<div class="layers">' + "".join(rows) + "</div>"


def _columns(content: dict, theme: Theme) -> str:
    items = _normalize_items(content)[:3]
    if not items:
        return _cards(content, theme)
    cls = "c3" if len(items) >= 3 else "c2"
    cols = []
    for it in items:
        head = _fit(it["title"] or (it["body"].split(".")[0] if it["body"] else ""), 70)
        body = _fit(it["body"], 170) if it["title"] else ""
        item_html = (
            f'<div class="col-item"><span class="ck">{icon_svg("check")}</span>'
            f'<span>{esc(body)}</span></div>'
            if body
            else ""
        )
        cols.append(f'<div class="col"><div class="col-head">{esc(head)}</div>{item_html}</div>')
    return _header(content) + f'<div class="columns {cls}">' + "".join(cols) + "</div>"


def _big_stat(content: dict, theme: Theme) -> str:
    metrics = content.get("metrics") or []
    data = []
    for m in metrics:
        if isinstance(m, dict):
            data.append(
                (
                    str(m.get("value", "")),
                    str(m.get("label") or m.get("name") or ""),
                    str(m.get("description") or ""),
                )
            )
    if not data:
        return _cards(content, theme)
    data = data[:3]
    cls = "c3" if len(data) >= 3 else "c2"
    cells = []
    for value, label, desc in data:
        cells.append(
            f'<div class="stat"><div class="s-big">{esc(value)}</div>'
            f'<div class="s-label">{esc(label)}</div>'
            + (f'<div class="s-desc">{esc(desc)}</div>' if desc else "")
            + "</div>"
        )
    return _header(content) + f'<div class="stat-grid {cls}">' + "".join(cells) + "</div>"


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #
# "List-ish" primitives are interchangeable for content that is a set of items,
# so the history-aware selector can rotate among them to break up monotony.
_LIST_PRIMS = ["cards", "rows", "callout_list", "columns", "steps"]


def _primitive_fits(prim: str, n: int) -> bool:
    if prim == "columns":
        return 2 <= n <= 3
    if prim == "rows":
        return 1 <= n <= 5
    if prim == "callout_list":
        return n >= 2
    if prim == "steps":
        return n >= 2
    if prim == "cards":
        return n >= 1
    return True


def _natural_primitive(content: dict) -> str:
    """Map a slide to its best-fit primitive, family-complete (no silent
    collapse of distinct composition families into ``cards``)."""
    family = (content.get("composition_family") or "").lower()
    role = (content.get("narrative_role") or content.get("slide_type") or "").lower()
    ex = content.get("exhibit_spec") or {}
    ex_type = (ex.get("type") or "").lower()
    has_metrics = bool(content.get("metrics")) or bool((content.get("chart_spec") or {}).get("data_points"))

    if family == "editorial_cover" or role == "cover":
        return "cover"
    if family == "path_forward_close" or ex_type == "recommendation" or role in ("closing", "recommendation"):
        return "closing"
    if ex_type == "comparison_table" and ex.get("rows"):
        return "table"
    if family == "decision_matrix" or ex_type == "matrix_2x2":
        return "matrix"
    if has_metrics or family == "metric_signal" or ex_type in ("chart", "metrics", "kpi"):
        if family == "proof_strip":
            return "big_stat"
        return "metrics"
    if family == "reframe_comparison":
        return "columns"
    if family == "reframe_split":
        return "split"
    if family == "spotlight_quote":
        return "quote"
    if family == "statement_canvas":
        return "statement"
    if family == "circular_trap":
        return "callout_list"
    if family in ("architecture_layers", "operating_map"):
        return "layers"
    if family in ("lifecycle_timeline", "decision_ladder"):
        return "timeline"
    if ex_type == "icon_rows" and role in ("implementation", "reference"):
        return "rows"
    if ex_type in ("process", "steps"):
        return "steps"
    if family in ("editorial_spread", "executive_summary") or ex_type == "executive_summary":
        return "callout_list"
    if family in ("evidence_wall", "challenge_cards", "why_it_matters_cards", "source_repair_cards", "toolkit_grid"):
        return "cards"
    if ex_type == "checklist":
        return "cards"
    items = _normalize_items(content)
    if len(items) >= 2:
        return "cards"
    return "statement"


def _choose_primitive(content: dict, history: list[str] | None = None) -> str:
    """Pick a primitive, rotating among interchangeable list primitives to
    avoid the deck collapsing to the same layout slide after slide."""
    natural = _natural_primitive(content)
    if not history or natural not in _LIST_PRIMS:
        return natural
    n = len(_normalize_items(content))
    recent = history[-2:]
    soft_cap = max(2, (len(history) + 1) // 3 + 1)
    overused = history.count(natural) >= soft_cap
    if natural in recent or overused:
        for alt in _LIST_PRIMS:
            if alt == natural or alt in recent:
                continue
            if _primitive_fits(alt, n):
                return alt
    return natural


_PRIMITIVES = {
    "cover": _cover,
    "closing": _closing,
    "statement": _statement,
    "quote": _quote,
    "cards": _cards,
    "rows": _rows,
    "steps": _steps,
    "split": _split,
    "table": _table,
    "callout_list": _callout_list,
    "metrics": _metrics,
    "matrix": _matrix,
    "timeline": _timeline,
    "layers": _layers,
    "columns": _columns,
    "big_stat": _big_stat,
}


def _footer(content: dict, theme: Theme, index: int, total: int) -> str:
    labels = (
        content.get("source_labels")
        or content.get("sources")
        or content.get("source_refs")
        or []
    )
    src = ""
    for label in labels:
        t = _clean_sentence(_as_text(label))
        if t and t.lower() not in ("uploaded source", "source needed", "[source needed]"):
            src = t
            break
    src_html = f'<div class="src">Source: {esc(src)}</div>' if src else "<div class='src'></div>"
    logo_html = ""
    if theme.logo_path:
        logo_html = f'<img class="logo" src="file://{esc(theme.logo_path)}" alt=""/>'
    pg = f'<div class="pg">{index + 1:02d} / {total:02d}</div>'
    return f'<div class="foot">{src_html}{logo_html}{pg}</div>'


def render_slide_html(
    outline,
    theme: Theme,
    mode: str,
    index: int,
    total: int,
    history: list[str] | None = None,
) -> str:
    content = _content(outline)
    primitive = _choose_primitive(content, history)
    if history is not None:
        history.append(primitive)
    builder = _PRIMITIVES.get(primitive, _cards)
    inner = builder(content, theme)
    extra_class = ""
    if primitive == "cover":
        extra_class = " cover"
    foot = "" if primitive == "cover" else _footer(content, theme, index, total)
    return f'<section class="slide {mode}{extra_class}">{inner}{foot}</section>'
