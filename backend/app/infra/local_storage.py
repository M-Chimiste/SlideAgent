from pathlib import Path
from typing import Iterable

from app.config import Settings
from app.models.document import DocumentBundle


class LocalStorage:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.ensure_dirs()

    def template_dir(self, template_id: str) -> Path:
        return self.settings.templates_dir / template_id

    def job_dir(self, job_id: str) -> Path:
        return self.settings.jobs_dir / job_id

    def ensure_job_dirs(self, job_id: str) -> None:
        base = self.job_dir(job_id)
        (base / "documents").mkdir(parents=True, exist_ok=True)
        (base / "markdown").mkdir(parents=True, exist_ok=True)
        (base / "planning").mkdir(parents=True, exist_ok=True)
        (base / "outline").mkdir(parents=True, exist_ok=True)
        (base / "slides").mkdir(parents=True, exist_ok=True)
        (base / "preview").mkdir(parents=True, exist_ok=True)
        (base / "qa").mkdir(parents=True, exist_ok=True)

    def save_template_source(self, template_id: str, filename: str, content: bytes) -> Path:
        template_dir = self.template_dir(template_id)
        template_dir.mkdir(parents=True, exist_ok=True)
        target = template_dir / "source.pptx"
        target.write_bytes(content)
        return target

    def save_template_profile(self, template_id: str, profile_json: str) -> Path:
        template_dir = self.template_dir(template_id)
        template_dir.mkdir(parents=True, exist_ok=True)
        target = template_dir / "profile.json"
        target.write_text(profile_json, encoding="utf-8")
        return target

    def save_job_document(self, job_id: str, filename: str, content: bytes) -> Path:
        self.ensure_job_dirs(job_id)
        target = self.job_dir(job_id) / "documents" / filename
        target.write_bytes(content)
        return target

    def save_markdown(self, job_id: str, doc_id: str, markdown: str) -> Path:
        self.ensure_job_dirs(job_id)
        target = self.job_dir(job_id) / "markdown" / f"{doc_id}.md"
        target.write_text(markdown, encoding="utf-8")
        return target

    def save_outline(self, job_id: str, outline_json: str) -> Path:
        self.ensure_job_dirs(job_id)
        target = self.job_dir(job_id) / "outline" / "outline.json"
        target.write_text(outline_json, encoding="utf-8")
        return target

    def save_planning_artifacts(
        self,
        job_id: str,
        artifacts: dict[str, object],
    ) -> None:
        self.ensure_job_dirs(job_id)
        planning_dir = self.job_dir(job_id) / "planning"
        import json

        for name, payload in artifacts.items():
            if name not in {"source-compression", "story-map", "spec-gate"}:
                continue
            target = planning_dir / f"{name}.json"
            target.write_text(
                json.dumps(payload, indent=2, ensure_ascii=True),
                encoding="utf-8",
            )

    def planning_artifact_path(self, job_id: str, artifact: str) -> Path:
        return self.job_dir(job_id) / "planning" / f"{artifact}.json"

    def save_document_bundle(self, job_id: str, bundle: DocumentBundle) -> Path:
        self.ensure_job_dirs(job_id)
        target = self.job_dir(job_id) / "planning" / "document-bundle.json"
        target.write_text(bundle.model_dump_json(indent=2), encoding="utf-8")
        return target

    def load_document_bundle(self, job_id: str) -> DocumentBundle | None:
        path = self.job_dir(job_id) / "planning" / "document-bundle.json"
        if not path.exists():
            return None
        try:
            return DocumentBundle.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def save_slide_script(self, job_id: str, slide_id: str, script: str) -> Path:
        self.ensure_job_dirs(job_id)
        target = self.job_dir(job_id) / "slides" / f"{slide_id}.js"
        target.write_text(script, encoding="utf-8")
        return target

    def save_preview_images(self, job_id: str, image_paths: Iterable[Path]) -> None:
        self.ensure_job_dirs(job_id)
        preview_dir = self.job_dir(job_id) / "preview"
        for image_path in image_paths:
            target = preview_dir / image_path.name
            if image_path != target:
                target.write_bytes(image_path.read_bytes())

    def save_qa_log(self, job_id: str, round_number: int, qa_json: str) -> Path:
        self.ensure_job_dirs(job_id)
        target = self.job_dir(job_id) / "qa" / f"round-{round_number}.json"
        target.write_text(qa_json, encoding="utf-8")
        return target

    def output_pptx_path(self, job_id: str) -> Path:
        self.ensure_job_dirs(job_id)
        return self.job_dir(job_id) / "output.pptx"

    def preview_dir(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "preview"
