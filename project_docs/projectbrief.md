# SlideAgent — Project Brief

## One-Liner
An AI-powered PowerPoint generation service that produces status decks and branded presentations from structured input data and a predefined template library, backed by AWS Bedrock and a React + FastAPI web interface.

## Problem Statement
Creating status decks and branded presentations at Novartis is time-consuming and repetitive. Analysts and technical leads maintain the same slide structures across reporting cycles, manually copying data into fixed templates or building branded decks from scratch. SlideAgent automates both workflows: populating known templates from structured inputs, and authoring new content-rich decks that conform to brand guidelines without requiring manual slide construction.

## Goals
- Reduce time-to-deck for recurring status reports from hours to minutes
- Maintain pixel-perfect template fidelity for regulated or standardized reporting formats
- Enable content-first deck creation within brand guardrails without requiring design skill
- Produce PPTX output compatible with Microsoft PowerPoint (no conversion step)
- Be deployable in Novartis AWS environment with minimal ops overhead
- Be extensible: designed for eventual absorption into Ariadne as a module

## Non-Goals (v1)
- Real-time collaborative editing
- Native desktop application (web-first)
- Support for Google Slides or Keynote output formats
- Automatic image sourcing or generation
- Direct PowerPoint COM automation (no Windows dependency)

## Two Core Modes
1. **Template Population** — Fill a fully-designed, fixed-layout template with structured input data. The agent's role is data mapping, coercion, and constraint enforcement. Minimal LLM creative output.
2. **Branded Content Generation** — Use a branding template (layouts, colors, fonts) as a visual framework, but author slide content and structure from scratch based on freeform or structured input. The agent plans the deck, selects layouts, generates content, and validates fit.

## Success Criteria
- Mode 1: Given valid input data, produces a correct PPTX with zero empty required fields and all content within shape bounds, in under 30 seconds
- Mode 2: Given a topic brief and branding template, produces a coherent, on-brand deck with appropriate layout variety, in under 90 seconds
- Both modes: Output opens without errors in Microsoft PowerPoint and passes visual QA

## Stakeholders
- Primary user: Christian (Technical Director, Agentic AI, Novartis R&D)
- Future users: R&D team members, project leads generating recurring status decks
- Future integration target: Ariadne desktop automation framework

## Timeline
- Phase 1: Core pipeline + Mode 1 for a single status deck template
- Phase 2: Mode 2 + layout library + deck planner
- Phase 3: Template registry UI, multi-template support, Ariadne integration
