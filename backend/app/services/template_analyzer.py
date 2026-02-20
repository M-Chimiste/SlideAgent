import re
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from lxml import etree
from pptx import Presentation

from app.clients.bedrock_client import BedrockClient
from app.models.brand import BrandDNA, BrandFonts
from app.models.template import SlideField, SlideSchema, SlideSpec, TemplateProfile
from app.services.rendering import render_pptx_to_images


class TemplateAnalyzer:
    def __init__(self, bedrock: Optional[BedrockClient] = None) -> None:
        self.bedrock = bedrock

    def analyze(
        self,
        template_path: Path,
        template_name: str,
        template_type: str,
        template_id: Optional[str] = None,
    ) -> tuple[TemplateProfile, list[Path]]:
        brand = self._extract_brand(template_path)
        slides = self._extract_slides(template_path, template_type)
        profile = TemplateProfile(
            id=template_id or self._new_id(),
            name=template_name,
            type=template_type,
            brand=brand,
            slides=slides,
            source_file=template_path.as_posix(),
            created_at=self._timestamp(),
            updated_at=self._timestamp(),
        )
        thumbnails = []
        try:
            thumbnails = render_pptx_to_images(
                template_path, template_path.parent / "thumbnails"
            )
        except Exception:
            thumbnails = []
        return profile, thumbnails

    def _extract_brand(self, template_path: Path) -> BrandDNA:
        with zipfile.ZipFile(template_path, "r") as zip_ref:
            theme_path = "ppt/theme/theme1.xml"
            if theme_path not in zip_ref.namelist():
                return BrandDNA()
            xml = zip_ref.read(theme_path)
        tree = etree.fromstring(xml)
        ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
        clr_scheme = tree.find(".//a:clrScheme", namespaces=ns)
        colors = {}
        if clr_scheme is not None:
            for child in clr_scheme:
                tag = etree.QName(child).localname
                color_node = child.find(".//a:srgbClr", namespaces=ns)
                if color_node is None:
                    color_node = child.find(".//a:sysClr", namespaces=ns)
                if color_node is not None:
                    colors[tag] = color_node.get("val") or color_node.get("lastClr")
        font_scheme = tree.find(".//a:fontScheme", namespaces=ns)
        fonts = BrandFonts()
        if font_scheme is not None:
            major = font_scheme.find(".//a:majorFont", namespaces=ns)
            minor = font_scheme.find(".//a:minorFont", namespaces=ns)
            if major is not None:
                major_latn = major.find(".//a:latin", namespaces=ns)
                if major_latn is not None and major_latn.get("typeface"):
                    fonts.heading = major_latn.get("typeface")
            if minor is not None:
                minor_latn = minor.find(".//a:latin", namespaces=ns)
                if minor_latn is not None and minor_latn.get("typeface"):
                    fonts.body = minor_latn.get("typeface")
        brand = BrandDNA(fonts=fonts)
        if colors:
            brand.colors.primary = colors.get("accent1", brand.colors.primary)
            brand.colors.secondary = colors.get("accent2", brand.colors.secondary)
            brand.colors.accent = colors.get("accent3", brand.colors.accent)
            brand.colors.text_dark = colors.get("dk1", brand.colors.text_dark)
            brand.colors.text_light = colors.get("lt1", brand.colors.text_light)
            brand.colors.background_dark = colors.get(
                "dk2", brand.colors.background_dark
            )
            brand.colors.background_light = colors.get(
                "lt2", brand.colors.background_light
            )
        return brand

    def _extract_slides(self, template_path: Path, template_type: str) -> list[SlideSpec]:
        presentation = Presentation(template_path.as_posix())
        slides = []
        for index, slide in enumerate(presentation.slides):
            title = self._slide_title(slide)
            label = title or f"Slide {index + 1}"
            mode = "flexible"
            reason = None
            schema = None
            intent = None
            if template_type == "strict":
                mode, reason = self._classify_slide(slide, label)
                if mode == "strict":
                    schema = self._extract_schema(slide)
                else:
                    intent = label
            slides.append(
                SlideSpec(
                    index=index,
                    mode=mode,
                    label=label,
                    layout_name=slide.slide_layout.name,
                    schema=schema,
                    intent=intent,
                    classification_reason=reason,
                )
            )
        return slides

    def _slide_title(self, slide) -> str:
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            text = shape.text.strip()
            if text:
                return text.splitlines()[0][:80]
        return ""

    def _classify_slide(self, slide, label: str) -> tuple[str, str]:
        text = " ".join(
            shape.text.strip()
            for shape in slide.shapes
            if shape.has_text_frame and shape.text
        ).lower()
        if any(keyword in text for keyword in ["status", "dashboard", "kpi", "score"]):
            return "strict", "Detected structured dashboard keywords."
        try:
            if any(getattr(shape, "has_chart", False) for shape in slide.shapes):
                return "strict", "Detected chart element."
        except Exception:
            pass
        if "title" in label.lower() and len(text.split()) < 8:
            return "strict", "Likely title slide."
        return "flexible", "Defaulted to flexible layout."

    def _extract_schema(self, slide) -> SlideSchema:
        fields = []
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            name = shape.name or f"Shape{len(fields) + 1}"
            shape_text = shape.text.strip()
            field_id = self._sanitize_id(name)
            field_type = self._infer_field_type(shape_text)
            constraints = self._infer_constraints(field_id, field_type, shape_text)
            is_placeholder = bool(getattr(shape, "is_placeholder", False))
            fields.append(
                SlideField(
                    id=field_id,
                    type=field_type,
                    location=f"shape:{name}",
                    required=is_placeholder or bool(shape_text),
                    max_chars=constraints.get("max_chars", 160),
                    values=constraints.get("values"),
                    render=constraints.get("render"),
                    color_map=constraints.get("color_map"),
                    max_items=constraints.get("max_items"),
                    max_chars_per_item=constraints.get("max_chars_per_item"),
                )
            )
        return SlideSchema(fields=fields)

    def _infer_field_type(self, text: str) -> str:
        lowered = text.lower()
        if any(token in lowered for token in ["rag", "status", "traffic light"]):
            return "enum"
        if any(token in lowered for token in ["risks", "actions", "items"]) and "\n" in text:
            return "text_list"
        if re.search(r"\d+%", lowered):
            return "number"
        if any(token in lowered for token in ["date", "month", "year"]):
            return "date"
        return "text"

    def _infer_constraints(
        self, field_id: str, field_type: str, shape_text: str
    ) -> dict[str, object]:
        lowered = f"{field_id} {shape_text}".lower()
        constraints: dict[str, object] = {}
        if field_type == "enum" or "rag" in lowered or "status" in lowered:
            constraints["values"] = ["green", "amber", "red"]
            constraints["render"] = "fill_color"
            constraints["color_map"] = {
                "green": "00B050",
                "amber": "FFC000",
                "red": "FF0000",
            }
        if field_type == "text_list":
            constraints["max_items"] = 4
            constraints["max_chars_per_item"] = 80
        if "title" in lowered:
            constraints["max_chars"] = 80
        elif "summary" in lowered or "description" in lowered:
            constraints["max_chars"] = 220
        return constraints

    def _sanitize_id(self, name: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip().lower())
        return cleaned.strip("_") or "field"

    def _timestamp(self) -> str:
        return datetime.utcnow().isoformat() + "Z"

    def _new_id(self) -> str:
        return str(uuid.uuid4())
