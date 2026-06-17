import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from markitdown import FileConversionException
from markitdown import MarkItDown

from app.models.document import (
    DocumentBundle,
    DocumentMetadata,
    DocumentMetric,
    DocumentRecord,
    DocumentSection,
    DocumentTable,
)


class DocumentIngester:
    def __init__(self) -> None:
        self.markitdown = MarkItDown()

    def ingest_documents(
        self, job_id: str, file_paths: Iterable[Path]
    ) -> tuple[list[DocumentRecord], DocumentBundle]:
        records: list[DocumentRecord] = []
        sections: list[DocumentSection] = []
        tables: list[DocumentTable] = []
        metrics: list[DocumentMetric] = []
        inventory: list[str] = []
        metadata = DocumentMetadata()

        for file_path in file_paths:
            record_id = str(uuid.uuid4())
            markdown = self._convert_to_markdown(file_path)
            record = DocumentRecord(
                id=record_id,
                job_id=job_id,
                filename=file_path.name,
                file_path=file_path.as_posix(),
                markdown_content=markdown,
                structured_json=None,
                created_at=self._timestamp(),
            )
            records.append(record)
            parsed_sections = self._parse_sections(record_id, markdown)
            sections.extend(parsed_sections)
            tables.extend(self._parse_tables(record_id, markdown))
            metrics.extend(self._parse_metrics(record_id, markdown))
            inventory.extend(self._extract_inventory(markdown))
            if not metadata.title:
                metadata.title = file_path.stem

        bundle = DocumentBundle(
            job_id=job_id,
            sections=sections,
            tables=tables,
            metrics=metrics,
            metadata=metadata,
            content_inventory=inventory,
        )
        return records, bundle

    def _convert_to_markdown(self, file_path: Path) -> str:
        try:
            result = self.markitdown.convert(file_path.as_posix())
            return result.text_content or ""
        except FileConversionException:
            if file_path.suffix.lower() == ".docx":
                return self._convert_docx_fallback(file_path)
            raise

    def _convert_docx_fallback(self, file_path: Path) -> str:
        from docx import Document

        document = Document(file_path.as_posix())
        lines: list[str] = []
        for paragraph in document.paragraphs:
            text = paragraph.text.strip()
            if not text:
                continue
            style_name = paragraph.style.name.lower() if paragraph.style else ""
            if "heading 1" in style_name:
                lines.append(f"# {text}")
            elif "heading 2" in style_name:
                lines.append(f"## {text}")
            elif "heading 3" in style_name:
                lines.append(f"### {text}")
            else:
                lines.append(text)
        for table in document.tables:
            rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
            if not rows:
                continue
            header = rows[0]
            lines.append("| " + " | ".join(header) + " |")
            lines.append("| " + " | ".join(["---"] * len(header)) + " |")
            for row in rows[1:]:
                lines.append("| " + " | ".join(row) + " |")
        return "\n\n".join(lines)

    def _parse_sections(self, doc_id: str, markdown: str) -> list[DocumentSection]:
        sections: list[DocumentSection] = []
        current_title = "Overview"
        current_level = 1
        current_lines: list[str] = []
        for line in markdown.splitlines():
            heading_match = re.match(r"^(#+)\s+(.*)", line)
            if heading_match:
                if current_lines:
                    sections.append(
                        DocumentSection(
                            title=current_title,
                            level=current_level,
                            content="\n".join(current_lines).strip(),
                            source_doc_id=doc_id,
                        )
                    )
                    current_lines = []
                current_level = len(heading_match.group(1))
                current_title = heading_match.group(2).strip()
            else:
                if line.strip():
                    current_lines.append(line)
        if current_lines:
            sections.append(
                DocumentSection(
                    title=current_title,
                    level=current_level,
                    content="\n".join(current_lines).strip(),
                    source_doc_id=doc_id,
                )
            )
        return sections

    def _parse_tables(self, doc_id: str, markdown: str) -> list[DocumentTable]:
        tables: list[DocumentTable] = []
        lines = markdown.splitlines()
        idx = 0
        while idx < len(lines) - 1:
            if "|" in lines[idx] and "|" in lines[idx + 1]:
                header = [cell.strip() for cell in lines[idx].split("|") if cell.strip()]
                separator = lines[idx + 1]
                if set(separator.replace("|", "").strip()) <= {"-", ":"}:
                    idx += 2
                    rows = []
                    while idx < len(lines) and "|" in lines[idx]:
                        row = [
                            cell.strip()
                            for cell in lines[idx].split("|")
                            if cell.strip()
                        ]
                        rows.append(row)
                        idx += 1
                    tables.append(
                        DocumentTable(
                            title=None,
                            headers=header,
                            rows=rows,
                            source_doc_id=doc_id,
                        )
                    )
                    continue
            idx += 1
        return tables

    def _parse_metrics(self, doc_id: str, markdown: str) -> list[DocumentMetric]:
        metrics: list[DocumentMetric] = []
        for match in re.finditer(r"([A-Za-z][A-Za-z\s]{2,40})[:\s]+(\d+(\.\d+)?)", markdown):
            label = match.group(1).strip()
            value = float(match.group(2))
            metrics.append(
                DocumentMetric(label=label, value=value, unit=None, source_doc_id=doc_id)
            )
        return metrics

    def _extract_inventory(self, markdown: str) -> list[str]:
        sentences = re.split(r"[.!?]\s+", markdown)
        return [sentence.strip() for sentence in sentences if sentence.strip()][:20]

    def _timestamp(self) -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def fuse_document_bundles(bundles: Iterable[DocumentBundle]) -> DocumentBundle:
    bundles = list(bundles)
    if not bundles:
        return DocumentBundle(
            job_id="unknown",
            sections=[],
            tables=[],
            metrics=[],
            metadata=DocumentMetadata(),
            content_inventory=[],
        )
    job_id = bundles[0].job_id
    sections = []
    tables = []
    metrics = []
    inventory = []
    for bundle in bundles:
        sections.extend(bundle.sections)
        tables.extend(bundle.tables)
        metrics.extend(bundle.metrics)
        inventory.extend(bundle.content_inventory)
    metadata = bundles[0].metadata
    return DocumentBundle(
        job_id=job_id,
        sections=sections,
        tables=tables,
        metrics=metrics,
        metadata=metadata,
        content_inventory=inventory,
    )
