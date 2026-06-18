from pathlib import Path
from typing import Optional

from app.clients.bedrock_client import BedrockClient
from app.clients.openai_compatible_client import OpenAICompatibleClient
from app.models.outline import SlideOutline
from app.models.qa import QAIssue, QAResult
from app.services.rendering import RenderingError, render_pptx_to_images
from app.services.visual_qa import constants as qa_constants
from app.services.visual_qa.checks import RuleAndPackageChecksMixin
from app.services.visual_qa.preview import PreviewFallbackMixin
from app.services.visual_qa.vision import VisionQAMixin


QA_SYSTEM_PROMPT = qa_constants.QA_SYSTEM_PROMPT


class VisualQAAgent(
    VisionQAMixin,
    RuleAndPackageChecksMixin,
    PreviewFallbackMixin,
):
    def __init__(
        self,
        bedrock: Optional[BedrockClient] = None,
        openai_client: Optional[OpenAICompatibleClient] = None,
        model_id: Optional[str] = None,
    ) -> None:
        self.bedrock = bedrock
        self.openai_client = openai_client
        self.model_id = model_id or "us.anthropic.claude-sonnet-4-20250514"

    def inspect_deck(
        self,
        pptx_path: Path,
        output_dir: Path,
        outlines: list[SlideOutline],
    ) -> tuple[QAResult, list[Path]]:
        issues: list[QAIssue] = []
        try:
            images = render_pptx_to_images(pptx_path, output_dir)
        except RenderingError as exc:
            issues.append(
                QAIssue(severity="WARNING", message=str(exc), category="render_unavailable")
            )
            images = self._render_pptx_preview_fallback(pptx_path, output_dir)
            if images:
                issues.append(
                    QAIssue(
                        severity="INFO",
                        message="Used approximate PPTX preview rendering for visual QA.",
                        category="render_fallback",
                    )
                )
                if self.bedrock or self.openai_client:
                    for idx, image in enumerate(images):
                        try:
                            report = self._inspect_image(image)
                        except Exception as exc:
                            issues.append(
                                QAIssue(
                                    severity="WARNING",
                                    message=f"Vision QA failed for approximate preview: {exc}",
                                    slide_index=idx,
                                    category="vision_unavailable",
                                )
                            )
                            continue
                        issues.extend(
                            self._downgrade_fallback_vision_issues(
                                self._parse_report(report, idx)
                            )
                        )
            else:
                issues.append(
                    QAIssue(
                        severity="WARNING",
                        message="No preview images could be generated for visual QA.",
                        category="preview_unavailable",
                    )
                )
            issues.extend(self._pptx_structure_checks(pptx_path, outlines))
            issues.extend(self._rule_based_checks(outlines))
            passed = not any(issue.severity == "CRITICAL" for issue in issues)
            return QAResult(issues=issues, passed=passed), images

        if self.bedrock or self.openai_client:
            for idx, image in enumerate(images):
                try:
                    report = self._inspect_image(image)
                except Exception as exc:
                    issues.append(
                        QAIssue(
                            severity="WARNING",
                            message=f"Vision QA failed for slide image: {exc}",
                            slide_index=idx,
                            category="vision_unavailable",
                        )
                    )
                    continue
                issues.extend(self._parse_report(report, idx))
        issues.extend(self._pptx_structure_checks(pptx_path, outlines))
        issues.extend(self._rule_based_checks(outlines))
        passed = not any(issue.severity == "CRITICAL" for issue in issues)
        return QAResult(issues=issues, passed=passed), images
