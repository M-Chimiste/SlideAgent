from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BrandColors(BaseModel):
    primary: str = Field(default="1E2761")
    secondary: str = Field(default="4B5563")
    accent: str = Field(default="FF6B35")
    background_dark: str = Field(default="1E2761")
    background_light: str = Field(default="F5F7FA")
    text_dark: str = Field(default="1E2761")
    text_light: str = Field(default="FFFFFF")


class BrandFonts(BaseModel):
    heading: str = Field(default="Calibri")
    body: str = Field(default="Calibri")


class BrandLogo(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    path: str
    placement: str = "top-right"
    size_w: float = Field(default=1.2, alias="w")
    size_h: float = Field(default=0.4, alias="h")


class BrandDNA(BaseModel):
    colors: BrandColors = Field(default_factory=BrandColors)
    fonts: BrandFonts = Field(default_factory=BrandFonts)
    logo: Optional[BrandLogo] = None
    design_notes: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def accept_flat_brand_fields(cls, data):
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        colors = dict(normalized.get("colors") or {})
        color_aliases = {
            "primary_color": "primary",
            "secondary_color": "secondary",
            "accent_color": "accent",
            "background_dark_color": "background_dark",
            "background_light_color": "background_light",
            "text_dark_color": "text_dark",
            "text_light_color": "text_light",
        }
        for source, target in color_aliases.items():
            if normalized.get(source):
                colors[target] = normalized[source]
        if colors:
            normalized["colors"] = colors

        fonts = dict(normalized.get("fonts") or {})
        font_aliases = {
            "font_headings": "heading",
            "font_heading": "heading",
            "heading_font": "heading",
            "font_body": "body",
            "body_font": "body",
        }
        for source, target in font_aliases.items():
            if normalized.get(source):
                fonts[target] = normalized[source]
        if fonts:
            normalized["fonts"] = fonts
        return normalized
