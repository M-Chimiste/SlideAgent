from app.models.document import DocumentBundle, DocumentMetadata, DocumentSection
from app.services.design_languages import LANGUAGES
from app.services.freeform_theme import derive_freeform_brand


def _bundle(title: str, content: str) -> DocumentBundle:
    return DocumentBundle(
        job_id="theme-job",
        sections=[
            DocumentSection(title=title, level=1, content=content, source_doc_id="doc-1")
        ],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title=title),
        content_inventory=[],
    )


def test_derive_freeform_brand_stamps_design_language_and_palette() -> None:
    bundle = _bundle(
        "Bootstrapping Benchmarks",
        "The harness defines model contracts, ground truth, and benchmark evaluation loops.",
    )

    brand = derive_freeform_brand(bundle, "Create an executive benchmark deck.")

    lang = brand.layout_profile["design_language"]
    assert lang in LANGUAGES
    # data/benchmark topics nudge toward the data-forward language.
    assert lang == "data_forward"
    palette = brand.layout_profile["palette"]
    assert set(palette) == {"primary", "secondary", "accent", "background_light", "background_dark"}
    # palette is generated, not the old hand-tuned constants
    assert brand.colors.background_dark
    assert all(len(v) == 6 for v in palette.values())


def test_derive_freeform_brand_distinct_topics_get_distinct_palettes() -> None:
    coding = derive_freeform_brand(
        _bundle("Agentic Coding Workflow", "Software agents, repository context, developer tools."),
        "Create an engineering operating deck.",
    )
    growth = derive_freeform_brand(
        _bundle("Revenue Growth", "Market expansion, customer pipeline, and sales motion."),
        "Create a growth strategy deck.",
    )

    assert coding.colors.primary != growth.colors.primary
    assert coding.layout_profile["design_language"] != growth.layout_profile["design_language"]


def test_derive_freeform_brand_explicit_design_language_overrides_topic() -> None:
    bundle = _bundle("Revenue Growth", "Market expansion and customer pipeline.")

    brand = derive_freeform_brand(
        bundle, "Create a growth deck.", design_language="bold_minimal"
    )

    assert brand.layout_profile["design_language"] == "bold_minimal"
    assert brand.layout_profile["palette_strategy"] == LANGUAGES["bold_minimal"].palette_strategy
