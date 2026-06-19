import html
import math
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lxml import etree

from app.models.brand import BrandDNA
from app.models.outline import SlideOutline


SVG_NS = "http://www.w3.org/2000/svg"
VIEWBOX_W = 960
VIEWBOX_H = 520


class DiagramRenderError(RuntimeError):
    pass


@dataclass(frozen=True)
class DiagramArtifact:
    svg_path: Path
    html_path: Path
    png_path: Path
    spec: dict[str, Any]


class ConceptDiagramRenderer:
    def render(
        self,
        outline: SlideOutline,
        brand: BrandDNA,
        output_dir: Path,
        stem: str,
        dark: bool = False,
    ) -> DiagramArtifact:
        output_dir.mkdir(parents=True, exist_ok=True)
        spec = self.diagram_spec(outline)
        svg = self.svg_for_spec(spec, brand, dark=dark)
        self.validate_svg(svg)
        svg_path = output_dir / f"{stem}.svg"
        html_path = output_dir / f"{stem}.html"
        png_path = output_dir / f"{stem}.png"
        svg_path.write_text(svg, encoding="utf-8")
        html_path.write_text(self._html_preview(svg, outline.label), encoding="utf-8")
        self.rasterize_svg(svg_path, png_path)
        return DiagramArtifact(
            svg_path=svg_path,
            html_path=html_path,
            png_path=png_path,
            spec=spec,
        )

    def diagram_spec(self, outline: SlideOutline) -> dict[str, Any]:
        explicit = outline.content_json.get("diagram_spec")
        if isinstance(explicit, dict) and explicit.get("kind"):
            return explicit
        layout = str(outline.layout_json.get("layout") or "").lower()
        exhibit = outline.content_json.get("exhibit_spec")
        exhibit = exhibit if isinstance(exhibit, dict) else {}
        exhibit_type = str(exhibit.get("type") or "").lower().replace("-", "_")
        if layout == "dependency_map" or exhibit_type == "dependency_map":
            return self._dependency_spec(outline, exhibit)
        if layout == "framework_cycle" or exhibit_type in {"cycle", "process"}:
            return self._cycle_spec(outline, exhibit)
        raise DiagramRenderError(f"Unsupported diagram layout: {layout or exhibit_type}")

    def svg_for_spec(
        self, spec: dict[str, Any], brand: BrandDNA, dark: bool = False
    ) -> str:
        kind = str(spec.get("kind") or "").lower()
        if kind == "dependency_flow":
            body = self._dependency_svg(spec, brand, dark)
        elif kind == "cycle":
            body = self._cycle_svg(spec, brand, dark)
        else:
            raise DiagramRenderError(f"Unsupported diagram kind: {kind}")
        return (
            f'<svg width="100%" viewBox="0 0 {VIEWBOX_W} {VIEWBOX_H}" '
            f'xmlns="{SVG_NS}">\n'
            f"{self._defs_and_styles(brand, dark)}\n"
            f"{body}\n"
            "</svg>\n"
        )

    def validate_svg(self, svg: str) -> None:
        try:
            root = etree.fromstring(svg.encode("utf-8"))
        except etree.XMLSyntaxError as exc:
            raise DiagramRenderError(f"Invalid SVG XML: {exc}") from exc
        marker = root.xpath(".//*[local-name()='marker' and @id='arrow']")
        if not marker:
            raise DiagramRenderError("Diagram SVG is missing arrow marker.")
        for text in root.xpath(".//*[local-name()='text']"):
            classes = set(str(text.get("class") or "").split())
            if not classes & {"t", "ts", "th"}:
                raise DiagramRenderError("Every diagram text node must use t, ts, or th.")
            if text.get("dominant-baseline") != "central":
                raise DiagramRenderError("Diagram text inside nodes needs central baseline.")
        for connector in root.xpath(
            ".//*[local-name()='line' or local-name()='path'][contains(@class, 'arr')]"
        ):
            if connector.get("fill") not in {None, "none"}:
                raise DiagramRenderError("Diagram connectors must use fill='none'.")
        for element in root.xpath(".//*[@x or @y or @cx or @cy]"):
            self._validate_bounds(element)

    def rasterize_svg(self, svg_path: Path, png_path: Path) -> None:
        script_path = Path(__file__).resolve().parents[1] / "workers" / "diagram_renderer.js"
        if shutil.which("node") is None:
            raise DiagramRenderError("Node is not available for diagram rasterization.")
        if not script_path.exists():
            raise DiagramRenderError("Diagram renderer worker is missing.")
        try:
            result = subprocess.run(
                [
                    "node",
                    script_path.as_posix(),
                    svg_path.as_posix(),
                    png_path.as_posix(),
                    "1920",
                    "1040",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise DiagramRenderError(f"Diagram rasterization failed: {exc}") from exc
        if result.returncode != 0 or not png_path.exists() or png_path.stat().st_size <= 0:
            raise DiagramRenderError(
                "Diagram rasterization failed: " + (result.stderr or "empty output")
            )

    def _dependency_spec(
        self, outline: SlideOutline, exhibit: dict[str, Any]
    ) -> dict[str, Any]:
        bullets = [
            self._clean_label(str(item))
            for item in outline.content_json.get("bullets", [])
            if self._clean_label(str(item))
        ]
        middle_nodes = [
            self._clean_label(str(item))
            for item in exhibit.get("middle_nodes", [])
            if self._clean_label(str(item))
        ][:4]
        fallback_nodes = ["Product context", "System patterns", "Active decisions"]
        while len(middle_nodes) < 2:
            next_index = len(middle_nodes)
            middle_nodes.append(
                bullets[next_index] if next_index < len(bullets) else fallback_nodes[next_index]
            )
        return {
            "kind": "dependency_flow",
            "title": outline.label,
            "left_node": self._clean_label(exhibit.get("left_node") or "Source context"),
            "middle_nodes": middle_nodes,
            "right_outcome": self._clean_label(exhibit.get("right_outcome") or outline.label),
            "connector_labels": [
                self._clean_label(str(item))
                for item in exhibit.get("connector_labels", [])
                if self._clean_label(str(item))
            ][:4],
        }

    def _cycle_spec(self, outline: SlideOutline, exhibit: dict[str, Any]) -> dict[str, Any]:
        steps = exhibit.get("steps") if isinstance(exhibit.get("steps"), list) else []
        labels = [
            self._clean_label(step.get("label") or step.get("description") or "")
            for step in steps
            if isinstance(step, dict)
            and self._clean_label(step.get("label") or step.get("description") or "")
        ][:6]
        if not labels:
            labels = [
                self._clean_label(str(item))
                for item in outline.content_json.get("bullets", [])
                if self._clean_label(str(item))
            ][:6]
        defaults = ["Frame", "Prime", "Generate", "Review", "Update", "Reset"]
        while len(labels) < 4:
            labels.append(defaults[len(labels)])
        return {
            "kind": "cycle",
            "title": outline.label,
            "center_label": self._clean_label(exhibit.get("center_label") or "Operating loop"),
            "steps": [{"label": label} for label in labels[:6]],
        }

    def _dependency_svg(
        self, spec: dict[str, Any], brand: BrandDNA, dark: bool
    ) -> str:
        left_label = self._fit_label(
            self._clean_label(spec.get("left_node") or "Source context"), 24
        )
        right_label = self._fit_label(
            self._dependency_outcome_label(spec.get("right_outcome") or "Reliable output"),
            36,
        )
        middle_nodes = [
            self._dependency_node_label(str(item))
            for item in spec.get("middle_nodes", [])
            if self._clean_label(str(item))
        ][:4]
        while len(middle_nodes) < 2:
            middle_nodes.append(["Rules", "Memory", "Review"][len(middle_nodes)])
        y_positions = self._stack_positions(len(middle_nodes), 82, 110)
        parts = [
            self._node(60, 220, 210, 80, left_label, "", "primary", dark),
            self._node(720, 220, 200, 80, right_label, "", "accent", dark),
        ]
        for index, label in enumerate(middle_nodes):
            y = y_positions[index]
            parts.append(self._node(360, y, 250, 74, label, "", "secondary", dark))
            parts.append(self._path(f"M270 260 C310 260 320 {y + 37} 350 {y + 37}", "secondary"))
            parts.append(self._path(f"M620 {y + 37} C660 {y + 37} 670 260 710 260", "accent"))
            connector_labels = spec.get("connector_labels", [])
            if index < len(connector_labels):
                parts.append(
                    self._label(
                        302,
                        y + 20,
                        self._fit_label(self._clean_label(connector_labels[index]), 14),
                        "secondary",
                    )
                )
        return "\n".join(parts)

    def _dependency_node_label(self, text: str) -> str:
        fitted = self._fit_label(self._clean_label(text), 42)
        words = fitted.split()
        if len(words) > 5:
            fitted = " ".join(words[:5])
        trailing = {"a", "an", "and", "as", "for", "from", "in", "of", "the", "to", "when", "where", "why", "with"}
        while fitted.split() and fitted.split()[-1].lower() in trailing:
            fitted = " ".join(fitted.split()[:-1]).strip(" ,;:.")
        return fitted or self._fit_label(text, 30)

    def _cycle_svg(self, spec: dict[str, Any], brand: BrandDNA, dark: bool) -> str:
        steps = [
            self._fit_label(
                self._clean_label(item.get("label") or item.get("description") or ""),
                20,
            )
            for item in spec.get("steps", [])
            if isinstance(item, dict)
            and self._clean_label(item.get("label") or item.get("description") or "")
        ][:6]
        while len(steps) < 4:
            steps.append(["Frame", "Prime", "Generate", "Review", "Update", "Reset"][len(steps)])
        center_label = self._fit_label(
            self._clean_label(spec.get("center_label") or "Operating loop"), 18
        )
        center_x, center_y = 480, 260
        positions: list[tuple[int, int, float]] = []
        count = len(steps)
        for index in range(count):
            angle = -math.pi / 2 + index * (2 * math.pi / count)
            x = int(center_x + 315 * math.cos(angle))
            y = int(center_y + 175 * math.sin(angle))
            positions.append((x, y, angle))
        parts = [
            f'<circle cx="{center_x}" cy="{center_y}" r="72" class="hub" />',
            self._center_text(center_x, center_y, center_label),
        ]
        for index, (x, y, angle) in enumerate(positions):
            next_x, next_y, next_angle = positions[(index + 1) % count]
            if index == count - 1:
                next_angle += 2 * math.pi
            control_angle = (angle + next_angle) / 2
            control_x = int(center_x + 365 * math.cos(control_angle))
            control_y = int(center_y + 212 * math.sin(control_angle))
            parts.append(
                self._path(
                    f"M{x} {y} Q{control_x} {control_y} {next_x} {next_y}",
                    "accent",
                )
            )
        for index, (x, y, _angle) in enumerate(positions):
            color = ["primary", "secondary", "accent"][index % 3]
            parts.append(self._node(x - 92, y - 34, 184, 68, steps[index], "", color, dark))
        return "\n".join(parts)

    def _defs_and_styles(self, brand: BrandDNA, dark: bool) -> str:
        colors = {
            "primary": self._clean_hex(brand.colors.primary),
            "secondary": self._clean_hex(brand.colors.secondary),
            "accent": self._clean_hex(brand.colors.accent),
            "text": "F8FAFC" if dark else self._clean_hex(brand.colors.text_dark),
            "muted": "CBD5E1" if dark else "475569",
            "surface": "111827" if dark else "FFFFFF",
        }
        return f"""
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5"
            markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke"
            stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
    </marker>
  </defs>
  <style>
    .t {{ font-family: Aptos, Arial, sans-serif; font-size: 18px; fill: #{colors["text"]}; }}
    .th {{ font-family: Aptos, Arial, sans-serif; font-size: 18px; font-weight: 700; fill: #{colors["text"]}; }}
    .ts {{ font-family: Aptos, Arial, sans-serif; font-size: 14px; fill: #{colors["muted"]}; }}
    .node rect {{ stroke-width: 1; }}
    .primary rect {{ fill: #{self._mix(colors["primary"], colors["surface"], 0.28 if dark else 0.12)}; stroke: #{colors["primary"]}; }}
    .secondary rect {{ fill: #{self._mix(colors["secondary"], colors["surface"], 0.26 if dark else 0.1)}; stroke: #{colors["secondary"]}; }}
    .accent rect {{ fill: #{self._mix(colors["accent"], colors["surface"], 0.28 if dark else 0.14)}; stroke: #{colors["accent"]}; }}
    .hub {{ fill: #{self._mix(colors["primary"], colors["surface"], 0.3 if dark else 0.12)}; stroke: #{colors["accent"]}; stroke-width: 2; }}
    .arr {{ fill: none; stroke-width: 3; stroke-linecap: round; marker-end: url(#arrow); opacity: 0.9; }}
    .arr.primary {{ stroke: #{colors["primary"]}; }}
    .arr.secondary {{ stroke: #{colors["secondary"]}; }}
    .arr.accent {{ stroke: #{colors["accent"]}; }}
  </style>"""

    def _node(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        title: str,
        subtitle: str,
        color: str,
        dark: bool,
    ) -> str:
        max_lines = 3 if height >= 68 else 2
        title_lines = self._wrap(title, max(8, int((width - 44) / 10)), max_lines)
        line_gap = 18 if len(title_lines) >= 3 else 20
        first_y = y + height / 2 - ((len(title_lines) - 1) * line_gap / 2)
        lines = [
            f'<g class="node {color}">',
            f'  <rect x="{x}" y="{y}" width="{width}" height="{height}" rx="12" />',
        ]
        for index, line in enumerate(title_lines):
            lines.append(
                f'  <text class="th" x="{x + width / 2:.1f}" y="{first_y + index * line_gap:.1f}" '
                f'text-anchor="middle" dominant-baseline="central">{html.escape(line)}</text>'
            )
        if subtitle:
            lines.append(
                f'  <text class="ts" x="{x + width / 2:.1f}" y="{y + height - 16}" '
                f'text-anchor="middle" dominant-baseline="central">{html.escape(subtitle)}</text>'
            )
        lines.append("</g>")
        return "\n".join(lines)

    def _center_text(self, x: int, y: int, text: str) -> str:
        lines = self._wrap(text, 10, 2)
        first_y = y - ((len(lines) - 1) * 19 / 2)
        return "\n".join(
            f'<text class="th" x="{x}" y="{first_y + index * 19:.1f}" '
            f'text-anchor="middle" dominant-baseline="central">{html.escape(line)}</text>'
            for index, line in enumerate(lines)
        )

    def _path(self, d: str, color: str) -> str:
        return f'<path d="{d}" class="arr {color}" fill="none" marker-end="url(#arrow)" />'

    def _label(self, x: int, y: int, text: str, color: str) -> str:
        return (
            f'<text class="ts" x="{x}" y="{y}" text-anchor="middle" '
            f'dominant-baseline="central">{html.escape(text)}</text>'
        )

    def _stack_positions(self, count: int, height: int, gap: int) -> list[int]:
        total = count * height + (count - 1) * (gap - height)
        start = int((VIEWBOX_H - total) / 2)
        return [start + index * gap for index in range(count)]

    def _validate_bounds(self, element: etree._Element) -> None:
        limits = {"x": VIEWBOX_W, "cx": VIEWBOX_W, "y": VIEWBOX_H, "cy": VIEWBOX_H}
        for attr, limit in limits.items():
            raw = element.get(attr)
            if raw is None:
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            if value < 0 or value > limit:
                raise DiagramRenderError("Diagram element is outside the safe viewBox.")

    def _html_preview(self, svg: str, title: str) -> str:
        return (
            "<!doctype html><html><head><meta charset=\"utf-8\">"
            f"<title>{html.escape(title)}</title>"
            "<style>body{margin:0;background:#f8fafc;padding:24px;}"
            "main{max-width:1100px;margin:auto;background:white;padding:24px;}</style>"
            "</head><body><main>"
            f"{svg}"
            "</main></body></html>"
        )

    def _fit_label(self, text: str, limit: int) -> str:
        cleaned = self._clean_label(text)
        if len(cleaned) <= limit:
            return cleaned
        for delimiter in ("; ", ". ", ": ", " - ", ", "):
            first_clause = cleaned.split(delimiter, 1)[0].strip(" ,;:.")
            if max(12, int(limit * 0.35)) <= len(first_clause) <= limit:
                return first_clause
        fitted = cleaned[:limit].rsplit(" ", 1)[0].strip(" ,;:.") or cleaned[:limit]
        stop_words = {
            "a",
            "an",
            "and",
            "as",
            "at",
            "by",
            "for",
            "from",
            "in",
            "of",
            "or",
            "that",
            "the",
            "to",
            "with",
        }
        while fitted.split() and fitted.split()[-1].lower() in stop_words:
            fitted = " ".join(fitted.split()[:-1]).strip(" ,;:.")
        return fitted or cleaned[:limit]

    def _wrap(self, text: str, max_chars: int, max_lines: int) -> list[str]:
        words = self._fit_label(text, max_chars * max_lines).split()
        lines: list[str] = []
        current: list[str] = []
        for word in words:
            candidate = " ".join([*current, word])
            if current and len(candidate) > max_chars:
                lines.append(" ".join(current))
                current = [word]
            else:
                current.append(word)
        if current:
            lines.append(" ".join(current))
        return lines[:max_lines] or [""]

    def _clean_label(self, text: Any) -> str:
        cleaned = re.sub(
            r"\[\s*diagram description\s*:[^\]]+\]",
            "",
            str(text or ""),
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"\bdiagram description\s*:[^.]+\.?",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\b(\d+)\.0(?=[A-Za-z]|\b)", r"\1", cleaned)
        cleaned = re.sub(
            r"(\d(?:[\d,]*\.?\d*)?)(tokens\b)",
            r"\1 \2",
            cleaned,
            flags=re.IGNORECASE,
        )
        return " ".join(cleaned.split()).strip(" -:;")

    def _dependency_outcome_label(self, text: Any) -> str:
        cleaned = self._clean_label(text)
        action_starts = (
            "adopt ",
            "contrast ",
            "define ",
            "enforce ",
            "establish ",
            "identify ",
            "implement ",
            "map ",
            "move ",
            "shift ",
            "show ",
            "translate ",
        )
        if len(cleaned) > 44 or cleaned.lower().startswith(action_starts):
            return "Reliable output"
        return cleaned or "Reliable output"

    def _clean_hex(self, value: str) -> str:
        cleaned = str(value or "000000").replace("#", "")[:6]
        return cleaned.upper() if re.fullmatch(r"[0-9A-Fa-f]{6}", cleaned) else "000000"

    def _mix(self, foreground: str, background: str, foreground_weight: float) -> str:
        fg = tuple(int(foreground[index : index + 2], 16) for index in (0, 2, 4))
        bg = tuple(int(background[index : index + 2], 16) for index in (0, 2, 4))
        mixed = tuple(
            round(fg[channel] * foreground_weight + bg[channel] * (1 - foreground_weight))
            for channel in range(3)
        )
        return "".join(f"{part:02X}" for part in mixed)
