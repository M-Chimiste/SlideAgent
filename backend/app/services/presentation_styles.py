"""Presentation-style registry.

A ``PresentationStyle`` re-parameterizes the planner — persona, narrative arc,
title doctrine, section labels, and exhibit emphasis — so a deck can read as an
investor pitch, a lecture, a sales deck, etc., instead of only a consulting
report. ``consulting`` is the default and reproduces the original planner prompt
and behavior byte-for-byte.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PresentationStyle:
    key: str
    label: str                              # used in user-prompt wording ("a {label} deck")
    persona: str                            # opening persona sentence (non-consulting prompt)
    arc: str                                # rule 2 — narrative arc
    title_rule: str                         # rule 3 — title doctrine
    audience: str                           # blueprint audience
    default_design_language: str
    section_plan_labels: tuple[tuple[str, str], tuple[str, str], tuple[str, str]]
    exhibit_emphasis: tuple[str, ...]
    section_labels: dict[str, str] = field(default_factory=dict)  # role -> eyebrow override
    keywords: tuple[str, ...] = ()


_CONSULTING = PresentationStyle(
    key="consulting",
    label="consulting",
    persona=(
        "a senior engagement manager at a top-tier strategy firm (McKinsey/BCG/Bain) "
        "building an executive-ready, consulting-quality slide deck."
    ),
    arc=(
        "SCR NARRATIVE. Structure the arc as Situation -> Complication -> Resolution, weighting "
        "roughly 10-15% Situation, 15-20% Complication, and 60-70% Resolution."
    ),
    title_rule=(
        "ACTION TITLES. Every slide title is a complete sentence with a verb stating the conclusion "
        "(the 'so what'), 15 words or fewer; never a topic label, never the word 'and'."
    ),
    audience="Engineering and product leaders",
    default_design_language="editorial_serif",
    section_plan_labels=(
        ("Frame the decision", "Establish thesis, stakes, and leadership question."),
        ("Prove the shift", "Use evidence and exhibits to show why the old model breaks."),
        ("Commit to execution", "Translate the answer into operating choices and next steps."),
    ),
    exhibit_emphasis=("comparison_table", "icon_rows", "callouts"),
    keywords=("consulting", "strategy", "engagement", "diagnostic", "operating model"),
)

_INVESTOR = PresentationStyle(
    key="investor_pitch",
    label="investor pitch",
    persona=(
        "a startup founder and pitch coach building a venture-grade investor pitch that earns "
        "the next meeting."
    ),
    arc=(
        "NARRATIVE ARC. Open with the problem and the size of the opportunity, then the product and "
        "traction, then the ask — momentum builds toward the raise."
    ),
    title_rule=(
        "TITLES. Each title is a confident, specific claim about the opportunity or traction (a number "
        "whenever possible), 12 words or fewer."
    ),
    audience="Investors and venture partners",
    default_design_language="bold_minimal",
    section_plan_labels=(
        ("Problem & opportunity", "Name the painful problem and the size of the market."),
        ("Product & traction", "Show the product and the evidence it is working."),
        ("The ask", "State the raise, the use of funds, and the milestones it buys."),
    ),
    exhibit_emphasis=("metric_chart", "comparison_table", "callouts"),
    section_labels={"problem": "THE PROBLEM", "evidence": "TRACTION", "closing": "THE ASK"},
    keywords=("pitch", "investor", "raise", "seed", "series a", "venture", "fundrais", "valuation", "traction", "startup"),
)

_SALES = PresentationStyle(
    key="sales",
    label="sales",
    persona=(
        "a senior solutions consultant building a customer-facing sales deck that moves a buyer to act."
    ),
    arc=(
        "NARRATIVE ARC. Start from the buyer's pain and the cost of inaction, then the solution and "
        "proof, then the offer and next step."
    ),
    title_rule=(
        "TITLES. Each title is a benefit-led claim in the buyer's language tied to their outcome, "
        "12 words or fewer."
    ),
    audience="Prospective customers and economic buyers",
    default_design_language="warm_magazine",
    section_plan_labels=(
        ("The buyer's challenge", "Name the buyer's pain and the cost of inaction."),
        ("Our solution & proof", "Show the solution and the proof it delivers."),
        ("The offer & next step", "Make the offer concrete and define the next step."),
    ),
    exhibit_emphasis=("comparison_table", "callouts", "metric_chart"),
    section_labels={"problem": "THE CHALLENGE", "evidence": "PROOF", "closing": "NEXT STEP"},
    keywords=("sales", "customer", "prospect", "buyer", "pricing", "proposal", "roi", "value prop", "deal"),
)

_LECTURE = PresentationStyle(
    key="academic_lecture",
    label="lecture",
    persona=(
        "a university lecturer building a clear, well-structured teaching deck that builds "
        "understanding step by step."
    ),
    arc=(
        "NARRATIVE ARC. Motivate the question, develop the concepts in logical order with examples, "
        "then summarize the takeaways and implications."
    ),
    title_rule=(
        "TITLES. Each title states the concept or finding for that slide in plain, precise language; "
        "a short topic phrase is acceptable when it aids learning."
    ),
    audience="Students and researchers",
    default_design_language="editorial_serif",
    section_plan_labels=(
        ("Motivation & question", "Motivate the topic and pose the central question."),
        ("Concepts & evidence", "Develop concepts in order with examples and evidence."),
        ("Takeaways", "Summarize the key takeaways and what they imply."),
    ),
    exhibit_emphasis=("table_reference", "two_column", "comparison_table"),
    section_labels={"problem": "MOTIVATION", "evidence": "EVIDENCE", "closing": "TAKEAWAYS"},
    keywords=("lecture", "course", "class", "teach", "academic", "student", "curriculum", "theory", "syllabus"),
)

_TECHNICAL = PresentationStyle(
    key="technical_deep_dive",
    label="technical deep-dive",
    persona=(
        "a staff engineer building a rigorous technical deep-dive for an engineering audience."
    ),
    arc=(
        "NARRATIVE ARC. Frame the system or problem and its constraints, walk the architecture and "
        "mechanisms, then the trade-offs, results, and recommendation."
    ),
    title_rule=(
        "TITLES. Each title states a precise technical claim or decision (with the mechanism or metric), "
        "14 words or fewer."
    ),
    audience="Engineers and technical leaders",
    default_design_language="technical_mono",
    section_plan_labels=(
        ("Problem & constraints", "Frame the system, the problem, and the constraints."),
        ("Architecture & mechanism", "Walk the architecture and how it works."),
        ("Trade-offs & results", "Cover trade-offs, results, and the recommendation."),
    ),
    exhibit_emphasis=("comparison_table", "icon_rows", "table_reference"),
    section_labels={"problem": "PROBLEM", "framework": "ARCHITECTURE", "closing": "RECOMMENDATION"},
    keywords=("architecture", "system", "engineering", "technical", "latency", "throughput", "infrastructure", "protocol"),
)

_KEYNOTE = PresentationStyle(
    key="keynote_narrative",
    label="keynote",
    persona=(
        "a keynote speaker crafting a bold, story-driven talk that changes how the audience sees "
        "the topic."
    ),
    arc=(
        "NARRATIVE ARC. Open with a provocative hook, build tension through a few vivid beats, then "
        "land on a memorable, inspiring takeaway."
    ),
    title_rule=(
        "TITLES. Each title is a short, punchy, evocative statement — one idea, roughly 8 words or "
        "fewer; favor resonance over completeness."
    ),
    audience="A broad keynote audience",
    default_design_language="bold_minimal",
    section_plan_labels=(
        ("The hook", "Open with a provocative hook that reframes the topic."),
        ("The journey", "Build tension through a few vivid, escalating beats."),
        ("The call to action", "Land on a memorable, inspiring takeaway."),
    ),
    exhibit_emphasis=("callouts", "quote_sidebar", "metric_chart"),
    section_labels={"problem": "THE HOOK", "evidence": "THE TURN", "closing": "THE CALL"},
    keywords=("keynote", "talk", "story", "vision", "manifesto", "inspire", "movement", "stage"),
)

_QBR = PresentationStyle(
    key="status_report_qbr",
    label="status report",
    persona=(
        "an operating leader building a crisp status report / QBR for a leadership review."
    ),
    arc=(
        "NARRATIVE ARC. State where we are versus plan, what changed and why, the risks and decisions "
        "needed, then next-quarter priorities."
    ),
    title_rule=(
        "TITLES. Each title states the status or result plainly with the number (on / ahead / behind "
        "plan), 14 words or fewer."
    ),
    audience="Leadership and cross-functional stakeholders",
    default_design_language="data_forward",
    section_plan_labels=(
        ("Where we stand", "State results versus plan with the numbers."),
        ("What changed & why", "Explain what moved, why, and the risks."),
        ("Decisions & next steps", "Name the decisions needed and the next priorities."),
    ),
    exhibit_emphasis=("metric_chart", "comparison_table", "checklist"),
    section_labels={"problem": "STATUS", "evidence": "DRIVERS", "closing": "NEXT QUARTER"},
    keywords=("status", "update", "quarterly", "qbr", "review", "okr", "kpi", "progress", "report-out", "milestone"),
)

STYLES: dict[str, PresentationStyle] = {
    s.key: s
    for s in (_CONSULTING, _INVESTOR, _SALES, _LECTURE, _TECHNICAL, _KEYNOTE, _QBR)
}
DEFAULT_STYLE = "consulting"
VALID_STYLES = set(STYLES) | {"auto"}

# Filler exhibits safe to inject for variety without risking weak diagrams.
SAFE_FILLER_EXHIBITS = {
    "comparison_table",
    "icon_rows",
    "callouts",
    "table_reference",
    "checklist",
    "two_column",
}


def get_style(key: str | None) -> PresentationStyle:
    return STYLES.get((key or "").strip().lower(), STYLES[DEFAULT_STYLE])


def infer_style(text: str) -> str:
    """Score the brief/topic text against each style's keywords; default consulting."""
    lowered = (text or "").lower()
    best_key, best_score = DEFAULT_STYLE, 0
    for key, style in STYLES.items():
        score = sum(1 for kw in style.keywords if kw in lowered)
        if score > best_score:
            best_key, best_score = key, score
    return best_key


# --- planner system-prompt composition (non-consulting styles) -------------- #

_SHARED_OPENING = (
    "Every slide must work as a STANDALONE DOCUMENT: it communicates its message clearly even "
    "with no presenter in the room."
)

_RULE1 = (
    "1. LEAD WITH THE ANSWER. State the conclusion first, then the supporting arguments, then the "
    "evidence. The slide titles, read in sequence, must tell the complete story on their own."
)

_SHARED_RULES = """4. ONE MESSAGE PER SLIDE. Each slide makes exactly one point. The subheading names the data shown (with units and time period); the body proves the title.
5. MECE. Every breakdown is Mutually Exclusive and Collectively Exhaustive: no overlaps, no gaps.
6. "SO WHAT" TEST. Every bullet, exhibit, and label must directly support the slide title. If it does not connect, delete it.
7. EVIDENCE QUALITY. Bullets are specific, parallel-in-structure, complete thoughts (3-4 per slide maximum), never vague filler. Prefer concrete nouns and numbers over abstractions. Never repeat a bullet across slides.
8. EXHIBITS THAT ARGUE. Choose the exhibit that proves the point. Charts use direct labels (no legends), let one accent color carry the message, and include a benchmark or target where possible; avoid 3D charts and pie charts with more than five slices.
9. SOURCE DISCIPLINE. Every quantitative claim needs a source. Use only numbers supported by the provided material; mark anything unsupported "[source needed]". Do not invent reports, URLs, people, companies, or dates.

Avoid these credibility killers: text-wall slides, generic filler bullets, decorative elements, data presented without a benchmark, inconsistent formatting, and burying the lead in the body instead of the title.

Return STRICT JSON only. No markdown, comments, reasoning, or any text outside the JSON object."""


def compose_system_prompt(style: PresentationStyle) -> str:
    """Build a planner system prompt for a non-consulting style."""
    return (
        f"You are {style.persona} {_SHARED_OPENING}\n\n"
        "Follow these rules, in priority order:\n\n"
        f"{_RULE1}\n"
        f"2. {style.arc}\n"
        f"3. {style.title_rule}\n"
        f"{_SHARED_RULES}"
    )
