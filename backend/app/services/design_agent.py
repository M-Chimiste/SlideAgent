import concurrent.futures
import random

from app.models.outline import SlideOutline


class DesignAgent:
    def __init__(self) -> None:
        self.icon_pool = {
            "strategy": "FaChessKnight",
            "growth": "FaChartLine",
            "risk": "FaExclamationTriangle",
            "status": "FaTachometerAlt",
            "timeline": "FaProjectDiagram",
            "security": "FaShieldAlt",
            "data": "FaDatabase",
            "customer": "FaUsers",
            "finance": "FaDollarSign",
            "default": "FaLightbulb",
        }
        self.layout_fallbacks = ["icon_rows", "icon_grid", "two_column", "callouts"]

    def apply_design(self, outlines: list[SlideOutline]) -> list[SlideOutline]:
        if len(outlines) < 6:
            return [self._apply_one(outline) for outline in outlines]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            return list(executor.map(self._apply_one, outlines))

    def revise_for_qa(self, outline: SlideOutline) -> SlideOutline:
        if outline.mode != "flexible":
            return outline
        current = outline.layout_json.get("layout", "icon_rows")
        alternatives = [layout for layout in self.layout_fallbacks if layout != current]
        outline.layout_json["layout"] = random.choice(alternatives)
        outline.layout_json["icons"] = self._select_icons(outline)
        outline.layout_json["visual_elements"] = ["icons"]
        return outline

    def _apply_one(self, outline: SlideOutline) -> SlideOutline:
        if outline.mode != "flexible":
            return outline
        layout = outline.layout_json.get("layout", "icon_rows")
        outline.layout_json["layout"] = self._normalize_layout(layout, outline)
        outline.layout_json["icons"] = self._select_icons(outline)
        outline.layout_json["visual_elements"] = ["icons"]
        return outline

    def _normalize_layout(self, layout: str, outline: SlideOutline) -> str:
        if layout == "chart" and not outline.content_json.get("metrics"):
            return "callouts"
        if layout not in self.layout_fallbacks and layout != "chart":
            return "icon_rows"
        return layout

    def _select_icons(self, outline: SlideOutline) -> list[str]:
        title = outline.content_json.get("title", "").lower()
        summary = outline.content_json.get("summary", "").lower()
        combined = f"{title} {summary}"
        selected = []
        for keyword, icon in self.icon_pool.items():
            if keyword in combined and icon not in selected:
                selected.append(icon)
        if not selected:
            selected.append(self.icon_pool["default"])
        while len(selected) < 3:
            selected.append(self.icon_pool["default"])
        return selected[:4]
