"""Inline SVG icon set for HTML-rendered slides.

Clean Feather-style line icons (24x24, stroke=currentColor) rendered inside
circular badges to match the reference deck's visual language. Semantic names
are resolved from planner-provided icon hints or from keyword matching against
card titles, with a safe default so a missing mapping never breaks rendering.
"""

from __future__ import annotations

# Inner SVG markup for each icon (viewBox 0 0 24 24, stroke=currentColor).
_ICONS: dict[str, str] = {
    "check": '<polyline points="20 6 9 17 4 12"/>',
    "check-circle": '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
    "target": '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
    "trending-up": '<polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>',
    "trending-down": '<polyline points="23 18 13.5 8.5 8.5 13.5 1 6"/><polyline points="17 18 23 18 23 12"/>',
    "link": '<path d="M15 7h3a5 5 0 0 1 0 10h-3"/><path d="M9 17H6A5 5 0 0 1 6 7h3"/><line x1="8" y1="12" x2="16" y2="12"/>',
    "shuffle": '<polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/><line x1="4" y1="4" x2="9" y2="9"/>',
    "eye": '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
    "eye-off": '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/>',
    "award": '<circle cx="12" cy="8" r="7"/><polyline points="8.21 13.89 7 23 12 20 17 23 15.79 13.88"/>',
    "gavel": '<path d="M14 13l-7.5 7.5a2.12 2.12 0 0 1-3-3L11 10"/><path d="M16 16l6-6"/><path d="M8 8l6-6"/><path d="M9 7l8 8"/><path d="M21 11l-8-8"/>',
    "flask": '<path d="M9 3h6"/><path d="M10 3v6l-5.5 9.5A1 1 0 0 0 5.4 20h13.2a1 1 0 0 0 .86-1.5L14 9V3"/><line x1="8" y1="14" x2="16" y2="14"/>',
    "file-text": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><line x1="10" y1="9" x2="8" y2="9"/>',
    "clipboard": '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/>',
    "sliders": '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    "database": '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>',
    "refresh": '<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
    "search": '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    "archive": '<polyline points="21 8 21 21 3 21 3 8"/><rect x="1" y="3" width="22" height="5"/><line x1="10" y1="12" x2="14" y2="12"/>',
    "share": '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>',
    "book": '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
    "code": '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
    "terminal": '<polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>',
    "zap": '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "tag": '<path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/>',
    "x-circle": '<circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>',
    "alert": '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    "users": '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "user-check": '<path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><polyline points="17 11 19 13 23 9"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    "building": '<path d="M3 21h18"/><path d="M5 21V3h14v18"/><path d="M9 7h2M13 7h2M9 11h2M13 11h2M9 15h2M13 15h2"/>',
    "maximize": '<polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/>',
    "layers": '<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>',
    "lightbulb": '<path d="M9 18h6"/><path d="M10 22h4"/><path d="M15.09 14c.18-.98.65-1.74 1.41-2.5A4.65 4.65 0 0 0 18 8 6 6 0 0 0 6 8c0 1 .23 2.23 1.5 3.5.76.76 1.23 1.52 1.41 2.5"/>',
    "cloud": '<path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/>',
    "arrow-right": '<line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>',
    "dollar": '<line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>',
    "scale": '<line x1="12" y1="3" x2="12" y2="21"/><line x1="6" y1="21" x2="18" y2="21"/><line x1="3" y1="7" x2="21" y2="7"/><path d="M6 7l-3 6a3 3 0 0 0 6 0z"/><path d="M18 7l-3 6a3 3 0 0 0 6 0z"/>',
    "briefcase": '<rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>',
    "compass": '<circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/>',
    "git-branch": '<line x1="6" y1="3" x2="6" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>',
    "map": '<polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"/><line x1="8" y1="2" x2="8" y2="18"/><line x1="16" y1="6" x2="16" y2="22"/>',
    "key": '<path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/>',
    "lock": '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "filter": '<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>',
    "anchor": '<circle cx="12" cy="5" r="3"/><line x1="12" y1="22" x2="12" y2="8"/><path d="M5 12H2a10 10 0 0 0 20 0h-3"/>',
    "dot": '<circle cx="12" cy="12" r="4" fill="currentColor" stroke="none"/>',
}

# Keyword -> icon name. First match wins; order matters (specific before generic).
_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("cost", "expensive", "budget", "price", "pricing", "cheap", "afford", "revenue", "roi"), "dollar"),
    (("catalog", "database", "data store", "datastore", "warehouse", "repository", "store"), "database"),
    (("balance", "fair", "equit", "trade-off", "tradeoff", "weigh"), "scale"),
    (("compare", "comparison", "versus", " vs ", "benchmark"), "trending-up"),
    (("grow", "increase", "improv", "scal", "accelerat", "uplift", "gain"), "trending-up"),
    (("declin", "decrease", "drop", "erode", "loss", "reduc", "shrink"), "trending-down"),
    (("circular", "loop", "cycle", "recurs", "repeat", "iterat", "refresh", "renew"), "refresh"),
    (("random", "noise", "mismatch", "distribut", "shuffle", "vary", "varianc"), "shuffle"),
    (("blind", "hidden", "unseen", "overlook", "miss", "gap", "invisible"), "eye-off"),
    (("visib", "observ", "monitor", "inspect", "watch", "see"), "eye"),
    (("regulat", "complian", "legal", "govern", "ruling", "verdict", "judge"), "gavel"),
    (("trust", "secur", "protect", "safe", "defen", "risk", "guard"), "shield"),
    (("experiment", "lab", "research", "test", "trial", "hypoth"), "flask"),
    (("document", "report", "paper", "spec", "contract", "file", "record"), "file-text"),
    (("checklist", "criteria", "requirement", "approv", "validat", "verif", "confirm", "accept"), "check-circle"),
    (("config", "setup", "settings", "parameter", "tune", "adjust", "calibrat"), "sliders"),
    (("automat", "process", "engine", "mechanic", "pipeline", "workflow", "operat", "execut"), "settings"),
    (("search", "discover", "find", "explore", "detect", "surfac", "uncover"), "search"),
    (("archive", "storage", "persist", "retain", "backup"), "archive"),
    (("orchestr", "coordinat", "network", "connect", "integrat", "link", "distribut"), "share"),
    (("knowledge", "learn", "book", "guide", "manual", "documentation", "reference"), "book"),
    (("code", "program", "develop", "engineer", "build", "implement"), "code"),
    (("terminal", "command", "cli", "script", "shell"), "terminal"),
    (("fast", "speed", "quick", "instant", "rapid", "power", "energy", "boost"), "zap"),
    (("time", "schedul", "deadline", "latency", "duration", "temporal", "when"), "clock"),
    (("label", "tag", "categor", "classif", "metadata", "annotat"), "tag"),
    (("fail", "error", "broken", "wrong", "defect", "fault", "reject", "block"), "x-circle"),
    (("warn", "caution", "alert", "danger", "threat", "issue", "problem", "challenge"), "alert"),
    (("team", "people", "stakeholder", "customer", "audience", "user", "human", "collaborat"), "users"),
    (("ownership", "accountab", "responsib", "assign", "role"), "user-check"),
    (("layer", "stack", "tier", "architect", "structur", "component", "modul"), "layers"),
    (("insight", "idea", "innovat", "creativ", "vision", "concept", "principle"), "lightbulb"),
    (("cloud", "synthetic", "generat", "infrastruct", "platform"), "cloud"),
    (("decision", "choice", "select", "next step", "transition", "shift", "move"), "arrow-right"),
    (("enterprise", "organization", "company", "business", "firm", "department"), "building"),
    (("expand", "broaden", "extend", "reach", "coverage", "scope"), "maximize"),
    (("target", "goal", "objective", "outcome", "result", "focus", "precision"), "target"),
    (("roadmap", "path", "direction", "journey", "future", "forward", "navigat"), "compass"),
    (("branch", "version", "git", "fork", "variant"), "git-branch"),
    (("key", "access", "credential", "unlock", "secret"), "key"),
    (("lock", "private", "restrict", "confiden", "permission"), "lock"),
    (("filter", "screen", "sift", "refine", "curat", "select subset", "sampl"), "filter"),
    (("anchor", "ground", "found", "base", "root", "stable", "reliab"), "anchor"),
    (("map", "territory", "landscape", "domain", "region"), "map"),
    (("award", "best", "win", "success", "achiev", "quality"), "award"),
]


def resolve_icon(hint: str | None = None, text: str | None = None) -> str:
    """Pick an icon name from an explicit hint and/or descriptive text."""
    if hint:
        normalized = hint.strip().lower().replace("_", "-").replace(" ", "-")
        if normalized in _ICONS:
            return normalized
        # try the hint as keyword text too
        for keywords, name in _KEYWORDS:
            if any(k.strip("-") in normalized for k in keywords):
                return name
    if text:
        low = f" {text.strip().lower()} "
        for keywords, name in _KEYWORDS:
            if any(k in low for k in keywords):
                return name
    return "dot"


def icon_svg(name: str, *, size: int = 24, stroke_width: float = 2.0) -> str:
    """Return a complete <svg> element for the named icon."""
    inner = _ICONS.get(name) or _ICONS["dot"]
    return (
        f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" '
        f'stroke="currentColor" stroke-width="{stroke_width}" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true">{inner}</svg>'
    )


def icon_for(hint: str | None = None, text: str | None = None, **kw) -> str:
    """Resolve and render in one call."""
    return icon_svg(resolve_icon(hint, text), **kw)
