"""The global CSS design system for HTML-rendered slides.

A single cohesive stylesheet drives every layout primitive, so visual variety
comes from *which* primitive a slide uses — never from per-slide restyling.
Theme colors/fonts are injected as custom properties; ``.slide.dark`` and
``.slide.light`` swap the working palette so the dark/light rhythm is automatic.
"""

from __future__ import annotations

from .design_system import Theme


def build_css(theme: Theme) -> str:
    s = theme.heading_scale

    def sz(px: float) -> int:
        return int(round(px * s))

    return f"""
@page {{ size: 13.333in 7.5in; margin: 0; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
html, body {{ margin: 0; padding: 0; }}

.deck {{
  --ink: {theme.ink};
  --teal: {theme.teal};
  --gold: {theme.gold};
  --bg-dark: {theme.background('dark')};
  --bg-light: {theme.background('light')};
  --serif: {theme.serif};
  --sans: {theme.sans};
  --mono: {theme.mono};
  --text-dark: {theme.text_dark};
  --text-dark-muted: {theme.text_dark_muted};
  --text-light: {theme.text_light};
  --text-light-muted: {theme.text_light_muted};
  --card-light: {theme.card_light};
  --card-light-alt: {theme.card_light_alt};
  --card-border-light: {theme.card_border_light};
  --card-dark: {theme.card_dark};
  --card-border-dark: {theme.card_border_dark};
}}

.slide {{
  position: relative;
  width: 1280px;
  height: 720px;
  overflow: hidden;
  page-break-after: always;
  font-family: var(--sans);
  display: flex;
  flex-direction: column;
  padding: {theme.slide_padding};
  color: var(--fg);
}}
.slide:last-child {{ page-break-after: auto; }}

.slide.light {{
  background: var(--bg-light);
  --fg: var(--text-dark);
  --fg-muted: var(--text-dark-muted);
  --eyebrow: var(--teal);
  --headline: var(--ink);
  --card-bg: var(--card-light);
  --card-bg-alt: var(--card-light-alt);
  --card-bd: var(--card-border-light);
  --card-shadow: 0 14px 34px rgba(15,30,50,0.10), 0 2px 6px rgba(15,30,50,0.06);
  --hair: rgba(15,30,50,0.12);
}}
.slide.dark {{
  background: var(--bg-dark);
  --fg: var(--text-light);
  --fg-muted: var(--text-light-muted);
  --eyebrow: var(--gold);
  --headline: var(--text-light);
  --card-bg: var(--card-dark);
  --card-bg-alt: rgba(255,255,255,0.09);
  --card-bd: var(--card-border-dark);
  --card-shadow: 0 16px 40px rgba(0,0,0,0.28);
  --hair: rgba(255,255,255,0.16);
}}

/* ---------- header block ---------- */
.eyebrow {{
  font-size: 13px; font-weight: 700; letter-spacing: {theme.eyebrow_spacing}; text-transform: uppercase;
  color: var(--eyebrow); margin-bottom: 16px; display: flex; align-items: center; gap: 10px;
}}
.eyebrow .tick {{ width: 22px; height: 2px; background: var(--eyebrow); display: inline-block; }}
.headline {{
  font-family: var(--serif); color: var(--headline); font-weight: {theme.headline_weight};
  line-height: 1.07; letter-spacing: -0.012em; max-width: 21ch;
}}
.h-xl {{ font-size: {sz(60)}px; }}
.h-lg {{ font-size: {sz(46)}px; }}
.h-md {{ font-size: {sz(38)}px; }}
.h-sm {{ font-size: {sz(31)}px; max-width: 30ch; }}
.subhead {{
  font-size: 18px; line-height: 1.45; color: var(--fg-muted);
  margin-top: 16px; max-width: 70ch; font-weight: 400;
}}
.head-block {{ margin-bottom: 30px; flex: 0 0 auto; }}
.body-area {{ flex: 1 1 auto; display: flex; flex-direction: column; min-height: 0; overflow: hidden; }}

/* ---------- cards grid ---------- */
.cards {{ display: grid; gap: {theme.card_gap}px; flex: 1 1 auto; align-content: center; }}
.cards.cols-1 {{ grid-template-columns: 1fr; }}
.cards.cols-2 {{ grid-template-columns: 1fr 1fr; }}
.cards.cols-3 {{ grid-template-columns: repeat(3, 1fr); }}
.cards.cols-4 {{ grid-template-columns: repeat(4, 1fr); }}
.cards.rows-2 {{ grid-auto-rows: 1fr; }}

.card {{
  background: var(--card-bg); border: 1px solid var(--card-bd); border-radius: {theme.card_radius}px;
  padding: {theme.card_padding}; box-shadow: var(--card-shadow);
  display: flex; flex-direction: column; gap: 12px; min-height: 0;
}}
.card.center {{ align-items: center; text-align: center; }}
.card-title {{ font-size: 20px; font-weight: 700; color: var(--headline); line-height: 1.2; letter-spacing: -0.01em; }}
.card-body {{ font-size: 15.5px; line-height: 1.5; color: var(--fg-muted); }}

/* graceful overflow: clamp pathologically long bodies instead of clipping */
.card-body, .row-body, .mini-body, .feature-body, .panel-sub, .tick-item .tt {{
  display: -webkit-box; -webkit-box-orient: vertical; overflow: hidden;
}}
.card-body {{ -webkit-line-clamp: 6; }}
.row-body, .mini-body {{ -webkit-line-clamp: 3; }}
.feature-body {{ -webkit-line-clamp: 7; }}
.panel-sub {{ -webkit-line-clamp: 4; }}
.tick-item .tt {{ -webkit-line-clamp: 4; }}
.card.tight {{ padding: 22px 24px; gap: 9px; }}
.card.tight .card-title {{ font-size: 18px; }}
.card.tight .card-body {{ font-size: 14.5px; }}

/* ---------- icon badges ---------- */
.badge {{
  width: 52px; height: 52px; min-width: 52px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center; color: #fff;
}}
.badge.teal {{ background: var(--teal); }}
.badge.gold {{ background: var(--gold); }}
.badge.soft {{ background: rgba(31,122,140,0.14); color: var(--teal); }}
.slide.dark .badge.soft {{ background: rgba(255,255,255,0.10); color: #fff; }}
.badge svg {{ width: 26px; height: 26px; }}
.badge.sm {{ width: 42px; height: 42px; min-width: 42px; }}
.badge.sm svg {{ width: 21px; height: 21px; }}
.card-head {{ display: flex; align-items: center; gap: 14px; }}

/* ---------- numbered chips ---------- */
.chip {{
  width: 40px; height: 40px; min-width: 40px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 17px; color: #fff;
}}
.chip.teal {{ background: var(--teal); }}
.chip.gold {{ background: var(--gold); }}

/* ---------- rows (architecture / list) ---------- */
.rows {{ display: flex; flex-direction: column; gap: 12px; flex: 1 1 auto; justify-content: center; min-height: 0; }}
.row {{
  display: flex; align-items: center; gap: 20px;
  background: var(--card-bg); border: 1px solid var(--card-bd); border-radius: 14px;
  padding: 14px 24px; box-shadow: var(--card-shadow);
}}
.row .row-title {{ font-size: 19px; font-weight: 700; color: var(--headline); width: 290px; min-width: 290px; }}
.row .row-body {{ font-size: 15.5px; line-height: 1.45; color: var(--fg-muted); }}

/* ---------- split / from-to ---------- */
.split {{ display: grid; grid-template-columns: 1fr 64px 1fr; align-items: stretch; gap: 0; flex: 1 1 auto; }}
.split .panel {{
  border-radius: 18px; padding: 34px 36px; display: flex; flex-direction: column; gap: 14px;
  justify-content: center;
  background: var(--card-bg); border: 1px solid var(--card-bd); box-shadow: var(--card-shadow);
}}
.split .panel.accent {{ background: var(--teal); border-color: transparent; color: #fff; }}
.split .panel.accent .panel-kicker {{ color: rgba(255,255,255,0.8); }}
.split .panel.accent .panel-lead {{ color: #fff; }}
.split .panel.accent .panel-sub {{ color: rgba(255,255,255,0.85); }}
.split .arrow {{ display: flex; align-items: center; justify-content: center; }}
.split .arrow .ring {{
  width: 56px; height: 56px; border-radius: 50%; background: var(--gold); color: #fff;
  display: flex; align-items: center; justify-content: center;
}}
.split .arrow .ring svg {{ width: 28px; height: 28px; }}
.panel-kicker {{ font-size: 12px; font-weight: 700; letter-spacing: 0.16em; text-transform: uppercase; color: var(--fg-muted); }}
.panel-lead {{ font-family: var(--serif); font-size: 26px; line-height: 1.22; font-weight: 600; color: var(--headline); font-style: italic; }}
.panel-sub {{ font-size: 15px; line-height: 1.5; color: var(--fg-muted); margin-top: 12px; }}

/* ---------- callout list (big card + icon rows) ---------- */
.callout-grid {{ display: grid; grid-template-columns: 0.82fr 1.18fr; gap: 26px; flex: 1 1 auto; }}
.feature {{
  background: var(--ink); color: #fff; border-radius: 18px; padding: 34px 32px;
  display: flex; flex-direction: column; gap: 16px; justify-content: center; align-items: center; text-align: center;
  box-shadow: 0 18px 40px rgba(0,0,0,0.22);
}}
.slide.dark .feature {{ background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); }}
.feature .badge {{ width: 64px; height: 64px; }}
.feature .badge svg {{ width: 32px; height: 32px; }}
.feature .feature-title {{ font-family: var(--serif); font-size: 25px; font-weight: 600; line-height: 1.18; }}
.feature .feature-body {{ font-size: 15.5px; line-height: 1.55; color: rgba(255,255,255,0.78); }}
.mini-rows {{ display: flex; flex-direction: column; gap: 12px; justify-content: center; }}
.mini-row {{
  display: flex; align-items: flex-start; gap: 16px; background: var(--card-bg);
  border: 1px solid var(--card-bd); border-radius: 13px; padding: 16px 20px; box-shadow: var(--card-shadow);
}}
.mini-row .mini-title {{ font-size: 17px; font-weight: 700; color: var(--headline); margin-bottom: 3px; }}
.mini-row .mini-body {{ font-size: 14.5px; line-height: 1.45; color: var(--fg-muted); }}

/* ---------- comparison table ---------- */
table.cmp {{ width: 100%; border-collapse: separate; border-spacing: 0; flex: 0 0 auto; margin-top: 4px; }}
table.cmp th, table.cmp td {{ text-align: left; padding: 15px 22px; font-size: 15.5px; }}
table.cmp thead th {{
  font-size: 12px; font-weight: 700; letter-spacing: 0.10em; text-transform: uppercase;
  color: var(--eyebrow); border-bottom: 2px solid var(--hair);
}}
table.cmp tbody td {{ border-bottom: 1px solid var(--hair); color: var(--fg-muted); }}
table.cmp tbody td:first-child {{ font-weight: 700; color: var(--headline); }}
table.cmp tbody tr:nth-child(even) td {{ background: var(--card-bg-alt); }}

/* ---------- statement / quote ---------- */
.statement {{ flex: 1 1 auto; display: flex; flex-direction: column; justify-content: center; max-width: 30ch; }}
.statement-grid {{ flex: 1 1 auto; display: grid; grid-template-columns: 1.05fr 0.95fr; gap: 56px; align-items: center; }}
.statement .lead, .statement-claim .lead {{ font-family: var(--serif); line-height: 1.1; font-weight: 600; color: var(--headline); letter-spacing: -0.015em; }}
.lead-xl {{ font-size: {sz(56)}px; }}
.lead-lg {{ font-size: {sz(44)}px; }}
.lead-md {{ font-size: {sz(35)}px; }}
.lead-sm {{ font-size: {sz(28)}px; }}
.statement .support, .statement-claim .support {{ font-size: 19px; line-height: 1.5; color: var(--fg-muted); margin-top: 22px; max-width: 52ch; }}
.statement-claim .eyebrow {{ margin-bottom: 18px; }}
.ticks {{ display: flex; flex-direction: column; gap: 18px; }}
.tick-item {{ display: flex; gap: 15px; align-items: flex-start; }}
.tick-item .tk {{ color: var(--eyebrow); margin-top: 2px; flex: 0 0 auto; }}
.tick-item .tk svg {{ width: 22px; height: 22px; }}
.tick-item .tt {{ font-size: 16.5px; line-height: 1.45; color: var(--fg); }}
.tick-item .tt b {{ color: var(--headline); font-weight: 700; }}
.quote {{ flex: 1 1 auto; display: flex; flex-direction: column; justify-content: center; }}
.quote .mark {{ font-family: var(--serif); font-size: 120px; line-height: 0.6; color: var(--gold); height: 60px; }}
.quote .qtext {{ font-family: var(--serif); font-style: italic; font-size: 40px; line-height: 1.24; font-weight: 500; color: var(--headline); max-width: 24ch; margin-top: 10px; }}
.quote .qattr {{ font-size: 16px; font-weight: 600; letter-spacing: 0.04em; color: var(--eyebrow); margin-top: 28px; }}

/* ---------- metric signal ---------- */
.metrics {{ display: flex; gap: 30px; flex: 1 1 auto; align-items: center; }}
.metric {{ flex: 1; display: flex; flex-direction: column; gap: 8px; }}
.metric .big {{ font-family: var(--serif); font-size: {sz(76)}px; font-weight: 600; line-height: 1; color: var(--headline); }}
.metric .big .unit {{ font-size: {sz(40)}px; }}
.metric .mlabel {{ font-size: 16px; font-weight: 600; color: var(--eyebrow); text-transform: uppercase; letter-spacing: 0.06em; }}
.metric .mdesc {{ font-size: 14.5px; line-height: 1.45; color: var(--fg-muted); }}
.metric + .metric {{ border-left: 1px solid var(--hair); padding-left: 30px; }}

/* ---------- bar chart ---------- */
.bars {{ display: flex; align-items: flex-end; gap: 26px; flex: 1 1 auto; padding: 10px 0 0; }}
.bar-col {{ flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; height: 100%; gap: 10px; }}
.bar {{ width: 78%; max-width: 120px; border-radius: 10px 10px 0 0; background: var(--teal); position: relative; }}
.bar-col:nth-child(even) .bar {{ background: var(--gold); }}
.bar-val {{ font-weight: 700; font-size: 18px; color: var(--headline); }}
.bar-lab {{ font-size: 14px; color: var(--fg-muted); text-align: center; line-height: 1.3; }}

/* ---------- timeline ---------- */
.timeline {{ display: flex; flex-direction: column; flex: 1 1 auto; justify-content: center; }}
.tl-item {{ display: flex; gap: 20px; padding-bottom: 18px; position: relative; }}
.tl-item:last-child {{ padding-bottom: 0; }}
.tl-item::before {{ content: ""; position: absolute; left: 21px; top: 46px; bottom: -2px; width: 2px; background: var(--hair); }}
.tl-item:last-child::before {{ display: none; }}
.tl-dot {{ width: 44px; height: 44px; min-width: 44px; border-radius: 50%; background: var(--teal); color: #fff; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 16px; z-index: 1; }}
.tl-item:nth-child(even) .tl-dot {{ background: var(--gold); }}
.tl-text {{ padding-top: 6px; }}
.tl-title {{ font-size: 18px; font-weight: 700; color: var(--headline); }}
.tl-body {{ font-size: 15px; line-height: 1.5; color: var(--fg-muted); margin-top: 3px; }}

/* ---------- comparison columns ---------- */
.columns {{ display: grid; gap: {theme.card_gap}px; flex: 1 1 auto; align-content: center; }}
.columns.c2 {{ grid-template-columns: 1fr 1fr; }}
.columns.c3 {{ grid-template-columns: repeat(3, 1fr); }}
.col {{ background: var(--card-bg); border: 1px solid var(--card-bd); border-radius: {theme.card_radius}px; padding: 24px 26px; box-shadow: var(--card-shadow); display: flex; flex-direction: column; gap: 14px; }}
.col-head {{ font-family: var(--serif); font-size: 21px; font-weight: 600; color: var(--headline); padding-bottom: 12px; border-bottom: 2px solid var(--hair); }}
.col-item {{ font-size: 15px; line-height: 1.45; color: var(--fg-muted); display: flex; gap: 10px; }}
.col-item .ck {{ color: var(--eyebrow); flex: 0 0 auto; }}
.col-item .ck svg {{ width: 18px; height: 18px; }}

/* ---------- 2x2 matrix ---------- */
.matrix {{ display: grid; grid-template-columns: 1fr 1fr; grid-template-rows: 1fr 1fr; gap: {theme.card_gap}px; flex: 1 1 auto; }}
.quad {{ background: var(--card-bg); border: 1px solid var(--card-bd); border-radius: {theme.card_radius}px; padding: 22px 24px; box-shadow: var(--card-shadow); display: flex; flex-direction: column; gap: 8px; }}
.quad .q-label {{ font-size: 12px; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; color: var(--eyebrow); }}
.quad .q-title {{ font-size: 18px; font-weight: 700; color: var(--headline); line-height: 1.2; }}
.quad .q-body {{ font-size: 14.5px; line-height: 1.45; color: var(--fg-muted); }}

/* ---------- architecture layers ---------- */
.layers {{ display: flex; flex-direction: column; gap: 12px; flex: 1 1 auto; justify-content: center; }}
.layer {{ display: flex; align-items: center; gap: 20px; background: var(--card-bg); border: 1px solid var(--card-bd); border-left: 4px solid var(--teal); border-radius: {theme.card_radius}px; padding: 18px 24px; box-shadow: var(--card-shadow); }}
.layer:nth-child(even) {{ border-left-color: var(--gold); }}
.layer .ly-title {{ font-size: 18px; font-weight: 700; color: var(--headline); width: 280px; min-width: 280px; }}
.layer .ly-body {{ font-size: 15px; line-height: 1.45; color: var(--fg-muted); }}

/* ---------- big-stat grid ---------- */
.stat-grid {{ display: grid; gap: {theme.card_gap}px; flex: 1 1 auto; align-content: center; }}
.stat-grid.c2 {{ grid-template-columns: 1fr 1fr; }}
.stat-grid.c3 {{ grid-template-columns: repeat(3, 1fr); }}
.stat {{ background: var(--card-bg); border: 1px solid var(--card-bd); border-radius: {theme.card_radius}px; padding: 26px 28px; box-shadow: var(--card-shadow); display: flex; flex-direction: column; gap: 8px; }}
.stat .s-big {{ font-family: var(--serif); font-size: {sz(60)}px; font-weight: 600; line-height: 1; color: var(--headline); }}
.stat .s-label {{ font-size: 15px; font-weight: 600; color: var(--eyebrow); text-transform: uppercase; letter-spacing: 0.05em; }}
.stat .s-desc {{ font-size: 14px; line-height: 1.4; color: var(--fg-muted); }}

/* ---------- quote variant ---------- */
.quote.bar {{ padding-left: 30px; border-left: 5px solid var(--gold); }}
.quote.bar .mark {{ display: none; }}

/* ---------- cover ---------- */
.slide.cover {{ justify-content: center; padding: {theme.cover_padding}; }}
.cover .c-eyebrow {{ font-size: 15px; font-weight: 700; letter-spacing: 0.22em; text-transform: uppercase; color: var(--gold); margin-bottom: 26px; }}
.cover .c-title {{ font-family: var(--serif); font-size: {sz(74)}px; line-height: 1.04; font-weight: {theme.headline_weight}; color: #fff; letter-spacing: -0.02em; max-width: 17ch; }}
.cover .c-title.long {{ font-size: {sz(56)}px; }}
.cover .c-sub {{ font-size: 21px; line-height: 1.5; color: rgba(233,239,245,0.8); margin-top: 30px; max-width: 60ch; }}
.cover .pills {{ display: flex; gap: 14px; margin-top: 44px; flex-wrap: wrap; }}
.pill {{ border: 1px solid rgba(255,255,255,0.28); border-radius: 999px; padding: 11px 22px; font-size: 15px; font-weight: 600; color: rgba(255,255,255,0.92); }}

/* ---------- closing ---------- */
.close-actions {{ display: flex; flex-direction: column; gap: 16px; flex: 1 1 auto; justify-content: center; max-width: 60%; }}
.close-step {{ display: flex; align-items: flex-start; gap: 16px; }}
.close-step .dotn {{ width: 30px; height: 30px; min-width: 30px; border-radius: 50%; background: var(--gold); color: #fff; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 14px; }}
.close-step .ctext {{ font-size: 19px; line-height: 1.4; color: var(--fg); padding-top: 2px; }}
.ask {{ margin-top: 26px; background: var(--gold); color: #19120a; border-radius: 14px; padding: 20px 26px; font-size: 19px; font-weight: 700; max-width: 60%; }}

/* ---------- decorative rings ---------- */
.rings {{ position: absolute; pointer-events: none; opacity: 0.5; }}
.rings.tr {{ top: -130px; right: -120px; }}
.rings.br {{ bottom: -160px; right: -110px; }}

/* ---------- footer ---------- */
.foot {{ position: absolute; left: 84px; right: 84px; bottom: 30px; display: flex; justify-content: space-between; align-items: center; }}
.foot .src {{ font-size: 11.5px; color: var(--fg-muted); letter-spacing: 0.01em; max-width: 70%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.foot .pg {{ font-size: 11.5px; color: var(--fg-muted); font-variant-numeric: tabular-nums; }}
.foot .logo {{ height: 22px; opacity: 0.9; }}

.bottom-line {{
  flex: 0 0 auto; margin-top: 20px; border-radius: 14px; padding: 18px 24px;
  display: flex; align-items: center; gap: 16px; background: var(--ink); color: #fff;
  box-shadow: 0 12px 28px rgba(0,0,0,0.18);
}}
.slide.dark .bottom-line {{ background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.14); }}
.bottom-line .bl-badge {{ color: var(--gold); display: flex; }}
.bottom-line .bl-text {{ font-size: 16px; line-height: 1.45; }}
.bottom-line .bl-text b {{ color: var(--gold); }}
"""


def rings_svg(color: str, position: str = "tr") -> str:
    """Concentric-ring decoration used on cover/closing slides."""
    return (
        f'<svg class="rings {position}" width="460" height="460" viewBox="0 0 460 460" '
        f'fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
        f'<circle cx="230" cy="230" r="228" stroke="{color}" stroke-width="1.5" opacity="0.35"/>'
        f'<circle cx="230" cy="230" r="170" stroke="{color}" stroke-width="1.5" opacity="0.5"/>'
        f'<circle cx="230" cy="230" r="112" stroke="{color}" stroke-width="1.5" opacity="0.7"/>'
        f'<circle cx="230" cy="230" r="54" fill="{color}"/>'
        f"</svg>"
    )


def _grid_svg(color: str, position: str = "tr") -> str:
    """Sparse dot/line grid decoration."""
    dots = "".join(
        f'<circle cx="{20 + c * 52}" cy="{20 + r * 52}" r="3" fill="{color}" opacity="0.55"/>'
        for r in range(8)
        for c in range(8)
    )
    return (
        f'<svg class="rings {position}" width="460" height="460" viewBox="0 0 460 460" '
        f'fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">{dots}</svg>'
    )


def _diagonal_svg(color: str, position: str = "tr") -> str:
    """Diagonal hairline-stripe decoration."""
    lines = "".join(
        f'<line x1="{i * 46}" y1="0" x2="0" y2="{i * 46}" stroke="{color}" stroke-width="1.5" opacity="0.4"/>'
        for i in range(1, 11)
    )
    return (
        f'<svg class="rings {position}" width="460" height="460" viewBox="0 0 460 460" '
        f'fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">{lines}</svg>'
    )


def motif_svg(theme: Theme, slot: str) -> str:
    """Emit the design-language decorative motif for a given slide slot.

    Returns ``""`` when the slot is not in the language's ``motif_slots`` or the
    motif is ``none`` — so a language opts decoration in per slot.
    """
    if slot not in theme.motif_slots or theme.motif == "none":
        return ""
    position = "br" if slot == "closing" else "tr"
    if theme.motif == "grid":
        return _grid_svg(theme.gold, position)
    if theme.motif == "diagonal":
        return _diagonal_svg(theme.gold, position)
    return rings_svg(theme.gold, position)
