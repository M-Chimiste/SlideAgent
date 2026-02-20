from typing import Optional

from pydantic import BaseModel, Field


class BrandColors(BaseModel):
    primary: str = Field(default="1E2761")
    secondary: str = Field(default="CADCFC")
    accent: str = Field(default="FF6B35")
    background_dark: str = Field(default="1E2761")
    background_light: str = Field(default="F5F7FA")
    text_dark: str = Field(default="1E2761")
    text_light: str = Field(default="FFFFFF")


class BrandFonts(BaseModel):
    heading: str = Field(default="Calibri")
    body: str = Field(default="Calibri")


class BrandLogo(BaseModel):
    path: str
    placement: str = "top-right"
    size_w: float = Field(default=1.2, alias="w")
    size_h: float = Field(default=0.4, alias="h")


class BrandDNA(BaseModel):
    colors: BrandColors = Field(default_factory=BrandColors)
    fonts: BrandFonts = Field(default_factory=BrandFonts)
    logo: Optional[BrandLogo] = None
    design_notes: Optional[str] = None
