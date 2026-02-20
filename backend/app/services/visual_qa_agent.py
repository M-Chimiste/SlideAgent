import json
import re
from pathlib import Path
from typing import Optional

from app.clients.bedrock_client import BedrockClient
from app.models.outline import SlideOutline
from app.models.qa import QAEnvelope, QAIssue, QAResult
from app.services.rendering import RenderingError, render_pptx_to_images, render_pptx_to_pdf


QA_SYSTEM_PROMPT = """You are a visual QA inspector for PowerPoint slides.
Return a JSON object with an array of issues, each with severity (CRITICAL, WARNING, INFO) and message.
Flag text walls, overlaps, cut-off text, low contrast, missing visuals, and repeated layouts.
Return strict JSON only:
{
  "issues": [{"severity":"CRITICAL|WARNING|INFO","message":"...", "category":"...", "slide_index":0}]
}"""


class VisualQAAgent:
    def __init__(
        self, bedrock: Optional[BedrockClient] = None, model_id: Optional[str] = None
    ) -> None:
        self.bedrock = bedrock
        self.model_id = model_id or "us.anthropic.claude-sonnet-4-20250514"

    def inspect_deck(
        self,
        pptx_path: Path,
        output_dir: Path,
        outlines: list[SlideOutline],
    ) -> tuple[QAResult, list[Path]]:
        try:
            images = render_pptx_to_images(pptx_path, output_dir)
        except RenderingError as exc:
            issues = [QAIssue(severity="WARNING", message=str(exc))]
            return QAResult(issues=issues, passed=False), []

        issues: list[QAIssue] = []
        if self.bedrock:
            for idx, image in enumerate(images):
                report = self._inspect_image(image)
                issues.extend(self._parse_report(report, idx))
        issues.extend(self._rule_based_checks(outlines))
        passed = not any(issue.severity == "CRITICAL" for issue in issues)
        return QAResult(issues=issues, passed=passed), images

    def _inspect_image(self, image_path: Path) -> str:
        if not self.bedrock:
            return ""
        image_bytes = image_path.read_bytes()
        return self.bedrock.converse_vision(
            model_id=self.model_id,
            system_prompt=QA_SYSTEM_PROMPT,
            user_prompt="Inspect this slide for layout, overlap, or text-wall issues.",
            image_bytes=image_bytes,
        )

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
            parsed.append(
                QAIssue(
                    severity=normalized_severity,
                    message=issue.message or "Unspecified issue.",
                    slide_index=issue.slide_index if issue.slide_index is not None else slide_index,
                    category=issue.category,
                )
            )
        return parsed

    def _rule_based_checks(self, outlines: list[SlideOutline]) -> list[QAIssue]:
        issues = []
        for outline in outlines:
            if outline.mode != "flexible":
                continue
            visuals = outline.layout_json.get("visual_elements", [])
            if not visuals:
                issues.append(
                    QAIssue(
                        severity="CRITICAL",
                        message="Text wall detected: no visual elements.",
                        slide_index=outline.slide_index,
                        category="text_wall",
                    )
                )
        return issues

    def export_pdf(self, pptx_path: Path, output_dir: Path) -> Optional[Path]:
        try:
            return render_pptx_to_pdf(pptx_path, output_dir)
        except RenderingError:
            return None

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
