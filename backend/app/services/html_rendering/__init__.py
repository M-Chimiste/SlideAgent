"""HTML-based slide rendering (headless-Chrome design system)."""

from .renderer import HtmlSlideRenderer, HtmlRenderError, find_chrome

__all__ = ["HtmlSlideRenderer", "HtmlRenderError", "find_chrome"]
