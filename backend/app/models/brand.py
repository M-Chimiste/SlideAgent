from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BrandColors(BaseModel):
    # Freeform house palette, tuned to the reference whitepaper: a deep navy ink,
    # a slate secondary, a refined bronze/gold accent (not a loud orange), cool
    # light-blue card fills, and white. Bronze tints to a warm blush for emphasis
    # cards, matching the reference deck's accent rhythm.
    primary: str = Field(default="14213D")
    secondary: str = Field(default="44506A")
    accent: str = Field(default="C8893B")
    background_dark: str = Field(default="0D1426")
    background_light: str = Field(default="EAEEF5")
    text_dark: str = Field(default="14213D")
    text_light: str = Field(default="FFFFFF")


class BrandFonts(BaseModel):
    # Freeform default house style: a serif display heading paired with a clean
    # sans body (emulating the reference deck, which pairs Cambria with Calibri).
    # Brand mode overrides both via the template analyzer, so this only styles
    # freeform decks.
    heading: str = Field(default="Cambria")
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
    layout_profile: dict[str, Any] = Field(default_factory=dict)

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
