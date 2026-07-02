from pathlib import Path
from typing import Optional

from app.clients.bedrock_client import BedrockClient
from app.clients.openai_compatible_client import OpenAICompatibleClient
from app.models.outline import SlideOutline
from app.models.qa import QAIssue, QAResult
from app.services.rendered_slide_audit import RenderedSlideAudit
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
        vision_max_slides: int = 8,
    ) -> None:
        self.bedrock = bedrock
        self.openai_client = openai_client
        self.model_id = model_id or "us.anthropic.claude-sonnet-4-20250514"
        self.vision_max_slides = max(0, vision_max_slides)

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
                QAIssue(severity="CRITICAL", message=str(exc), category="render_unavailable")
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
                    for idx in self._vision_image_indexes(images):
                        image = images[idx]
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
                    issues.extend(self._vision_sampling_issues(images))
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
            issues.extend(self._rendered_slide_audit_issues(pptx_path, output_dir, outlines))
            passed = not any(issue.severity == "CRITICAL" for issue in issues)
            return QAResult(issues=issues, passed=passed), images

        if self.bedrock or self.openai_client:
            for idx in self._vision_image_indexes(images):
                image = images[idx]
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
            issues.extend(self._vision_sampling_issues(images))
        issues.extend(self._pptx_structure_checks(pptx_path, outlines))
        issues.extend(self._rule_based_checks(outlines))
        issues.extend(self._rendered_slide_audit_issues(pptx_path, output_dir, outlines))
        passed = not any(issue.severity == "CRITICAL" for issue in issues)
        return QAResult(issues=issues, passed=passed), images

    def _vision_image_indexes(self, images: list[Path]) -> list[int]:
        if not images or self.vision_max_slides <= 0:
            return []
        if len(images) <= self.vision_max_slides:
            return list(range(len(images)))
        if self.vision_max_slides == 1:
            return [0]
        last = len(images) - 1
        indexes = {
            round(position * last / (self.vision_max_slides - 1))
            for position in range(self.vision_max_slides)
        }
        return sorted(indexes)

    def _vision_sampling_issues(self, images: list[Path]) -> list[QAIssue]:
        inspected_count = len(self._vision_image_indexes(images))
        if not images or inspected_count >= len(images):
            return []
        return [
            QAIssue(
                severity="INFO",
                message=(
                    f"Vision QA inspected {inspected_count} of {len(images)} "
                    "rendered slides; deterministic full-deck checks still ran."
                ),
                category="vision_sampling",
            )
        ]

    def _rendered_slide_audit_issues(
        self,
        pptx_path: Path,
        output_dir: Path,
        outlines: list[SlideOutline],
    ) -> list[QAIssue]:
        try:
            _, issues = RenderedSlideAudit().inspect(
                pptx_path,
                outlines,
                output_dir.parent / "qa",
            )
            return issues
        except Exception as exc:
            return [
                QAIssue(
                    severity="WARNING",
                    message=f"Rendered slide audit could not run: {exc}",
                    category="rendered_slide_audit",
                )
            ]
