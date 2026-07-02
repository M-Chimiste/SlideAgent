from app.models.template import SlideField
from app.services.strict_validator import StrictSchemaValidator


def test_enum_normalization_and_fallback() -> None:
    validator = StrictSchemaValidator()
    field = SlideField(
        id="overall_rag",
        type="enum",
        location="shape:RAG",
        values=["green", "amber", "red"],
        required=True,
    )

    normalized, warnings = validator.validate_field_value(field, "Green")
    assert normalized == "green"
    assert warnings == []

    normalized, warnings = validator.validate_field_value(field, "invalid")
    assert normalized == "[INSERT CONTENT HERE]"
    assert warnings


def test_text_list_bounds() -> None:
    validator = StrictSchemaValidator()
    field = SlideField(
        id="key_risks",
        type="text_list",
        location="shape:Risks",
        max_items=2,
        max_chars_per_item=5,
    )
    normalized, warnings = validator.validate_field_value(
        field, ["first item", "second", "third"]
    )
    assert normalized == ["first", "secon"]
    assert len(warnings) >= 1
