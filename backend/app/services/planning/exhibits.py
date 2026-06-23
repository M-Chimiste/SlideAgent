import re
from typing import Any

from app.models.document import DocumentMetric, DocumentSection, DocumentTable
from app.models.generation import ContentBlock


class ExhibitCompiler:
    """Compile source-shaped content into deterministic exhibit specs."""

    def compile(
        self,
        archetype: str,
        role: str,
        section: DocumentSection | None,
        tables: list[DocumentTable],
        metrics: list[DocumentMetric],
    ) -> dict[str, Any]:
        normalized = archetype.strip().lower().replace("-", "_")
        nearby_metrics = self._metric_dicts(metrics)
        if normalized in {"metric_chart", "chart"}:
            if self._same_unit_metrics(nearby_metrics):
                return {"type": "metric_chart", "metrics": nearby_metrics[:6]}
            if self._time_series_metrics(nearby_metrics):
                return {"type": "line_chart", "metrics": nearby_metrics[:8]}
            return {"type": "metric_chart", "metrics": nearby_metrics[:4]}
        if tables:
            table = tables[0]
            if self._looks_like_time_series_table(table):
                return self._line_chart_from_table(table)
            if self._looks_like_comparison_table(table) or normalized == "comparison_table":
                return self._comparison_from_table(table)
            return self._reference_from_table(table)
        bullets = self._section_bullets(section)
        if normalized == "comparison_table":
            return self._comparison_from_bullets(bullets)
        if normalized == "dependency_map":
            return self._dependency_from_bullets(section, bullets)
        if normalized in {"matrix", "2x2", "2x2_matrix", "matrix_2x2"}:
            return self._matrix_from_bullets(bullets)
        if normalized in {"checklist", "process"} or self._looks_ordered(bullets):
            return {
                "type": "checklist",
                "items": [
                    {"action": bullet, "owner": "Owner", "timing": "Next"}
                    for bullet in self._ensure_items(bullets, 3)
                ],
            }
        if normalized in {"table_reference", "reference"} or role == "reference":
            return {
                "type": "reference_table",
                "columns": ["Item", "Implication", "Update trigger"],
                "rows": [
                    [self._short_label(bullet), bullet, "When conditions change"]
                    for bullet in self._ensure_items(bullets, 3)
                ],
            }
        if normalized == "anti_patterns":
            items = self._ensure_items(bullets, 3)
            return {
                "type": "anti_patterns",
                "patterns": [
                    {
                        "name": self._short_label(item),
                        "symptom": item,
                        "consequence": "The operating model becomes harder to trust.",
                        "better_behavior": self._behavior_from_text(item),
                    }
                    for item in items[:4]
                ],
            }
        if normalized in {"framework_cycle", "cycle"}:
            items = self._ensure_items(bullets, 4)
            return {
                "type": "cycle",
                "center_label": self._short_label(section.title if section else "Operating loop"),
                "steps": [
                    {"label": self._short_label(item), "description": item}
                    for item in items[:6]
                ],
            }
        if normalized == "quote_sidebar":
            return {
                "type": "quote_sidebar",
                "key_idea": bullets[0] if bullets else "Make the operating choice explicit.",
                "supporting_points": self._ensure_items(bullets, 3),
            }
        if normalized == "closing_recommendation":
            return {
                "type": "recommendation",
                "recommendation": bullets[0] if bullets else "Commit to the recommended operating change.",
                "next_steps": self._ensure_items(bullets[1:], 3),
                "decision_ask": "Confirm owner, timing, and success measure.",
            }
        return {
            "type": "reference_table",
            "columns": ["Signal", "Implication"],
            "rows": [[self._short_label(bullet), bullet] for bullet in self._ensure_items(bullets, 3)],
        }

    def content_blocks(self, exhibit: dict[str, Any]) -> list[ContentBlock]:
        exhibit_type = str(exhibit.get("type") or "")
        if exhibit_type in {"metric_chart", "line_chart"}:
            # Carry the metrics as readable strings, never raw dicts: if this slide
            # is later diversified to a non-chart layout, the bullet fallback must
            # render "Adoption — 95%", not "{'label': 'Adoption', 'value': 95}".
            return [
                ContentBlock(
                    type="chart",
                    body=[
                        text
                        for metric in exhibit.get("metrics", [])
                        if isinstance(metric, dict)
                        and (text := self._metric_phrase(metric))
                    ],
                )
            ]
        if exhibit_type in {"comparison_table", "reference_table"}:
            rows = []
            columns = exhibit.get("columns")
            if isinstance(columns, list):
                rows.append(columns)
            for row in exhibit.get("rows", []):
                if isinstance(row, dict):
                    rows.append([row.get("label", ""), *row.get("values", [])])
                elif isinstance(row, list):
                    rows.append(row)
            return [ContentBlock(type="table", body=rows)]
        if exhibit_type == "checklist":
            return [
                ContentBlock(
                    type="table",
                    body=[
                        ["Action", "Owner", "Timing"],
                        *[
                            [item.get("action", ""), item.get("owner", ""), item.get("timing", "")]
                            for item in exhibit.get("items", [])
                            if isinstance(item, dict)
                        ],
                    ],
                )
            ]
        if exhibit_type == "anti_patterns":
            return [
                ContentBlock(
                    type="bullets",
                    body=[
                        f"{item.get('name')}: {item.get('better_behavior')}"
                        for item in exhibit.get("patterns", [])
                        if isinstance(item, dict)
                    ],
                )
            ]
        if exhibit_type == "matrix_2x2":
            return [
                ContentBlock(
                    type="table",
                    body=[
                        ["Quadrant", "Meaning"],
                        *[
                            [item.get("label", ""), item.get("description", "")]
                            for item in exhibit.get("quadrants", [])
                            if isinstance(item, dict)
                        ],
                    ],
                )
            ]
        if exhibit_type == "dependency_map":
            middle = exhibit.get("middle_nodes", [])
            body = [
                str(exhibit.get("left_node") or ""),
                *[str(item) for item in middle if str(item).strip()],
                str(exhibit.get("right_outcome") or ""),
            ]
            return [ContentBlock(type="bullets", body=[item for item in body if item])]
        body = []
        for key in ("supporting_points", "next_steps", "points"):
            value = exhibit.get(key)
            if isinstance(value, list):
                body.extend(str(item) for item in value if str(item).strip())
        if not body and exhibit.get("recommendation"):
            body.append(str(exhibit["recommendation"]))
        return [ContentBlock(type="bullets", body=body)]

    def chart_spec(self, exhibit: dict[str, Any]) -> dict[str, Any] | None:
        exhibit_type = str(exhibit.get("type") or "")
        if exhibit_type == "line_chart":
            return {"type": "line", "metrics": exhibit.get("metrics", [])}
        if exhibit_type == "metric_chart":
            return {"type": "bar", "metrics": exhibit.get("metrics", [])}
        return None

    def _dependency_from_bullets(
        self,
        section: DocumentSection | None,
        bullets: list[str],
    ) -> dict[str, Any]:
        items = self._ensure_items(bullets, 3)
        middle = [self._short_label(item) for item in items[:4]]
        title = self._clean_section_title(section.title) if section else ""
        left = title or "Source context"
        return {
            "type": "dependency_map",
            "left_node": left,
            "middle_nodes": middle,
            "right_outcome": "Reliable output",
            "connector_labels": ["feeds", "constrains", "updates"],
        }

    def _section_bullets(self, section: DocumentSection | None) -> list[str]:
        text = section.content if section else ""
        bullets = []
        for line in re.split(r"\n+|(?<=[.!?])\s+", text):
            cleaned = " ".join(line.strip(" -\t").split())
            if cleaned:
                bullets.append(self._truncate(cleaned, 130))
            if len(bullets) >= 5:
                break
        if bullets:
            subject = self._short_label(
                self._clean_section_title(section.title if section else "Source evidence")
            ).lower()
            source_specific = [
                f"Use {subject} as the operating reference.",
                f"Connect {subject} to explicit review gates.",
                f"Refresh {subject} when assumptions change.",
            ]
            for item in source_specific:
                if len(bullets) >= 4:
                    break
                if item not in bullets:
                    bullets.append(item)
            return bullets
        title = section.title if section else "Decision"
        return [f"Clarify the implication of {self._clean_section_title(title)}."]

    def _metric_phrase(self, metric: dict[str, Any]) -> str:
        label = " ".join(str(metric.get("label") or "").split()).strip()
        raw = metric.get("value", "")
        unit = str(metric.get("unit") or "").strip()
        try:
            numeric = float(str(raw).replace(",", "").rstrip("%"))
            if abs(numeric) >= 1_000_000:
                value = f"{numeric / 1_000_000:g}M"
            elif abs(numeric) >= 1_000:
                value = f"{numeric / 1_000:g}k"
            elif numeric.is_integer():
                value = str(int(numeric))
            else:
                value = f"{numeric:g}"
        except (TypeError, ValueError):
            value = str(raw).strip()
        if unit == "%":
            value = f"{value}%"
        elif unit:
            value = f"{value} {unit}"
        if not value.strip():
            return label
        return f"{label} — {value}".strip(" —") if label else value

    def _metric_dicts(self, metrics: list[DocumentMetric]) -> list[dict[str, Any]]:
        return [
            {
                "label": metric.label,
                "value": metric.value,
                "unit": metric.unit,
                "source_id": getattr(metric, "source_id", ""),
            }
            for metric in metrics
        ]

    def _same_unit_metrics(self, metrics: list[dict[str, Any]]) -> bool:
        if len(metrics) < 3:
            return False
        return len({str(metric.get("unit") or "").lower() for metric in metrics}) == 1

    def _time_series_metrics(self, metrics: list[dict[str, Any]]) -> bool:
        if len(metrics) < 3:
            return False
        return sum(1 for metric in metrics if re.search(r"\b(19|20)\d{2}\b", str(metric.get("label")))) >= 3

    def _looks_like_time_series_table(self, table: DocumentTable) -> bool:
        headers = " ".join(table.headers)
        return bool(re.search(r"\b(19|20)\d{2}\b|quarter|month|year", headers, re.IGNORECASE))

    def _looks_like_comparison_table(self, table: DocumentTable) -> bool:
        return len(table.headers) >= 3 and len(table.rows) >= 2

    def _line_chart_from_table(self, table: DocumentTable) -> dict[str, Any]:
        metrics = []
        headers = table.headers
        for row in table.rows[:8]:
            if len(row) < 2:
                continue
            label = row[0]
            for index, cell in enumerate(row[1:], start=1):
                try:
                    value = float(str(cell).replace(",", "").rstrip("%"))
                except ValueError:
                    continue
                metrics.append(
                    {
                        "label": f"{label} {headers[index] if index < len(headers) else index}",
                        "value": value,
                        "unit": "%" if str(cell).strip().endswith("%") else "",
                    }
                )
        return {"type": "line_chart", "metrics": metrics[:8]}

    def _comparison_from_table(self, table: DocumentTable) -> dict[str, Any]:
        return {
            "type": "comparison_table",
            "columns": table.headers[:4],
            "rows": [
                {"label": row[0] if row else "", "values": row[1:4]}
                for row in table.rows[:5]
                if row
            ],
        }

    def _reference_from_table(self, table: DocumentTable) -> dict[str, Any]:
        return {
            "type": "reference_table",
            "columns": table.headers[:4] or ["Item", "Detail"],
            "rows": [row[:4] for row in table.rows[:6]],
        }

    def _comparison_from_bullets(self, bullets: list[str]) -> dict[str, Any]:
        items = self._ensure_items(bullets, 3)
        return {
            "type": "comparison_table",
            "columns": ["Dimension", "Current state", "Target state"],
            "rows": [
                {
                    "label": self._short_label(item),
                    "values": [self._truncate(item, 46), self._behavior_from_text(item)],
                }
                for item in items[:4]
            ],
        }

    def _matrix_from_bullets(self, bullets: list[str]) -> dict[str, Any]:
        items = self._ensure_items(bullets, 4)
        labels = ["High impact / high readiness", "High impact / low readiness", "Low impact / high readiness", "Low impact / low readiness"]
        return {
            "type": "matrix_2x2",
            "x_axis": "Readiness",
            "y_axis": "Impact",
            "quadrants": [
                {"label": labels[index], "description": self._truncate(items[index], 78)}
                for index in range(4)
            ],
        }

    def _ensure_items(self, items: list[str], count: int) -> list[str]:
        cleaned = [item for item in items if item]
        while len(cleaned) < count:
            cleaned.append(
                [
                    "Name the decision owner.",
                    "Confirm the evidence standard.",
                    "Set the review cadence.",
                    "Track changes as conditions shift.",
                ][len(cleaned) % 4]
            )
        return cleaned[: max(count, len(cleaned))]

    def _looks_ordered(self, bullets: list[str]) -> bool:
        text = " ".join(bullets).lower()
        return any(token in text for token in ("first", "then", "next", "finally", "step", "phase"))

    def _behavior_from_text(self, text: str) -> str:
        cleaned = self._truncate(text, 62).rstrip(".")
        if re.match(r"^(define|assign|confirm|review|track|build|use|create)\b", cleaned, re.IGNORECASE):
            return cleaned + "."
        return f"Convert {cleaned[:1].lower() + cleaned[1:]} into an owned action."

    def _short_label(self, text: str) -> str:
        words = re.sub(r"[^A-Za-z0-9\s%-]", "", str(text)).split()
        return " ".join(words[:4]) or "Signal"

    def _clean_section_title(self, title: str) -> str:
        cleaned = re.sub(r"^\d+(?:\.\d+)*\.?\s+", "", str(title)).strip()
        cleaned = re.sub(r"[^A-Za-z0-9\s%-]", "", cleaned)
        return " ".join(cleaned.split()) or "Source evidence"

    def _truncate(self, text: str, limit: int) -> str:
        cleaned = " ".join(str(text).split())
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[:limit].rsplit(" ", 1)[0].rstrip(".,;:")
