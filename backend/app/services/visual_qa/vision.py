# ruff: noqa: F401
import json
import posixpath
import re
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Optional

from lxml import etree
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from app.models.outline import SlideOutline
from app.models.qa import QAEnvelope, QAIssue, QAResult
from app.services.rendering import RenderingError, render_pptx_to_images, render_pptx_to_pdf
from app.services.visual_qa.constants import (
    CONTENT_TYPES_NS,
    EMU_PER_INCH,
    QA_SYSTEM_PROMPT,
    REL_NS,
    SAFE_XML_PARSER,
)


class VisionQAMixin:
    def _inspect_image(self, image_path: Path) -> str:
        if not self.bedrock:
            if not self.openai_client:
                return ""
            image_format = image_path.suffix.lower().lstrip(".") or "jpeg"
            if image_format == "jpg":
                image_format = "jpeg"
            return self.openai_client.complete_vision(
                system_prompt=QA_SYSTEM_PROMPT,
                user_prompt=(
                    "Inspect this slide for layout, overlap, text-wall, contrast, spacing, "
                    "cut-off or incomplete visible text, nonsensical copy, raw markdown/table "
                    "artifacts, and whether any diagram or exhibit actually explains the slide "
                    "claim. Return JSON only."
                ),
                image_bytes=self._vision_image_bytes(image_path, image_format),
                image_format=image_format,
                max_tokens=2400,
                temperature=0,
            )
        image_format = image_path.suffix.lower().lstrip(".") or "jpeg"
        if image_format == "jpg":
            image_format = "jpeg"
        return self.bedrock.converse_vision(
            model_id=self.model_id,
            system_prompt=QA_SYSTEM_PROMPT,
            user_prompt=(
                "Inspect this slide for layout, overlap, text-wall, contrast, cut-off "
                "or incomplete visible text, nonsensical copy, raw artifacts, and "
                "diagram/exhibit semantic fit."
            ),
            image_bytes=self._vision_image_bytes(image_path, image_format),
        )

    def _vision_image_bytes(
        self,
        image_path: Path,
        image_format: str,
        max_edge: int = 1280,
    ) -> bytes:
        try:
            with Image.open(image_path) as image:
                image = image.convert("RGB")
                if max(image.size) <= max_edge:
                    return image_path.read_bytes()
                image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
                buffer = BytesIO()
                output_format = "JPEG" if image_format.lower() in {"jpg", "jpeg"} else "PNG"
                image.save(buffer, format=output_format, quality=88)
                return buffer.getvalue()
        except Exception:
            return image_path.read_bytes()

    def _parse_report(self, report: str, slide_index: int) -> list[QAIssue]:
        if not report.strip():
            return []
        payload = self._extract_json(report)
        if payload is None:
            return [
                QAIssue(
                    severity="WARNING",
                    message="QA response could not be parsed.",
                    slide_index=slide_index,
                    category="qa_parse",
                )
            ]
        try:
            envelope = QAEnvelope.model_validate(payload)
        except Exception:
            return [
                QAIssue(
                    severity="WARNING",
                    message="QA response JSON did not match expected schema.",
                    slide_index=slide_index,
                    category="qa_schema",
                )
            ]
        parsed: list[QAIssue] = []
        for issue in envelope.issues:
            normalized_severity = issue.severity if issue.severity in {"CRITICAL", "WARNING", "INFO"} else "INFO"
            normalized_severity = self._normalize_vision_severity(
                normalized_severity,
                issue.message,
                issue.category,
            )
            parsed.append(
                QAIssue(
                    severity=normalized_severity,
                    message=issue.message or "Unspecified issue.",
                    slide_index=slide_index,
                    category=issue.category,
                )
            )
        return parsed

    def _normalize_vision_severity(
        self,
        severity: str,
        message: str,
        category: str | None,
    ) -> str:
        if severity != "CRITICAL":
            return severity
        text = " ".join(f"{category or ''} {message}".lower().split())
        positive_markers = (
            "no overlap",
            "no overlapping",
            "no cut-off",
            "no cutoff",
            "no clipped",
            "no clipping",
            "not overlapping",
            "layout is clean",
            "well-spaced",
            "well spaced",
            "no issues detected",
        )
        if any(marker in text for marker in positive_markers):
            return "INFO"
        if (
            ("footer" in text or "source" in text)
            and ("may be" in text or "risk" in text or "potential" in text)
            and not any(
                marker in text
                for marker in (
                    "is cut off",
                    "are cut off",
                    "cut off in",
                    "overlaps",
                    "overlapping",
                )
            )
        ):
            return "WARNING"
        return severity

    def _downgrade_fallback_vision_issues(
        self, issues: list[QAIssue]
    ) -> list[QAIssue]:
        downgraded: list[QAIssue] = []
        for issue in issues:
            message = f"Approximate preview finding: {issue.message}"
            if issue.severity == "CRITICAL":
                downgraded.append(
                    issue.model_copy(update={"severity": "WARNING", "message": message})
                )
            else:
                downgraded.append(issue.model_copy(update={"message": message}))
        return downgraded

    def _extract_json(self, report: str) -> Optional[dict]:
        try:
            return json.loads(report)
        except json.JSONDecodeError:
            pass
        fenced = re.search(r"```json\s*(\{.*?\})\s*```", report, flags=re.DOTALL)
        if fenced:
            try:
                return json.loads(fenced.group(1))
            except json.JSONDecodeError:
                return None
        first_brace = report.find("{")
        last_brace = report.rfind("}")
        if first_brace != -1 and last_brace > first_brace:
            candidate = report[first_brace : last_brace + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                return None
        return None
