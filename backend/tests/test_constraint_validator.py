"""Tests for ConstraintValidator."""
import pytest

from app.models.templates import FieldType, SlideSchema, TemplateFieldSchema
from app.services.constraint_validator import ConstraintValidator


@pytest.fixture
def validator():
    return ConstraintValidator()


@pytest.fixture
def schema():
    return {
        "1": SlideSchema(
            slide_index=1,
            fields={
                "title": TemplateFieldSchema(shape_id=2, type=FieldType.text, max_chars=60),
                "date": TemplateFieldSchema(
                    shape_id=3, type=FieldType.date, date_format="%d %b %Y"
                ),
            },
        ),
        "2": SlideSchema(
            slide_index=2,
            fields={
                "project": TemplateFieldSchema(shape_id=2, type=FieldType.text, max_chars=80),
                "status": TemplateFieldSchema(
                    shape_id=4,
                    type=FieldType.enum,
                    allowed_values=["Green", "Amber", "Red"],
                ),
                "summary": TemplateFieldSchema(
                    shape_id=3, type=FieldType.text, max_chars=50
                ),
                "count": TemplateFieldSchema(shape_id=6, type=FieldType.number, required=False),
                "strict_field": TemplateFieldSchema(
                    shape_id=7, type=FieldType.text, max_chars=10, truncation_allowed=False, required=False,
                ),
            },
        ),
    }


def test_valid_input(validator, schema):
    fields = {
        "title": "Weekly Status",
        "date": "17 Feb 2026",
        "project": "Ariadne",
        "status": "Green",
        "summary": "On track.",
    }
    validated, warnings, errors = validator.validate(fields, schema)
    assert errors == []
    assert warnings == []
    assert validated["title"] == "Weekly Status"
    assert validated["status"] == "Green"


def test_missing_required_field(validator, schema):
    fields = {"title": "Test"}  # Missing date, project, status, summary
    validated, warnings, errors = validator.validate(fields, schema)
    assert len(errors) >= 3  # date, project, status, summary are required


def test_invalid_enum(validator, schema):
    fields = {
        "title": "Test",
        "date": "17 Feb 2026",
        "project": "X",
        "status": "Blue",  # Invalid
        "summary": "OK",
    }
    validated, warnings, errors = validator.validate(fields, schema)
    assert any("Blue" in e for e in errors)
    assert "status" not in validated


def test_date_validation_correct_format(validator, schema):
    fields = {
        "title": "T",
        "date": "17 Feb 2026",
        "project": "X",
        "status": "Green",
        "summary": "OK",
    }
    validated, _, _ = validator.validate(fields, schema)
    assert validated["date"] == "17 Feb 2026"


def test_date_validation_alternate_format(validator, schema):
    fields = {
        "title": "T",
        "date": "2026-02-17",  # ISO format, should be reformatted
        "project": "X",
        "status": "Green",
        "summary": "OK",
    }
    validated, _, _ = validator.validate(fields, schema)
    assert validated["date"] == "17 Feb 2026"


def test_date_validation_invalid(validator, schema):
    fields = {
        "title": "T",
        "date": "not a date",
        "project": "X",
        "status": "Green",
        "summary": "OK",
    }
    _, _, errors = validator.validate(fields, schema)
    assert any("date" in e.lower() for e in errors)


def test_text_truncation(validator, schema):
    long_summary = "A" * 100  # Exceeds max_chars=50
    fields = {
        "title": "T",
        "date": "17 Feb 2026",
        "project": "X",
        "status": "Green",
        "summary": long_summary,
    }
    validated, warnings, errors = validator.validate(fields, schema)
    assert errors == []
    assert len(validated["summary"]) <= 50
    assert any("truncated" in w.lower() for w in warnings)


def test_truncation_not_allowed(validator, schema):
    fields = {
        "title": "T",
        "date": "17 Feb 2026",
        "project": "X",
        "status": "Green",
        "summary": "OK",
        "strict_field": "This exceeds ten characters limit",
    }
    _, _, errors = validator.validate(fields, schema)
    assert any("strict_field" in e for e in errors)


def test_number_validation_valid(validator, schema):
    fields = {
        "title": "T",
        "date": "17 Feb 2026",
        "project": "X",
        "status": "Green",
        "summary": "OK",
        "count": "42",
    }
    validated, _, errors = validator.validate(fields, schema)
    assert "count" in validated
    assert validated["count"] == "42"


def test_number_validation_invalid(validator, schema):
    fields = {
        "title": "T",
        "date": "17 Feb 2026",
        "project": "X",
        "status": "Green",
        "summary": "OK",
        "count": "not-a-number",
    }
    _, _, errors = validator.validate(fields, schema)
    assert any("count" in e for e in errors)


def test_unknown_field_warning(validator, schema):
    fields = {
        "title": "T",
        "date": "17 Feb 2026",
        "project": "X",
        "status": "Green",
        "summary": "OK",
        "unknown_field": "value",
    }
    _, warnings, _ = validator.validate(fields, schema)
    assert any("unknown_field" in w for w in warnings)


def test_truncation_at_word_boundary(validator, schema):
    # 50 chars max for summary, text is longer than 50
    text = "This is a sentence that should be truncated at a word boundary nicely."
    fields = {
        "title": "T",
        "date": "17 Feb 2026",
        "project": "X",
        "status": "Green",
        "summary": text,
    }
    validated, _, _ = validator.validate(fields, schema)
    assert len(validated["summary"]) <= 50
    assert not validated["summary"].endswith(" ")  # No trailing space
