# SlideAgent — Product Context

## Why This Exists
Status reporting in pharma R&D is high-frequency, high-stakes, and heavily templated. The same slide structures recur across weekly, monthly, and quarterly cycles — portfolio status, program updates, IMB meeting materials, leadership summaries. The data changes; the structure doesn't. Yet analysts spend significant time manually populating these decks, reformatting pasted content, and adjusting layouts when text overflows. SlideAgent eliminates that overhead.

The second use case — branded content generation — addresses a different pain point: when someone needs to build a new deck (a project proposal, a team briefing, an ad-hoc leadership update) and has the content but not the design skill or time to lay out 15 slides in PowerPoint. They provide a brief; SlideAgent produces a complete, on-brand draft.

## User Experience Goals

### Mode 1 (Template Population)
The user experience should feel like filling out a smart form, not building a presentation. The user:
1. Selects a template from the registry
2. Provides structured input (JSON, CSV, Excel, or a generated form based on the template schema)
3. Reviews a thumbnail preview of the generated deck
4. Downloads the PPTX

The system handles all formatting, constraint enforcement, and XML injection invisibly. If data is missing or too long, the UI surfaces specific, actionable errors — not generic failures.

### Mode 2 (Branded Content Generation)
The user experience should feel like briefing a skilled colleague. The user:
1. Selects a branding template
2. Provides a topic brief (freeform text, bullet points, or structured sections)
3. Reviews the agent's proposed deck outline (slide count, layout per slide, narrative arc) and can edit it
4. Approves the outline, triggering full content generation
5. Reviews thumbnail preview
6. Downloads the PPTX

The outline review step is intentional — it gives the user a low-cost checkpoint before the expensive content generation pass, and surfaces planning decisions (12 slides vs 8, whether to include an appendix) that users often have opinions about.

## User Pain Points Being Solved
- Copying data from spreadsheets into fixed slide layouts
- Content overflow: text doesn't fit, user manually rewrites or shrinks font
- Inconsistent formatting when multiple people contribute to a deck
- Starting a branded deck from scratch when templates exist but aren't pre-populated
- Version control: generating a fresh deck from the same data source is trivially reproducible

## Competitive Context
- **Manual PowerPoint**: Current state. Slow, error-prone, requires design attention.
- **Copilot in PowerPoint**: Available in M365 but operates on the open document, not as an API, and doesn't support template-driven structured population from external data.
- **Beautiful.ai / Tome / Gamma**: Consumer/SMB SaaS tools. Not enterprise-deployable, no PPTX fidelity guarantee, no Bedrock/internal LLM integration.
- **PPTAgent (open source)**: Closest open-source analog. Research-grade, complex setup, requires multiple external API keys, not designed for fixed template population.

## Key UX Constraints
- **NDA / data sensitivity**: All processing must occur within the Novartis AWS boundary. No data leaves to third-party APIs. Bedrock is the LLM substrate.
- **PPTX output only**: No PDF, no Google Slides. Output must open natively in PowerPoint.
- **Template fidelity in Mode 1**: The template is authoritative. The agent does not redesign, recolor, or alter layouts. It fills slots.
- **Brand fidelity in Mode 2**: Font, color, and spatial structure from the branding template are preserved. Content and layout selection are agent-driven but constrained to available layouts.
