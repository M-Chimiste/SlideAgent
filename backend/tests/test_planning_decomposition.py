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
