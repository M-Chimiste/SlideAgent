"""Tests for InputParser (exact match mode only, no Bedrock)."""
import pytest

from app.models.templates import FieldType, SlideSchema, TemplateFieldSchema
from app.services.input_parser import InputParser


@pytest.fixture
def parser():
    return InputParser(bedrock=None)  # No Bedrock, strict mode


@pytest.fixture
def schema():
    return {
        "1": SlideSchema(
            slide_index=1,
            fields={
                "title": TemplateFieldSchema(shape_id=2, type=FieldType.text),
                "date": TemplateFieldSchema(shape_id=3, type=FieldType.date),
            },
        ),
        "2": SlideSchema(
            slide_index=2,
            fields={
                "project": TemplateFieldSchema(shape_id=2, type=FieldType.text),
                "status": TemplateFieldSchema(
                    shape_id=4, type=FieldType.enum, allowed_values=["Green", "Red"]
                ),
            },
        ),
    }


@pytest.mark.asyncio
async def test_exact_match_all_fields(parser, schema):
    input_data = {
        "title": "Weekly Status",
        "date": "17 Feb 2026",
        "project": "Ariadne",
        "status": "Green",
    }
    result = await parser.parse(input_data, schema)
    assert result == input_data


@pytest.mark.asyncio
async def test_exact_match_subset(parser, schema):
    input_data = {"title": "Only Title"}
    result = await parser.parse(input_data, schema)
    assert result == {"title": "Only Title"}


@pytest.mark.asyncio
async def test_unmatched_fields_ignored_without_bedrock(parser, schema):
    input_data = {
        "title": "T",
        "proj_name": "Ariadne",  # Doesn't match any schema field
    }
    result = await parser.parse(input_data, schema)
    assert result == {"title": "T"}
    # proj_name should be silently ignored


@pytest.mark.asyncio
async def test_non_string_values_converted(parser, schema):
    input_data = {"title": 42, "status": True}
    result = await parser.parse(input_data, schema)
    assert result["title"] == "42"
    assert result["status"] == "True"
