from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.models.dev_tools import ShapeInfo, ShapeMap
from app.models.jobs import (
    JobCreateRequest,
    JobError,
    JobOptions,
    JobRecord,
    JobStatus,
    JobStatusResponse,
)
from app.models.schemas import (
    CoercedField,
    CoercionInput,
    CoercionOutput,
    InjectionTarget,
    PipelineResult,
)
from app.models.templates import (
    ContentType,
    FieldType,
    LayoutDefinition,
    SlideSchema,
    TemplateFieldSchema,
    TemplateMode,
    TemplateRecord,
)

NOW = datetime.now(tz=timezone.utc)


# --- Template models ---


def test_template_field_schema_text():
    field = TemplateFieldSchema(shape_id=3, type=FieldType.text, max_chars=80)
    assert field.shape_id == 3
    assert field.required is True
    assert field.truncation_allowed is True


def test_template_field_schema_enum():
    field = TemplateFieldSchema(
        shape_id=7,
        type=FieldType.enum,
        allowed_values=["Green", "Amber", "Red"],
    )
    assert field.allowed_values == ["Green", "Amber", "Red"]


def test_template_field_schema_invalid_type():
    with pytest.raises(ValidationError):
        TemplateFieldSchema(shape_id=1, type="invalid")


def test_slide_schema():
    schema = SlideSchema(
        slide_index=2,
        description="Project status",
        fields={
            "project_name": TemplateFieldSchema(shape_id=3, type=FieldType.text, max_chars=80),
            "status": TemplateFieldSchema(
                shape_id=7, type=FieldType.enum, allowed_values=["Green", "Amber", "Red"]
            ),
        },
    )
    assert len(schema.fields) == 2
    assert schema.fields["project_name"].max_chars == 80


def test_layout_definition():
    layout = LayoutDefinition(
        layout_name="bullets",
        slide_layout_index=2,
        suitable_for=[ContentType.bullets],
        fields={"title": TemplateFieldSchema(shape_id=1, type=FieldType.text, max_chars=60)},
    )
    assert layout.suitable_for == [ContentType.bullets]


def test_template_record():
    record = TemplateRecord(
        template_id="test-template",
        version="1.0.0",
        display_name="Test Template",
        mode=TemplateMode.mode1,
        pptx_path="templates/test/template.pptx",
        slides={
            "1": SlideSchema(
                slide_index=1,
                fields={"title": TemplateFieldSchema(shape_id=2, type=FieldType.text)},
            )
        },
        created_at=NOW,
    )
    assert record.template_id == "test-template"
    assert record.is_active is True

    # Round-trip through JSON
    data = record.model_dump(mode="json")
    restored = TemplateRecord.model_validate(data)
    assert restored.template_id == record.template_id


def test_template_record_invalid_mode():
    with pytest.raises(ValidationError):
        TemplateRecord(
            template_id="t",
            version="1.0.0",
            display_name="T",
            mode="invalid_mode",
            pptx_path="p.pptx",
            created_at=NOW,
        )


# --- Job models ---


def test_job_status_enum():
    assert JobStatus.queued == "queued"
    assert JobStatus.awaiting_approval == "awaiting_approval"


def test_job_record():
    job = JobRecord(
        job_id="abc-123",
        template_id="test",
        template_version="1.0.0",
        mode="mode1",
        status=JobStatus.queued,
        input_payload={"project_name": "Test"},
        created_at=NOW,
        updated_at=NOW,
        ttl_expires_at=NOW + timedelta(hours=24),
    )
    assert job.progress == 0
    assert job.warnings == []
    assert job.error is None


def test_job_error():
    error = JobError(stage="parsing", message="Missing field", retryable=False)
    assert error.stage == "parsing"


def test_job_create_request():
    req = JobCreateRequest(
        template_id="test", mode="mode1", input_data={"name": "val"}
    )
    assert req.options is None


def test_job_status_response():
    resp = JobStatusResponse(
        job_id="abc",
        status=JobStatus.complete,
        progress=100,
        current_stage="complete",
        outline=None,
        warnings=[],
        error=None,
        output_url="https://example.com/output.pptx",
        created_at=NOW,
        updated_at=NOW,
    )
    data = resp.model_dump(mode="json")
    assert data["status"] == "complete"


# --- Schema models ---


def test_coercion_input_output():
    inp = CoercionInput(
        raw_fields={"proj_name": "Test"},
        schema_fields={"project_name": {"type": "text", "max_chars": 80}},
        mismatched_pairs=[("proj_name", "project_name")],
    )
    assert len(inp.mismatched_pairs) == 1

    out = CoercionOutput(
        coerced_fields=[
            CoercedField(
                schema_field_name="project_name",
                coerced_value="Test",
                confidence=0.95,
            )
        ],
        unresolvable_fields=[],
    )
    assert out.coerced_fields[0].confidence == 0.95


def test_injection_target():
    target = InjectionTarget(
        slide_index=2, shape_id=7, field_name="status", value="Green"
    )
    assert target.was_truncated is False


def test_pipeline_result():
    result = PipelineResult(
        success=True,
        output_path="outputs/abc/output.pptx",
        injection_targets=[],
        warnings=["truncated field X"],
    )
    assert result.error is None


# --- Dev tools models ---


def test_shape_info():
    info = ShapeInfo(
        shape_id=3,
        shape_name="Title 1",
        slide_index=1,
        shape_type="PLACEHOLDER",
        has_text=True,
        current_text="Slide Title",
        position={"x": 0.5, "y": 0.3, "w": 8.0, "h": 1.0},
    )
    assert info.has_text is True


def test_shape_map():
    smap = ShapeMap(
        template_path="test.pptx",
        slide_count=5,
        shapes=[
            ShapeInfo(
                shape_id=1,
                shape_name="Shape1",
                slide_index=1,
                shape_type="TEXT_BOX",
                has_text=True,
                position={"x": 0, "y": 0, "w": 1, "h": 1},
            )
        ],
    )
    assert smap.slide_count == 5
    assert len(smap.shapes) == 1
