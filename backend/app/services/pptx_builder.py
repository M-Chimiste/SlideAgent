import json
from pathlib import Path
from typing import Iterable

from app.models.outline import SlideOutline
from app.models.template import TemplateProfile
from app.services.hybrid_assembler import HybridAssembler, SlideReplacement
from app.services.pptx_renderer import DeterministicPptxRenderer
from app.services.strict_injector import StrictSlideInjector
from app.workers.node_runner import NodePptxGenRunner


class PptxBuilder:
    def __init__(self, node_runner: NodePptxGenRunner) -> None:
        self.node_runner = node_runner
        self.hybrid_assembler = HybridAssembler()
        self.strict_injector = StrictSlideInjector()
        self.renderer = DeterministicPptxRenderer()

    def build_deck(
        self,
        template: TemplateProfile,
        outlines: list[SlideOutline],
        output_path: Path,
        working_dir: Path,
    ) -> list[dict[str, str | int]]:
        if template.type in {"freeform", "brand"}:
            return self.renderer.render(outlines, template.brand, output_path)

        strict_output = working_dir / "strict.pptx"
        flex_output = working_dir / "flexible.pptx"
        strict_warnings = self.strict_injector.inject(
            Path(template.source_file), template, outlines, strict_output
        )

        flexible_outlines = [outline for outline in outlines if outline.mode == "flexible"]
        if not flexible_outlines:
            output_path.write_bytes(strict_output.read_bytes())
            return strict_warnings

        render_warnings = self.renderer.render(
            flexible_outlines, template.brand, flex_output, enable_diagrams=False
        )

        replacements = []
        flex_number = 1
        for slide_spec in template.slides:
            if slide_spec.mode == "flexible":
                replacements.append(
                    SlideReplacement(
                        template_slide_number=slide_spec.index + 1,
                        flexible_slide_number=flex_number,
                    )
                )
                flex_number += 1

        self.hybrid_assembler.assemble(
            strict_output, flex_output, replacements, output_path
        )
        return [*strict_warnings, *render_warnings]

    def _write_deck_json(
        self,
        template: TemplateProfile,
        outlines: Iterable[SlideOutline],
        working_dir: Path,
    ) -> Path:
        slides = []
        for outline in outlines:
            slides.append(
                {
                    "title": outline.content_json.get("title", outline.label),
                    "summary": outline.content_json.get("summary", ""),
                    "bullets": outline.content_json.get("bullets", []),
                    "metrics": outline.content_json.get("metrics", []),
                    "layout": outline.layout_json.get("layout", "icon_rows"),
                    "icons": outline.layout_json.get("icons", []),
                }
            )
        payload = {
            "brand": template.brand.model_dump(),
            "slides": slides,
        }
        deck_json_path = working_dir / "deck.json"
        deck_json_path.write_text(json.dumps(payload), encoding="utf-8")
        return deck_json_path
