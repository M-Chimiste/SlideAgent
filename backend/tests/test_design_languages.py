from app.services.design_languages import (
    DEFAULT_LANGUAGE,
    LANGUAGES,
    get_language,
    resolve_design_language,
)


def test_editorial_serif_is_default_and_mirrors_current_literals() -> None:
    assert DEFAULT_LANGUAGE == "editorial_serif"
    editorial = LANGUAGES["editorial_serif"]
    assert editorial.heading_scale == 1.0
    assert editorial.card_radius == 16
    assert editorial.slide_padding == "70px 84px 60px"
    assert editorial.dark_angle == 155
    assert editorial.light_angle == 165
    assert editorial.motif == "rings"
    assert editorial.motif_slots == ("cover", "closing")


def test_get_language_falls_back_to_default() -> None:
    assert get_language("nonsense").key == DEFAULT_LANGUAGE
    assert get_language(None).key == DEFAULT_LANGUAGE
    assert get_language("bold_minimal").key == "bold_minimal"


def test_resolve_precedence_explicit_then_style_then_topic() -> None:
    # explicit wins
    assert resolve_design_language("warm_magazine", "data_forward", "benchmarks and metrics") == "warm_magazine"
    # style default when no explicit
    assert resolve_design_language("auto", "data_forward", "generic deck") == "data_forward"
    # topic nudge when neither
    assert resolve_design_language("auto", None, "an engineering api platform deep dive") == "technical_mono"


def test_motif_slots_are_known_slots() -> None:
    known = {"cover", "closing", "section", "statement"}
    for lang in LANGUAGES.values():
        assert set(lang.motif_slots) <= known
        assert lang.palette_strategy
