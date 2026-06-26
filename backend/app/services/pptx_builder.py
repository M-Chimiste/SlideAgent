import json
from pathlib import Path
from typing import Iterable

from app.models.outline import SlideOutline
from app.models.template import TemplateProfile
from app.services.authored_pptx_renderer import AuthoredPptxRenderer
from app.services.brand_layout_renderer import BrandLayoutInstantiationRenderer
from app.services.brand_template_renderer import BrandTemplateCloneRenderer
from app.services.generation_editing_contract import GenerationEditingContract
from app.services.html_rendering import HtmlRenderError, HtmlSlideRenderer
from app.services.hybrid_assembler import HybridAssembler, SlideReplacement
from app.services.pptx_renderer import DeterministicPptxRenderer
from app.services.strict_injector import StrictSlideInjector
from app.workers.node_runner import NodePptxGenRunner


class PptxBuilder:
    def __init__(
        self,
        node_runner: NodePptxGenRunner,
        renderer_engine: str = "authored",
        brand_layout_instantiation: bool = False,
    ) -> None:
        self.node_runner = node_runner
        self.hybrid_assembler = HybridAssembler()
        self.strict_injector = StrictSlideInjector()
        self.legacy_renderer = DeterministicPptxRenderer()
        self.authored_renderer = AuthoredPptxRenderer(self.legacy_renderer)
        self.html_renderer = HtmlSlideRenderer()
        self.brand_template_renderer = BrandTemplateCloneRenderer()
        self.brand_layout_renderer = BrandLayoutInstantiationRenderer()
        self.editing_contract = GenerationEditingContract()
        self.renderer_engine = renderer_engine.strip().lower() or "authored"
        self.brand_layout_instantiation = brand_layout_instantiation

    def build_deck(
        self,
        template: TemplateProfile,
        outlines: list[SlideOutline],
        output_path: Path,
        working_dir: Path,
    ) -> list[dict[str, str | int]]:
        if template.type in {"freeform", "brand"}:
            prepared = self.prepare_outlines(template, outlines)
            if template.type == "brand" and self.renderer_engine != "legacy":
                pre_warnings: list[dict[str, str | int]] = []
                if self.brand_layout_instantiation:
                    instantiated, instantiate_warnings = self.brand_layout_renderer.render(
                        template,
                        prepared,
                        output_path,
                        working_dir,
                    )
                    if instantiated:
                        return instantiate_warnings
                    pre_warnings = instantiate_warnings
                rendered, clone_warnings = self.brand_template_renderer.render(
                    template,
                    prepared,
                    output_path,
                    working_dir,
                )
                if rendered:
                    return [*pre_warnings, *clone_warnings]
                fallback_outlines = self._strip_template_frames(prepared)
                render_warnings = self._render_generated(
                    fallback_outlines,
                    template.brand,
                    output_path,
                )
                return [*pre_warnings, *clone_warnings, *render_warnings]
            return self._render_generated(
                prepared,
                template.brand,
                output_path,
            )

        strict_output = working_dir / "strict.pptx"
        flex_output = working_dir / "flexible.pptx"
        strict_warnings = self.strict_injector.inject(
            Path(template.source_file), template, outlines, strict_output
        )

        flexible_outlines = [outline for outline in outlines if outline.mode == "flexible"]
        if not flexible_outlines:
            output_path.write_bytes(strict_output.read_bytes())
            return strict_warnings

        render_warnings = self.legacy_renderer.render(
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

    def _renderer(self):
        if self.renderer_engine == "legacy":
            return self.legacy_renderer
        if self.renderer_engine == "html":
            return self.html_renderer
        return self.authored_renderer

    def _render_generated(
        self,
        outlines: list[SlideOutline],
        brand,
        output_path: Path,
    ) -> list[dict[str, str | int]]:
        """Render generated freeform/brand decks, falling back from the HTML
        engine to the authored renderer if the headless-Chrome toolchain is
        unavailable, so the pipeline never hard-fails on a missing dependency.
        """
        if self.renderer_engine == "html":
            try:
                return self.html_renderer.render(outlines, brand, output_path)
            except HtmlRenderError as exc:
                fallback = self.authored_renderer.render(outlines, brand, output_path)
                return [
                    {
                        "slide_index": -1,
                        "field": "render_engine",
                        "severity": "warning",
                        "message": f"html renderer unavailable, used authored fallback: {exc}",
                    },
                    *fallback,
                ]
        return self._renderer().render(outlines, brand, output_path)

    def prepare_outlines(
        self,
        template: TemplateProfile,
        outlines: list[SlideOutline],
    ) -> list[SlideOutline]:
        if template.type not in {"freeform", "brand"}:
            return outlines
        prepared = (
            outlines
            if self.renderer_engine == "legacy"
            else self.authored_renderer.author_outlines(outlines)
        )
        if template.type != "brand":
            return prepared
        return self._attach_template_frames(template, prepared)

    def _attach_template_frames(
        self,
        template: TemplateProfile,
        outlines: list[SlideOutline],
    ) -> list[SlideOutline]:
        if not template.slides or not template.source_file:
            return outlines
        framed: list[SlideOutline] = []
        used_counts: dict[int, int] = {}
        for outline in outlines:
            if outline.mode != "flexible":
                framed.append(outline)
                continue
            frame = self.editing_contract.template_slide_for(
                outline, template, outlines, used_counts
            )
            if not frame:
                framed.append(outline)
                continue
            try:
                index = int(frame.get("index"))
                used_counts[index] = used_counts.get(index, 0) + 1
            except (TypeError, ValueError):
                pass
            slot_plan = self.editing_contract.slot_plan_for(outline, frame, template)
            revised = outline.model_copy(deep=True)
            frame_payload = {
                **frame,
                "source_file": template.source_file,
                "reuse_mode": "duplicate-slide-edit",
                "slot_plan": slot_plan,
            }
            revised.layout_json["template_frame"] = frame_payload
            revised.content_json["template_frame"] = {
                key: value
                for key, value in frame_payload.items()
                if key != "source_file"
            }
            framed.append(revised)
        return framed

    def _strip_template_frames(self, outlines: list[SlideOutline]) -> list[SlideOutline]:
        stripped: list[SlideOutline] = []
        for outline in outlines:
            if "template_frame" not in outline.layout_json and "template_frame" not in outline.content_json:
                stripped.append(outline)
                continue
            revised = outline.model_copy(deep=True)
            revised.layout_json.pop("template_frame", None)
            revised.content_json.pop("template_frame", None)
            stripped.append(revised)
        return stripped

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
