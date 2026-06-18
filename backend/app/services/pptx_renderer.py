from pathlib import Path

from pptx import Presentation
from pptx.util import Inches

from app.models.brand import BrandDNA
from app.models.outline import SlideOutline
from app.services.concept_diagram_renderer import ConceptDiagramRenderer
from app.services.pptx_rendering.assets import AssetRenderingMixin
from app.services.pptx_rendering.chrome import ChromeRenderingMixin
from app.services.pptx_rendering.constants import SLIDE_H, SLIDE_W
from app.services.pptx_rendering.core_layouts import CoreLayoutRenderingMixin
from app.services.pptx_rendering.drawing import DrawingMixin
from app.services.pptx_rendering.exhibit_layouts import ExhibitLayoutRenderingMixin
from app.services.pptx_rendering.immersive_layouts import ImmersiveLayoutRenderingMixin
from app.services.pptx_rendering.table_layouts import TableLayoutRenderingMixin


class DeterministicPptxRenderer(
    AssetRenderingMixin,
    ChromeRenderingMixin,
    CoreLayoutRenderingMixin,
    TableLayoutRenderingMixin,
    ImmersiveLayoutRenderingMixin,
    ExhibitLayoutRenderingMixin,
    DrawingMixin,
):
    def render(
        self,
        outlines: list[SlideOutline],
        brand: BrandDNA,
        output_path: Path,
        enable_diagrams: bool = True,
    ) -> list[dict[str, str | int]]:
        self._warnings: list[dict[str, str | int]] = []
        self._icon_cache_dir = output_path.parent / f"{output_path.stem}-icons"
        self._icon_cache_dir.mkdir(parents=True, exist_ok=True)
        self._diagram_cache_dir = (
            output_path.parent / f"{output_path.stem}-diagrams"
            if enable_diagrams
            else None
        )
        self._diagram_renderer = ConceptDiagramRenderer() if enable_diagrams else None
        prs = Presentation()
        prs.slide_width = Inches(SLIDE_W)
        prs.slide_height = Inches(SLIDE_H)
        blank_layout = prs.slide_layouts[6]
        for index, outline in enumerate(outlines):
            slide = prs.slides.add_slide(blank_layout)
            self._render_slide(slide, outline, brand, index + 1, len(outlines))
        prs.save(output_path.as_posix())
        return self._warnings

    def _render_slide(
        self,
        slide,
        outline: SlideOutline,
        brand: BrandDNA,
        slide_number: int,
        total_slides: int,
    ) -> None:
        title = outline.content_json.get("action_title") or outline.content_json.get("title") or outline.label
        subheading = outline.content_json.get("subheading") or outline.content_json.get("summary", "")
        layout = outline.layout_json.get("layout", "two_column")
        if layout == "cover":
            self._add_cover(slide, outline, brand)
            self._add_logo(slide, brand)
            return
        if layout == "section_divider":
            self._add_section_divider(slide, outline, brand, slide_number)
            self._add_logo(slide, brand)
            return
        if layout == "framework_cycle":
            self._add_framework_cycle_immersive(
                slide, outline, brand, slide_number, total_slides
            )
            self._add_logo(slide, brand)
            return
        if layout == "quote_sidebar":
            self._add_quote_sidebar_immersive(
                slide, outline, brand, slide_number, total_slides
            )
            self._add_logo(slide, brand)
            return
        if layout == "closing_recommendation":
            self._add_closing_recommendation_immersive(
                slide, outline, brand, slide_number, total_slides
            )
            self._add_logo(slide, brand)
            return
        self._add_header(slide, title, subheading, brand, outline, slide_number)
        self._add_logo(slide, brand)
        self._add_footer(slide, outline, brand, slide_number, total_slides)

        if layout == "executive_summary":
            self._add_executive_summary(slide, outline, brand)
        elif layout == "chart":
            self._add_metric_chart(slide, outline, brand)
        elif layout == "comparison_table":
            self._add_comparison_table(slide, outline, brand)
        elif layout == "callouts":
            self._add_callouts(slide, outline, brand)
        elif layout == "process":
            self._add_table_or_process(slide, outline, brand)
        elif layout == "quote_sidebar":
            self._add_quote_sidebar(slide, outline, brand)
        elif layout == "framework_cycle":
            self._add_framework_cycle(slide, outline, brand)
        elif layout == "dependency_map":
            self._add_dependency_map(slide, outline, brand)
        elif layout == "checklist":
            self._add_checklist(slide, outline, brand)
        elif layout == "code_panel":
            self._add_code_panel(slide, outline, brand)
        elif layout == "anti_patterns":
            self._add_anti_patterns(slide, outline, brand)
        elif layout == "table_reference":
            self._add_reference_table(slide, outline, brand)
        elif layout == "closing_recommendation":
            self._add_closing_recommendation(slide, outline, brand)
        elif layout == "icon_grid":
            self._add_grid(slide, outline, brand)
        elif layout == "icon_rows":
            self._add_icon_rows(slide, outline, brand)
        else:
            self._add_two_column(slide, outline, brand)
