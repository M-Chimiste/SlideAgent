"""Native icon chips — react-icons (Feather) rasterized once into a small PNG
disk cache by the Node worker. Small (~0.3in) picture icons inside accent
circles reproduce the reference-deck look; the deck stays fully editable (an
icon chip is an image the same way a logo is). With no Node available the
caller falls back to the existing glyph/monogram treatment.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

_WORKER = Path(__file__).resolve().parents[2] / "workers" / "icon_renderer.js"
_WORKER_CWD = Path(__file__).resolve().parents[3]  # backend/ (node_modules lives here)
_CACHE_DIR = Path(tempfile.gettempdir()) / "slideforge-icon-cache"

# keyword stems -> Feather icon. First match wins; matched against the model's
# icon hint + the item's lead first, then its body.
_KEYWORD_ICONS: list[tuple[tuple[str, ...], str]] = [
    (("risk", "warn", "danger", "threat", "fail", "break", "gap", "flaw", "problem", "error", "anti"), "FiAlertTriangle"),
    (("check", "valid", "success", "complete", "pass", "approv", "proof", "confirm", "verif"), "FiCheckCircle"),
    (("shift", "transition", "migrat", "adopt", "handoff", "arrow", "next"), "FiArrowRightCircle"),
    (("grow", "increase", "scale", "improve", "gain", "trend", "accelerat", "saturat"), "FiTrendingUp"),
    (("declin", "reduc", "shrink", "erod", "degrad"), "FiTrendingDown"),
    (("cost", "price", "budget", "spend", "curation cost", "expens"), "FiDollarSign"),
    (("data", "database", "record", "catalog", "inventory", "corpus"), "FiDatabase"),
    (("document", "file", "spec", "contract", "report", "paper", "artifact"), "FiFileText"),
    (("layer", "stack", "architecture", "structure", "framework", "foundation"), "FiLayers"),
    (("search", "discover", "find", "explore", "extract", "mine"), "FiSearch"),
    (("target", "goal", "objective", "focus", "priorit", "outcome"), "FiTarget"),
    (("cycle", "loop", "iterate", "refresh", "repeat", "recur"), "FiRefreshCw"),
    (("secur", "protect", "shield", "guard", "govern", "compli", "safe"), "FiShield"),
    (("time", "schedule", "deadline", "cadence", "clock", "phase", "milestone"), "FiClock"),
    (("team", "people", "user", "stakeholder", "human", "leader", "expert", "owner"), "FiUsers"),
    (("setting", "config", "mechanism", "operat", "engine", "orchestrat"), "FiSettings"),
    (("code", "develop", "script", "software", "api", "implement"), "FiCode"),
    (("terminal", "command", "cli", "console"), "FiTerminal"),
    (("book", "learn", "knowledge", "guide", "reference", "onboard"), "FiBookOpen"),
    (("message", "conversation", "chat", "prompt", "dialog", "communicat"), "FiMessageSquare"),
    (("key", "credential", "unlock", "access"), "FiKey"),
    (("lock", "restrict", "constraint", "boundar", "limit"), "FiLock"),
    (("review", "inspect", "observe", "monitor", "watch", "visib", "blind"), "FiEye"),
    (("globe", "market", "global", "world", "region", "domain"), "FiGlobe"),
    (("link", "connect", "depend", "integrat", "chain", "bind"), "FiLink"),
    (("flag", "launch", "release", "ship"), "FiFlag"),
    (("star", "quality", "excellen", "premium", "showcase"), "FiStar"),
    (("award", "benchmark", "standard", "certif", "credib"), "FiAward"),
    (("compass", "navigate", "direction", "strateg", "align"), "FiCompass"),
    (("map", "roadmap", "plan", "path", "journey"), "FiMap"),
    (("energy", "power", "fast", "quick", "speed", "zap", "instant", "automat"), "FiZap"),
    (("chart", "metric", "measure", "kpi", "score", "stat", "quanti", "calibrat"), "FiBarChart2"),
    (("box", "package", "module", "component", "bundle"), "FiBox"),
    (("branch", "version", "fork", "variant", "paradigm"), "FiGitBranch"),
    (("memory", "context", "recall", "brain", "persist", "model"), "FiCpu"),
    (("edit", "write", "author", "draft", "label"), "FiEdit3"),
    (("remove", "delete", "waste", "discard", "cleanup"), "FiTrash2"),
    (("grid", "matrix", "portfolio", "taxonomy", "inventory"), "FiGrid"),
    (("filter", "select", "curat", "triage", "gate"), "FiFilter"),
    (("deploy", "publish", "upload", "production"), "FiUploadCloud"),
    (("question", "unknown", "uncertain", "why", "ambigu"), "FiHelpCircle"),
    (("evidence", "truth", "ground", "source", "grounded"), "FiCheckSquare"),
]

# Rotation for items with no keyword signal — varied but deliberate, never the
# same default icon on every card.
_DEFAULT_ROTATION = [
    "FiTarget", "FiLayers", "FiBarChart2", "FiCompass",
    "FiGrid", "FiBox", "FiBookOpen", "FiZap",
]

_HINT_NAME = re.compile(r"^(Fi|Fa|Md|Hi|Bi)[A-Z][A-Za-z0-9]+$")


def resolve_icon(hint: str, title: str, body: str, index: int) -> str:
    """React-icons name for an item: an explicit react-icons hint wins, then
    keyword stems over hint+lead, then body, then a rotating default."""
    hint = str(hint or "").strip()
    if _HINT_NAME.match(hint):
        return hint
    lead_signal = f"{hint} {title}".lower()
    for stems, name in _KEYWORD_ICONS:
        if any(stem in lead_signal for stem in stems):
            return name
    body_signal = str(body or "").lower()
    for stems, name in _KEYWORD_ICONS:
        if any(stem in body_signal for stem in stems):
            return name
    return _DEFAULT_ROTATION[index % len(_DEFAULT_ROTATION)]


def icon_file(icon_name: str, color_hex: str = "FFFFFF") -> Path | None:
    """Cached PNG for a react-icons name, or None when Node/worker are absent
    (caller falls back to the glyph treatment)."""
    color = re.sub(r"[^0-9a-fA-F]", "", str(color_hex))[:6] or "FFFFFF"
    safe = re.sub(r"[^a-z0-9]+", "-", icon_name.lower()).strip("-") or "icon"
    path = _CACHE_DIR / f"{safe}-{color.lower()}.png"
    if path.exists() and path.stat().st_size > 0:
        return path
    if shutil.which("node") is None or not _WORKER.exists():
        return None
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            ["node", _WORKER.as_posix(), icon_name, color, path.as_posix()],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
            cwd=_WORKER_CWD.as_posix(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode == 0 and path.exists() and path.stat().st_size > 0:
        return path
    return None
