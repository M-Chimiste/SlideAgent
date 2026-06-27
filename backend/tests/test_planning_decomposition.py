"""Tests for decomposed (batched / per-slide) generation + the narrative pass."""

import json
import re

from app.models.document import DocumentBundle, DocumentMetadata, DocumentSection
from app.models.generation import DeckBlueprint, DeckSpec, GeneratedSlideSpec
from app.models.planning import StoryBeat, StoryMap
from app.services.content_planner import ContentPlanner


def _bundle() -> DocumentBundle:
    return DocumentBundle(
        job_id="job-1",
        sections=[
            DocumentSection(
                title="Problem",
                level=1,
                content="Synthetic benchmarks create circular validation loops without grounding in reality.",
                source_doc_id="doc-1",
            ),
            DocumentSection(
                title="Solution",
                level=1,
                content="A harness-centric framework reframes benchmarking as a discovery task over proprietary data.",
                source_doc_id="doc-1",
            ),
        ],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Bench"),
        content_inventory=[],
    )


def _story_map(n: int = 4) -> StoryMap:
    beats = [
        StoryBeat(
            beat_number=i + 1,
            role="cover" if i == 0 else "evidence",
            claim=f"Claim number {i + 1} about grounding benchmarks in evidence",
            source_refs=[],
            preferred_exhibit="callouts",
            rationale="reason",
        )
        for i in range(n)
    ]
    return StoryMap(
        status="llm",
        thesis="Bootstrap validated ground truth from proprietary data.",
        narrative_arc="Situation -> Complication -> Resolution",
        recommendation="Approve the first governed pilot.",
        beats=beats,
        source_refs=[],
    )


def _blueprint(n: int = 4) -> DeckBlueprint:
    return DeckBlueprint(deck_title="Bench", audience="Executives", target_slide_count=n)


class _BatchLLM:
    """Echoes one slide per beat in each batch call; records batch sizes."""

    def __init__(self):
        self.calls: list[int] = []

    def complete_json(self, **kwargs):
        prompt = kwargs.get("user_prompt", "")
        match = re.search(r"Beats: (\[.*\])\nAllowed", prompt, re.DOTALL)
        beats = json.loads(match.group(1)) if match else []
        self.calls.append(len(beats))
        return {
            "slides": [
                {
                    "slide_number": beat["slide_number"],
                    "slide_type": "content",
                    "action_title": f"Drive outcome {beat['slide_number']} from validated evidence",
                    "archetype": "callouts",
                    "narrative_role": beat["role"],
                    "exhibit_spec": {"type": "callouts", "points": ["A grounded point", "Another grounded point"]},
                    "sources": ["Uploaded source"],
                }
                for beat in beats
            ]
        }


def test_batched_generation_returns_all_slides():
    planner = ContentPlanner(llm_client=_BatchLLM(), slide_generation_strategy="batched")
    deck = planner._plan_with_llm_batched(
        _bundle(), "instr", "freeform",
        blueprint=_blueprint(4), quality_profile="fast",
        source_compression=None, story_map=_story_map(4), batch_size=4,
    )
    assert deck is not None
    assert [s.slide_number for s in deck.slides] == [1, 2, 3, 4]


def test_batched_uses_batches_of_four():
    llm = _BatchLLM()
    planner = ContentPlanner(llm_client=llm, slide_generation_strategy="batched")
    deck = planner._generate_deck_slides(
        _bundle(), "i", "freeform",
        blueprint=_blueprint(6), quality_profile="fast",
        source_compression=None, story_map=_story_map(6),
    )
    assert len(deck.slides) == 6
    assert llm.calls == [4, 2]


def test_per_slide_calls_once_per_beat():
    llm = _BatchLLM()
    planner = ContentPlanner(llm_client=llm, slide_generation_strategy="per_slide")
    deck = planner._generate_deck_slides(
        _bundle(), "i", "freeform",
        blueprint=_blueprint(4), quality_profile="fast",
        source_compression=None, story_map=_story_map(4),
    )
    assert len(deck.slides) == 4
    assert llm.calls == [1, 1, 1, 1]


def test_fill_deck_to_target_backfills_from_fallback():
    # Use a real blueprint so the deterministic fallback has an archetype
    # sequence to author from (production always builds the blueprint this way).
    planner = ContentPlanner()
    bundle = _bundle()
    blueprint = planner._build_blueprint(
        bundle, "instr", "freeform", quality_profile="fast", length_strategy="auto"
    )
    deck = DeckSpec(
        deck_title="D",
        slides=[GeneratedSlideSpec(slide_number=1, slide_type="content", action_title="First grounded slide title here")],
    )
    target = max(3, blueprint.target_slide_count)
    filled = planner._fill_deck_to_target(deck, target, bundle, "instr", "freeform", blueprint, _story_map(4))
    assert len(filled.slides) > 1  # grew via the deterministic fallback


def test_decomposition_falls_back_to_monolithic_when_batches_empty():
    class EmptyBatchLLM:
        def complete_json(self, **kwargs):
            prompt = kwargs.get("user_prompt", "")
            if "Beats:" in prompt:  # decomposed batch call -> nothing usable
                return {}
            return {  # monolithic fallback call -> a full deck
                "deck_title": "D",
                "slides": [
                    {"slide_number": i + 1, "slide_type": "content", "action_title": f"Monolithic slide {i + 1} drives the point"}
                    for i in range(4)
                ],
            }

    planner = ContentPlanner(llm_client=EmptyBatchLLM(), slide_generation_strategy="batched")
    deck = planner._generate_deck_slides(
        _bundle(), "i", "freeform",
        blueprint=_blueprint(4), quality_profile="fast",
        source_compression=None, story_map=_story_map(4),
    )
    assert deck is not None
    assert deck.slides


class _NarrativeLLM:
    def complete_json(self, **kwargs):
        prompt = kwargs.get("user_prompt", "")
        match = re.search(r"Slides: (\[.*\])", prompt, re.DOTALL)
        slides = json.loads(match.group(1)) if match else []
        return {
            "titles": [
                {"n": s["n"], "title": f"Adopt grounded evaluation step {s['n']} across teams"}
                for s in slides
            ]
        }


def test_narrative_pass_rewrites_titles_but_keeps_cover():
    planner = ContentPlanner(llm_client=_NarrativeLLM())
    deck = DeckSpec(
        deck_title="D",
        slides=[
            GeneratedSlideSpec(
                slide_number=i + 1,
                slide_type="cover" if i == 0 else "content",
                narrative_role="cover" if i == 0 else "evidence",
                action_title=f"Old weak placeholder title number {i + 1}",
            )
            for i in range(4)
        ],
    )
    planner._rewrite_title_ladder_for_narrative(deck, _story_map(4), _bundle())
    assert deck.slides[0].action_title == "Old weak placeholder title number 1"  # cover untouched
    assert any("Adopt grounded evaluation" in s.action_title for s in deck.slides[1:])
    assert planner.last_planning_artifacts["narrative-pass"]["status"].startswith("applied")


def test_narrative_pass_noops_without_client():
    planner = ContentPlanner()  # no llm_client
    titles = [f"Original title number {i}" for i in range(4)]
    deck = DeckSpec(
        deck_title="D",
        slides=[GeneratedSlideSpec(slide_number=i + 1, slide_type="content", action_title=titles[i]) for i in range(4)],
    )
    planner._rewrite_title_ladder_for_narrative(deck, _story_map(4), _bundle())
    assert [s.action_title for s in deck.slides] == titles


def test_sentence_case_title_normalizes_only_title_case():
    p = ContentPlanner()
    # fully Title-Cased -> sentence case, acronyms preserved
    assert p._sentence_case_title("Unstructured AI Prompting Creates Context Rot") == \
        "Unstructured AI prompting creates context rot"
    assert p._sentence_case_title("Migrate Legacy APIs to GitHub Actions") == \
        "Migrate legacy APIs to GitHub actions"
    # already sentence case with proper nouns -> untouched
    for keep in [
        "The Memory Bank architecture provides a persistent external brain",
        "The principles of Agentic Coding are tool-agnostic",
        "Implicit ground truth discovery makes benchmark creation scalable",
        "Ground the next decision in implicit ground truth",
    ]:
        assert p._sentence_case_title(keep) == keep


def test_batched_fills_to_blueprint_target_when_story_map_short():
    # When the story map returns fewer beats than the requested length, the
    # deck is still filled out to the blueprint target (not capped at beat count).
    planner = ContentPlanner(llm_client=_BatchLLM(), slide_generation_strategy="batched")
    bundle = _bundle()
    blueprint = planner._build_blueprint(
        bundle, "instr", "freeform", quality_profile="fast", length_strategy="expanded"
    )
    short_story = _story_map(4)  # only 4 beats vs the expanded target
    deck = planner._plan_with_llm_batched(
        bundle, "instr", "freeform",
        blueprint=blueprint, quality_profile="fast",
        source_compression=None, story_map=short_story, batch_size=4,
    )
    assert deck is not None
    assert blueprint.target_slide_count > 4  # expanded target exceeds the beats
    assert len(deck.slides) > 4  # filled beyond the short story map
    assert len(deck.slides) <= blueprint.target_slide_count


def test_near_duplicate_subject_titles_are_diversified():
    # Two slides that open with the same four-word subject are near-duplicates;
    # the second should be rewritten to a distinct title.
    p = ContentPlanner()
    deck = DeckSpec(
        deck_title="D",
        slides=[
            GeneratedSlideSpec(slide_number=1, slide_type="cover", action_title="Bootstrapping Benchmarks",
                               archetype="cover", narrative_role="cover"),
            GeneratedSlideSpec(slide_number=2, slide_type="content",
                               action_title="Implicit ground truth discovery makes benchmark creation scalable",
                               archetype="callouts", narrative_role="evidence", subheading="Scale"),
            GeneratedSlideSpec(slide_number=3, slide_type="content",
                               action_title="Implicit ground truth discovery turns existing evidence into benchmarks",
                               archetype="icon_rows", narrative_role="evidence", subheading="Reuse"),
        ],
    )
    p._repair_repeated_action_titles(deck)
    prefixes = [p._title_subject_prefix(s.action_title) for s in deck.slides[1:]]
    assert prefixes[0] != prefixes[1]  # shared subject prefix no longer collides


def test_awkward_use_the_case_for_opener_is_flagged_weak():
    p = ContentPlanner()
    awkward = "Use the case for implicit ground truth discovery to sharpen the next operating choice"
    assert p._gate_title_is_weak(awkward)
    assert p.qa._has_meta_title_frame(awkward)
    # a legitimate "Use the <noun>" title must not be a false positive
    legit = "Use the harness to standardize evaluation across domains"
    assert not p._gate_title_is_weak(legit)
    assert not p.qa._has_meta_title_frame(legit)


# --------------------------------------------------------------------------- #
# Type+budget per-slide prompt (3d) + structural-variety controller (3e)
# --------------------------------------------------------------------------- #
def test_beat_authoring_contract_carries_type_and_budget():
    planner = ContentPlanner()
    beat = StoryBeat(
        beat_number=2, role="evidence", claim="Compare the two operating models",
        source_refs=[], preferred_exhibit="comparison_table", rationale="r",
    )
    contract = planner._beat_authoring_contract(beat)
    # comparison_table -> "comparison" slide type with a density floor and budgets.
    assert contract["slide_type"] == "comparison"
    assert contract["min_points"] >= 3
    assert contract["min_points"] <= contract["max_points"]
    assert contract["lead_chars"] > 0 and contract["body_chars"] > 0


def test_batched_prompt_injects_contract_and_evidence():
    captured: dict[str, str] = {}

    class _RecordLLM:
        def complete_json(self, **kwargs):
            captured["prompt"] = kwargs.get("user_prompt", "")
            return {"slides": []}

    planner = ContentPlanner(llm_client=_RecordLLM(), slide_generation_strategy="batched")
    beat = StoryBeat(
        beat_number=1, role="evidence", claim="Ground the model in proprietary data",
        source_refs=[], preferred_exhibit="callouts", rationale="r",
        evidence=["Proprietary logs reveal true failure modes", "Synthetic data hides them"],
    )
    planner._generate_slide_batch(
        [beat], [], _bundle(), _blueprint(1), "fast", _story_map(1), [],
        start_number=1,
    )
    prompt = captured["prompt"]
    assert "authoring_contract" in prompt
    assert "min_points" in prompt and "lead_chars" in prompt
    assert "Proprietary logs reveal true failure modes" in prompt  # bound evidence
    assert "complete thoughts" in prompt.lower()


def _list_deck(n_list: int) -> DeckSpec:
    slides = [GeneratedSlideSpec(slide_number=1, slide_type="cover",
                                 action_title="Deck cover title", archetype="cover",
                                 narrative_role="cover")]
    for i in range(n_list):
        slides.append(GeneratedSlideSpec(
            slide_number=i + 2, slide_type="content",
            action_title=f"List slide number {i + 2} grounded in evidence",
            archetype="callouts", narrative_role="evidence",
            exhibit_spec={"type": "callouts", "points": ["one point here", "two point here", "three point here"]},
        ))
    slides.append(GeneratedSlideSpec(slide_number=n_list + 2, slide_type="closing",
                                     action_title="Closing recommendation slide",
                                     archetype="closing_recommendation", narrative_role="closing"))
    return DeckSpec(deck_title="Deck", audience="Execs", slides=slides)


def test_variety_controller_breaks_consecutive_list_runs():
    from app.services import slide_types

    planner = ContentPlanner()
    deck = _list_deck(7)  # 7 consecutive list-type interior slides
    planner._ensure_structural_variety(deck, _bundle())
    flags = [slide_types.is_list_type(s.slide_type) for s in deck.slides]
    longest = run = 0
    for f in flags:
        run = run + 1 if f else 0
        longest = max(longest, run)
    assert longest <= 2  # no run of three or more list slides


def test_variety_controller_guarantees_non_list_anchor():
    from app.services import slide_types

    planner = ContentPlanner()
    deck = _list_deck(5)
    planner._ensure_structural_variety(deck, _bundle())
    interior = deck.slides[1:-1]
    assert any(not slide_types.is_list_type(s.slide_type) for s in interior)


def test_reassign_picks_stat_when_metrics_present():
    planner = ContentPlanner()
    plain = GeneratedSlideSpec(slide_number=2, slide_type="content",
                               action_title="A grounded list slide title", archetype="callouts")
    planner._reassign_to_non_list_type(plain)
    assert plain.slide_type == "statement"

    metric = GeneratedSlideSpec(slide_number=3, slide_type="content",
                                action_title="A grounded metric slide title", archetype="metric_chart",
                                exhibit_spec={"type": "metric_chart", "metrics": [{"label": "Lift", "value": "30%"}]})
    planner._reassign_to_non_list_type(metric)
    assert metric.slide_type == "stat"


# --------------------------------------------------------------------------- #
# Step A: sentence-aware source extraction (no mid-sentence fragments)
# --------------------------------------------------------------------------- #
def test_source_excerpt_keeps_whole_sentences():
    p = ContentPlanner()
    prose = ("Agentic Coding introduces a disciplined operating model for AI work. "
             "It replaces ephemeral chat context with a persistent memory bank. "
             "Teams gain reproducible, reviewable software outcomes as a result.")
    out = p._source_excerpt(prose, 120)
    assert out  # non-empty
    assert out.rstrip().endswith((".", "!", "?"))  # never ends mid-sentence
    assert "introduces a disciplined" not in out or out.count(".") >= 1


def test_to_bullets_splits_prose_into_complete_sentences():
    p = ContentPlanner()
    prose = ("Synthetic benchmarks create circular validation loops without grounding. "
             "Source-grounded harnesses evaluate models against real organizational evidence. "
             "Benchmark quality improves when test cases come from validated workflows.")
    bullets = p._to_bullets(prose)
    assert len(bullets) >= 3
    assert all(b.rstrip().endswith((".", "!", "?")) for b in bullets)  # complete thoughts


def test_to_bullets_preserves_short_bullet_lines():
    p = ContentPlanner()
    listed = "Shared source of truth\nExplicit operating rules\nBuilt-in quality gates"
    bullets = p._to_bullets(listed)
    assert "Shared source of truth" in bullets


# --------------------------------------------------------------------------- #
# Step C: grammar/completeness title gate (not first-word-verb whitelist)
# --------------------------------------------------------------------------- #
def test_gate_accepts_clean_declarative_titles():
    p = ContentPlanner()
    # Clean declarative claims must NOT be flagged weak (the old gate rejected
    # anything not starting with a whitelisted imperative verb).
    assert not p._gate_title_is_weak("Memory rot compounds across long-running sessions")
    assert not p._gate_title_is_weak("Model contracts make evaluation expectations explicit")
    assert not p._gate_title_is_weak("Shift the developer mental model from coder to manager")


def test_gate_flags_verb_prefix_grafts_and_scaffolding():
    p = ContentPlanner()
    # Imperative opener glued onto a clause with its own finite verb (the verb-graft).
    assert p._gate_title_is_weak("Adopt specifications must precede all AI coding prompts")
    assert p._gate_title_is_weak("Prioritize developers must shift their mental model")
    # Scaffolding frames and too-short titles stay weak.
    assert p._gate_title_is_weak("Use the case for implicit ground truth discovery")
    assert p._gate_title_is_weak("Market overview")


def test_consulting_qa_accepts_declarative_claim_titles():
    from app.services.consulting_qa import ConsultingQA
    qa = ConsultingQA()
    assert qa._has_action_signal("Memory rot compounds across long-running sessions")
    assert qa._has_action_signal("Contracts make expectations explicit")
    # A bare noun phrase still reads as missing a conclusion.
    assert not qa._has_action_signal("Vibe coding operating patterns")


# --------------------------------------------------------------------------- #
# Step D: critique-and-refine pass (LLM enhance + defensive apply + backstop)
# --------------------------------------------------------------------------- #
def _content_deck(title="A weak placeholder", slide_type="content"):
    return DeckSpec(
        deck_title="Deck", audience="Execs",
        slides=[
            GeneratedSlideSpec(slide_number=1, slide_type="cover", action_title="Deck cover title",
                               archetype="cover", narrative_role="cover"),
            GeneratedSlideSpec(slide_number=2, slide_type=slide_type, action_title=title,
                               archetype="callouts", narrative_role="evidence", subheading="ctx",
                               exhibit_spec={"type": "callouts", "points": [{"title": "Old", "body": "Old point here now."}]}),
        ],
    )


def test_refine_pass_noops_without_client():
    p = ContentPlanner()  # no llm_client
    deck = _content_deck("Memory bank holds persistent project context for agents")
    before = [s.action_title for s in deck.slides]
    p._refine_slides(deck, _story_map(2), None, None, _bundle())
    assert [s.action_title for s in deck.slides] == before
    assert p.last_planning_artifacts.get("refine-pass", {}).get("status") == "skipped"


def test_refine_pass_enhances_slide_from_llm():
    class _RefineLLM:
        model = "test-model"
        def complete_json(self, **kwargs):
            return {"slides": [{"n": 2,
                "action_title": "Persistent memory keeps agents reliable across sessions",
                "subheading": "Durable context replaces ephemeral chat history",
                "items": [{"title": "Memory bank", "body": "A persistent external brain holds project context."}],
                "changed": True}]}

    p = ContentPlanner(llm_client=_RefineLLM())
    deck = _content_deck("A weak placeholder")
    p._refine_slides(deck, _story_map(2), None, None, _bundle())
    assert deck.slides[1].action_title == "Persistent memory keeps agents reliable across sessions"
    assert "external brain" in deck.slides[1].exhibit_spec["points"][0]["body"].lower()
    assert p.last_planning_artifacts["refine-pass"]["refined"] >= 1


def test_refine_rejects_weak_refinement():
    class _WeakRefineLLM:
        model = "test-model"
        def complete_json(self, **kwargs):
            return {"slides": [{"n": 2, "action_title": "Bad", "changed": True}]}  # too short -> weak

    p = ContentPlanner(llm_client=_WeakRefineLLM())
    deck = _content_deck("Persistent memory keeps agents reliable across sessions")
    p._refine_slides(deck, _story_map(2), None, None, _bundle())
    # Defensive apply: a weak refinement never degrades the slide.
    assert deck.slides[1].action_title == "Persistent memory keeps agents reliable across sessions"


def test_backstop_repairs_weak_title_as_last_resort():
    p = ContentPlanner()  # no client -> deterministic backstop active
    deck = _content_deck("Memory rot")  # 2 words -> weak
    p._backstop_weak_titles(deck, _bundle())
    assert not p._gate_title_is_weak(deck.slides[1].action_title)


# --------------------------------------------------------------------------- #
# Step F: closing decision-ask grounded in recommendation; metric K/M display
# --------------------------------------------------------------------------- #
def test_ground_closing_ask_uses_recommendation_not_canned():
    from app.models.generation import GeneratedSlideSpec
    p = ContentPlanner()
    deck = DeckSpec(deck_title="D", audience="X", slides=[
        GeneratedSlideSpec(slide_number=1, slide_type="closing", action_title="Commit to the path forward",
                           archetype="closing_recommendation", narrative_role="closing",
                           exhibit_spec={"type": "recommendation",
                                         "decision_ask": "Approve the recommended pilot with named owners and a review date.",
                                         "next_steps": ["Step one here.", "Step two here."]}),
    ])
    p._ground_closing_ask(deck, _story_map(1).model_copy(update={"recommendation": "Approve the first governed harness pilot this quarter."}))
    assert deck.slides[0].exhibit_spec["decision_ask"] == "Approve the first governed harness pilot this quarter."


def test_metric_value_display_compacts_large_numbers():
    from app.services.pptx_native.primitives import _metric_value_display
    assert _metric_value_display("200000") == "200K"
    assert _metric_value_display("3500000") == "3.5M"
    assert _metric_value_display("95") == "95"
    assert _metric_value_display("30%") == "30%"


# --------------------------------------------------------------------------- #
# Step G: regression guard — no canned 'BS' strings on the LLM authoring path
# --------------------------------------------------------------------------- #
_CANNED_STRINGS = (
    "ground the next decision in",
    "anchor the recommendation in the source evidence",
    "approve the recommended pilot with named owners and a review date",
    "approve a time-boxed pilot with named owners",
    "evidence to inspect", "condition to validate", "implication to resolve",
    "make the key decision explicit", "use the source evidence to choose the next step",
)


def _assert_no_canned_strings(outlines):
    blob = " ".join(json.dumps(o.content_json, ensure_ascii=True).lower() for o in outlines)
    hits = [phrase for phrase in _CANNED_STRINGS if phrase in blob]
    assert not hits, f"canned strings leaked onto the LLM path: {hits}"


class _CleanFullLLM:
    """Fake planner client that authors clean, complete slides end-to-end, so the
    full plan() pipeline never needs canned fallback content."""

    model = "test-model"

    def complete_json(self, **kwargs):
        prompt = kwargs.get("user_prompt", "")
        low = prompt.lower()
        if "story map" in low:
            roles_claims = [
                ("cover", "Ground benchmark creation in validated organizational evidence"),
                ("problem", "Synthetic benchmarks create circular validation loops without grounding"),
                ("evidence", "Source-grounded harnesses evaluate models against real workflows"),
                ("framework", "Harness design turns existing workflows into evaluation evidence"),
                ("implementation", "Model contracts make evaluation expectations explicit and testable"),
                ("closing", "Adopt source-grounded harnesses to make benchmark quality observable"),
            ]
            return {
                "thesis": "Ground benchmark creation in validated evidence.",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "recommendation": "Adopt source-grounded harnesses for benchmark creation this quarter.",
                "beats": [
                    {"beat_number": i + 1, "role": r, "claim": c, "source_refs": [],
                     "preferred_exhibit": "callouts", "rationale": "Advance the argument."}
                    for i, (r, c) in enumerate(roles_claims)
                ],
            }
        if "one slide object" in low or "beats:" in low:
            match = re.search(r"Beats: (\[.*?\])\nAllowed", prompt, re.DOTALL)
            beats = json.loads(match.group(1)) if match else []
            return {"slides": [
                {
                    "slide_number": b["slide_number"], "slide_type": "content",
                    "action_title": b["claim"], "subheading": "Evidence drawn from validated workflows",
                    "archetype": "callouts", "narrative_role": b["role"],
                    "exhibit_spec": {"type": "callouts", "points": [
                        {"title": "Validated evidence", "body": "Source-grounded harnesses test models against real organizational workflows."},
                        {"title": "Reproducible cases", "body": "Benchmark cases derive from validated workflows rather than generated examples."},
                        {"title": "Operational proof", "body": "Contracts define exactly what each benchmark must prove before scaling."},
                    ]},
                    "sources": ["Uploaded source"], "source_refs": ["doc-1:Solution"],
                }
                for b in beats
            ]}
        # narrative + refine passes: clean no-ops (titles already strong).
        return {"titles": [], "slides": []}


def test_llm_path_deck_has_no_canned_strings():
    from app.models.brand import BrandDNA
    from app.models.template import TemplateProfile
    template = TemplateProfile(
        id="t", name="t", type="freeform", brand=BrandDNA(), slides=[],
        source_file="", created_at="2026-01-01T00:00:00Z", updated_at="2026-01-01T00:00:00Z",
    )
    planner = ContentPlanner(llm_client=_CleanFullLLM(), slide_generation_strategy="batched")
    outlines, _ = planner.plan(
        template, _bundle(),
        instructions="Create a deck about grounding benchmarks in evidence.",
        generation_mode="freeform", quality_profile="fast",
    )
    assert outlines
    _assert_no_canned_strings(outlines)
