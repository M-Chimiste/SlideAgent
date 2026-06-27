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
        if normalized == "callouts":
            return {"type": "callouts", "points": self._ensure_items(bullets, 3)[:3]}
        if normalized == "icon_rows":
            items = bullets[:4] if len(bullets) >= 3 else self._ensure_items(bullets, 3)
            return {"type": "icon_rows", "items": items}
        if normalized == "two_column":
            items = bullets[:4] if len(bullets) >= 3 else self._ensure_items(bullets, 3)
            return {
                "type": "two_column",
                "left": items[:2],
                "right": items[2:4] or items[:2],
                "points": items[:4],
            }
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
                    {
                        "action": self._action_from_text(bullet),
                        "owner": self._owner_for_action(bullet, index),
                        "timing": self._timing_for_action(bullet, index),
                    }
                    for index, bullet in enumerate(self._ensure_items(bullets, 3))
                ],
            }
        if normalized in {"table_reference", "reference"} or role == "reference":
            triggers = [
                "Evidence changes",
                "Review standard changes",
                "Workflow changes",
                "Ownership changes",
            ]
            return {
                "type": "reference_table",
                "columns": ["Artifact", "Purpose", "Update trigger"],
                "rows": [
                    [
                        self._short_label(bullet),
                        self._complete_fragment(bullet),
                        triggers[index % len(triggers)],
                    ]
                    for index, bullet in enumerate(self._ensure_items(bullets, 3))
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
                "key_idea": bullets[0] if bullets else "Make the key decision explicit.",
                "supporting_points": self._ensure_items(bullets, 3),
            }
        if normalized == "closing_recommendation":
            return {
                "type": "recommendation",
                "recommendation": bullets[0] if bullets else "Commit to the recommended operating change.",
                "next_steps": self._ensure_items(bullets[1:], 3),
                "decision_ask": "Approve the recommended pilot with named owners and a review date.",
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
        if exhibit_type == "callouts":
            points = exhibit.get("points", [])
            return [
                ContentBlock(
                    type="callout",
                    body=[str(item) for item in points if str(item).strip()],
                )
            ]
        if exhibit_type == "icon_rows":
            items = exhibit.get("items", [])
            return [
                ContentBlock(
                    type="bullets",
                    body=[str(item) for item in items if str(item).strip()],
                )
            ]
        if exhibit_type == "two_column":
            points = exhibit.get("points", [])
            if not isinstance(points, list):
                points = [
                    *(exhibit.get("left", []) if isinstance(exhibit.get("left"), list) else []),
                    *(exhibit.get("right", []) if isinstance(exhibit.get("right"), list) else []),
                ]
            return [
                ContentBlock(
                    type="bullets",
                    body=[str(item) for item in points if str(item).strip()],
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
            "right_outcome": f"{title} decision" if title else "Source-backed decision",
            "connector_labels": ["feeds", "constrains", "updates"],
        }

    def _section_bullets(self, section: DocumentSection | None) -> list[str]:
        text = section.content if section else ""
        bullets = []
        for line in re.split(r"\n+|(?<=[.!?])\s+", text):
            cleaned = self._clean_source_item(line)
            if cleaned:
                bullets.append(self._complete_fragment(self._truncate(cleaned, 130)))
            if len(bullets) >= 5:
                break
        if bullets:
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
            "columns": table.headers[:4] or ["Artifact", "Detail"],
            "rows": [row[:4] for row in table.rows[:6]],
        }

    def _comparison_from_bullets(self, bullets: list[str]) -> dict[str, Any]:
        items = self._ensure_items(bullets, 3)
        return {
            "type": "comparison_table",
            "columns": ["Evidence signal", "Unmanaged pattern", "Harness move"],
            "rows": [
                {
                    "label": self._short_label(item),
                    "values": [
                        self._comparison_current_state(item, index),
                        self._comparison_target_move(item, index),
                    ],
                }
                for index, item in enumerate(items[:4])
            ],
        }

    def _comparison_current_state(self, text: str, index: int) -> str:
        lowered = str(text).lower()
        if any(token in lowered for token in ("manual", "label", "human")):
            return "Manual evaluation effort."
        if any(token in lowered for token in ("synthetic", "generate", "frontier model")):
            return "Synthetic shortcut."
        if any(token in lowered for token in ("contract", "specif", "question")):
            return "Implicit expectations."
        if any(token in lowered for token in ("harness", "interface", "execution")):
            return "Unstandardized execution."
        if any(token in lowered for token in ("data catalog", "schema", "metadata")):
            return "Manual discovery bottleneck."
        if any(token in lowered for token in ("ground truth", "evidence", "validated")):
            return "Unverified benchmark assumption."
        if any(token in lowered for token in ("scale", "scalable", "production")):
            return "Ad hoc scaling path."
        return [
            "Unverified claim.",
            "Loose operating implication.",
            "Unassigned review requirement.",
            "Unclear scale condition.",
        ][index % 4]

    def _comparison_target_move(self, text: str, index: int) -> str:
        lowered = str(text).lower()
        if any(token in lowered for token in ("manual", "label", "human")):
            return "Shift judgment to benchmark design."
        if any(token in lowered for token in ("synthetic", "generate", "frontier model")):
            return "Ground tests in validated workflows."
        if any(token in lowered for token in ("contract", "specif", "question")):
            return "Make expectations explicit before execution."
        if any(token in lowered for token in ("harness", "interface", "execution")):
            return "Standardize execution through a harness."
        if any(token in lowered for token in ("data catalog", "schema", "metadata")):
            return "Connect enterprise metadata to discovery."
        if any(token in lowered for token in ("ground truth", "evidence", "validated")):
            return "Bind the benchmark to inspected evidence."
        if any(token in lowered for token in ("scale", "scalable", "production")):
            return "Codify the review gate before scaling."
        return [
            "Turn the claim into a review gate.",
            "Assign evidence ownership before scaling.",
            "Bind the decision to source-backed checks.",
            "Refresh the benchmark when evidence changes.",
        ][index % 4]

    def _matrix_from_bullets(self, bullets: list[str]) -> dict[str, Any]:
        items = self._ensure_items(bullets, 4)
        labels = [self._short_label(item) for item in items[:4]]
        return {
            "type": "matrix_2x2",
            "x_axis": "Operational clarity",
            "y_axis": "Evidence strength",
            "quadrants": [
                {
                    "label": labels[index],
                    "description": self._complete_fragment(self._truncate(items[index], 78)),
                }
                for index in range(4)
            ],
        }

    def _ensure_items(self, items: list[str], count: int) -> list[str]:
        cleaned = [self._clean_source_item(item) for item in items if self._clean_source_item(item)]
        while len(cleaned) < count:
            subject = cleaned[0] if cleaned else "Source claim"
            subject = self._short_label(subject)
            cleaned.append(
                [
                    f"{subject} evidence to inspect.",
                    f"{subject} condition to validate.",
                    f"{subject} implication to resolve.",
                    f"{subject} change to track.",
                ][len(cleaned) % 4]
            )
        return cleaned[: max(count, len(cleaned))]

    def _clean_source_item(self, text: str) -> str:
        cleaned = re.sub(
            r"\(\s*owner\s*/\s*next\s*\)|\bowner\s*/\s*next\b",
            "",
            str(text),
            flags=re.IGNORECASE,
        )
        convert_match = re.match(
            r"\s*convert\s+(.+?)\s+into\s+an?(?:\s+owned)?(?:\s+action)?\.?\s*$",
            cleaned,
            flags=re.IGNORECASE,
        )
        if convert_match:
            cleaned = convert_match.group(1)
        if "|" in cleaned:
            cleaned = self._pipe_row_to_display_text(cleaned)
        return " ".join(cleaned.strip(" -\t:;").split())

    def _pipe_row_to_display_text(self, text: str) -> str:
        cells = [
            " ".join(cell.strip(" -:;").split())
            for cell in str(text).split("|")
            if cell.strip(" -:;")
        ]
        header_cells = {
            "artifact",
            "purpose",
            "update trigger",
            "signal",
            "implication",
            "action",
            "owner",
            "timing",
        }
        meaningful = [
            cell
            for cell in cells
            if cell.casefold() not in header_cells
            and not re.fullmatch(r"-+", cell)
        ]
        if not meaningful:
            return ""
        return max(meaningful, key=lambda cell: (len(cell.split()), len(cell)))

    def _looks_ordered(self, bullets: list[str]) -> bool:
        text = " ".join(bullets).lower()
        return any(token in text for token in ("first", "then", "next", "finally", "step", "phase"))

    def _behavior_from_text(self, text: str) -> str:
        cleaned = self._complete_fragment(self._truncate(text, 86)).rstrip(".")
        if re.match(r"^(define|assign|confirm|review|track|build|use|create)\b", cleaned, re.IGNORECASE):
            return cleaned + "."
        return cleaned + "."

    def _action_from_text(self, text: str) -> str:
        cleaned = self._complete_fragment(self._truncate(text, 96)).rstrip(".")
        if re.match(r"^(define|assign|confirm|review|track|build|use|create|set|document)\b", cleaned, re.IGNORECASE):
            return cleaned + "."
        return cleaned + "."

    def _owner_for_action(self, text: str, index: int) -> str:
        lowered = str(text).lower()
        if any(token in lowered for token in ("contract", "success", "semantic", "question")):
            return "Contract owner"
        if any(token in lowered for token in ("harness", "execute", "workflow", "operational")):
            return "Harness lead"
        if any(token in lowered for token in ("data", "catalog", "schema", "metadata", "source")):
            return "Data owner"
        if any(token in lowered for token in ("review", "quality", "evidence", "validation")):
            return "Review lead"
        return ["Sponsor", "Product lead", "Evaluation lead", "Ops lead"][index % 4]

    def _timing_for_action(self, text: str, index: int) -> str:
        lowered = str(text).lower()
        if any(token in lowered for token in ("define", "contract", "question", "what goes in")):
            return "Define"
        if any(token in lowered for token in ("execute", "harness", "pilot", "workflow")):
            return "Pilot"
        if any(token in lowered for token in ("review", "validation", "evidence", "quality")):
            return "Review"
        if any(token in lowered for token in ("scale", "deployment", "production", "catalog")):
            return "Scale"
        return ["Now", "Next", "Pilot", "Scale"][index % 4]

    def _short_label(self, text: str) -> str:
        words = re.sub(r"[^A-Za-z0-9\s%-]", "", str(text)).split()
        return " ".join(words[:4]) or "Signal"

    def _clean_section_title(self, title: str) -> str:
        cleaned = re.sub(r"^\d+(?:\.\d+)*\.?\s+", "", str(title)).strip()
        cleaned = re.sub(r"[^A-Za-z0-9\s%-]", "", cleaned)
        return " ".join(cleaned.split()) or "Source evidence"

    def _truncate(self, text: str, limit: int) -> str:
        cleaned = " ".join(str(text).split())
        if cleaned.count('"') % 2 == 1:
            return ""
        if len(cleaned) <= limit:
            return self._complete_fragment(cleaned)
        truncated = cleaned[:limit].rsplit(" ", 1)[0].rstrip(".,;:")
        if truncated.count('"') % 2 == 1:
            return ""
        return self._complete_fragment(truncated)

    def _complete_fragment(self, text: str) -> str:
        cleaned = " ".join(str(text).split()).strip(" ,;:")
        trailing = {
            "a",
            "an",
            "and",
            "as",
            "by",
            "for",
            "from",
            "in",
            "into",
            "of",
            "or",
            "the",
            "their",
            "through",
            "to",
            "with",
            "contain",
            "contains",
            "consist",
            "consists",
            "create",
            "determine",
            "generate",
            "has",
            "have",
            "include",
            "includes",
            "need",
            "needs",
            "provide",
            "provides",
            "requires",
            "specified",
            "test",
            "treat",
        }
        words = cleaned.split()
        while words and words[-1].lower().strip(".") in trailing:
            words.pop()
        cleaned = " ".join(words).strip(" ,;:")
        cleaned = re.sub(r"\s+\((?:e\.g|i\.e)\.?$", "", cleaned, flags=re.IGNORECASE)
        if not cleaned:
            return "Clarify the source evidence."
        return cleaned if cleaned.endswith((".", "?", "!")) else f"{cleaned}."
