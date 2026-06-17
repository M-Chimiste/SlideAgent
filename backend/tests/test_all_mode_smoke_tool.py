from pathlib import Path

from app.models.qa import QAIssue, QAResult
from app.services.design_agent import DesignAgent
from app.tools.all_mode_smoke import (
    _actionable_issue_signature,
    _model_slug,
    deck_report,
    serialize_qa_issues,
    summarize_qa,
)


def test_summarize_qa_counts_severities_and_categories() -> None:
    summary = summarize_qa(
        [
            QAIssue(severity="CRITICAL", message="Broken", category="office"),
            QAIssue(severity="WARNING", message="Needs source", category="source"),
            QAIssue(severity="INFO", message="Rendered", category="render"),
            QAIssue(severity="WARNING", message="Again", category="source"),
        ]
    )

    assert summary == {
        "count": 4,
        "critical": 1,
        "warning": 2,
        "info": 1,
        "categories": {"office": 1, "source": 2, "render": 1},
    }


def test_deck_report_shape_is_machine_readable(tmp_path: Path) -> None:
    output = tmp_path / "deck.pptx"
    preview = tmp_path / "slide-1.png"
    result = deck_report(
        mode="freeform",
        output_path=output,
        slide_count=1,
        titles=["Improve delivery discipline"],
        layouts=["two_column"],
        planning_warnings=[],
        build_warnings=[],
        qa_result=QAResult(
            issues=[
                QAIssue(
                    severity="WARNING",
                    message="Spacing is tight.",
                    category="spacing",
                    slide_index=0,
                )
            ],
            passed=True,
        ),
        preview_images=[preview],
    )

    assert result["mode"] == "freeform"
    assert result["output"] == output.as_posix()
    assert result["qa_passed"] is True
    assert result["qa_rounds"] == 0
    assert result["qa_history"] == [result["qa"]]
    assert result["qa_issues"] == [
        {
            "severity": "WARNING",
            "category": "spacing",
            "message": "Spacing is tight.",
            "slide_index": 0,
        }
    ]
    assert result["preview_images"] == [preview.as_posix()]


def test_serialize_qa_issues_preserves_issue_details() -> None:
    issue = QAIssue(
        severity="CRITICAL",
        category="overlap",
        message="Title overlaps subheading.",
        slide_index=2,
    )

    assert serialize_qa_issues([issue]) == [
        {
            "severity": "CRITICAL",
            "category": "overlap",
            "message": "Title overlaps subheading.",
            "slide_index": 2,
        }
    ]


def test_model_slug_is_filesystem_friendly() -> None:
    assert _model_slug("minimax-m2.7") == "minimax-m2-7"
    assert _model_slug("qwen3.6-35b-a3b-mtp") == "qwen3-6-35b-a3b-mtp"


def test_actionable_issue_signature_sorts_deck_and_slide_level_issues() -> None:
    result = QAResult(
        passed=False,
        issues=[
            QAIssue(
                severity="WARNING",
                category="layout",
                message="Deck-level layout variety issue.",
                slide_index=None,
            ),
            QAIssue(
                severity="CRITICAL",
                category="overlap",
                message="Slide-level overlap.",
                slide_index=1,
            ),
        ],
    )

    signature = _actionable_issue_signature(DesignAgent(), result)

    assert signature[0][0] == -1
    assert signature[1][0] == 1
