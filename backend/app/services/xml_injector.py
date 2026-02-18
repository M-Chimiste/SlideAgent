"""XMLInjector: Injects field values into PPTX slide XML by shape ID using lxml.

Uses lxml's XMLParser with resolve_entities=False for safe parsing.
Preserves all formatting attributes from the template.
"""

import logging
from pathlib import Path

from lxml import etree

from app.models.schemas import InjectionTarget

logger = logging.getLogger(__name__)

NSMAP = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}

# Safe parser: disables entity resolution and network access
_SAFE_PARSER = etree.XMLParser(resolve_entities=False, no_network=True)


class XMLInjector:
    def inject(self, staging_dir: Path, targets: list[InjectionTarget]) -> list[str]:
        """Inject all targets into slide XMLs in the staging directory.

        Returns a list of warnings (e.g. shape not found).
        """
        warnings: list[str] = []

        # Group targets by slide index
        by_slide: dict[int, list[InjectionTarget]] = {}
        for target in targets:
            by_slide.setdefault(target.slide_index, []).append(target)

        for slide_index, slide_targets in by_slide.items():
            slide_path = staging_dir / "ppt" / "slides" / f"slide{slide_index}.xml"
            if not slide_path.exists():
                for t in slide_targets:
                    msg = f"Slide file not found: slide{slide_index}.xml (field: {t.field_name})"
                    logger.warning(msg)
                    warnings.append(msg)
                continue

            slide_warnings = self._inject_into_slide(slide_path, slide_targets)
            warnings.extend(slide_warnings)

        return warnings

    def _inject_into_slide(
        self, slide_path: Path, targets: list[InjectionTarget]
    ) -> list[str]:
        """Process all targets for a single slide XML file."""
        warnings: list[str] = []

        tree = etree.parse(str(slide_path), parser=_SAFE_PARSER)
        root = tree.getroot()

        for target in targets:
            shape = self._find_shape_by_id(root, target.shape_id)
            if shape is None:
                msg = (
                    f"Shape ID {target.shape_id} not found in slide {target.slide_index} "
                    f"(field: {target.field_name})"
                )
                logger.warning(msg)
                warnings.append(msg)
                continue

            self._replace_text_in_shape(shape, target.value)

        # Validate modified XML is well-formed by serializing and re-parsing
        xml_bytes = etree.tostring(tree, xml_declaration=True, encoding="UTF-8", standalone=True)
        try:
            etree.fromstring(xml_bytes)
        except etree.XMLSyntaxError as e:
            raise ValueError(
                f"XML became malformed after injection in slide {targets[0].slide_index}: {e}"
            ) from e

        # Write back
        slide_path.write_bytes(xml_bytes)
        return warnings

    def _find_shape_by_id(self, root: etree._Element, shape_id: int) -> etree._Element | None:
        """Find a shape element by its ID attribute on cNvPr."""
        # Standard shapes: p:sp/p:nvSpPr/p:cNvPr[@id]
        xpath = f".//p:sp[p:nvSpPr/p:cNvPr[@id='{shape_id}']]"
        results = root.xpath(xpath, namespaces=NSMAP)
        if results:
            return results[0]
        return None

    def _replace_text_in_shape(self, shape: etree._Element, text: str) -> None:
        """Replace all text in a shape while preserving first run's formatting.

        Strategy:
        1. Find all <a:r> (run) elements in the shape's <a:txBody>.
        2. Set the first run's <a:t> to the full replacement text.
        3. Preserve the first run's <a:rPr> (formatting attributes).
        4. Remove all subsequent <a:r> elements.
        """
        ns_a = NSMAP["a"]
        ns_p = NSMAP["p"]
        # txBody is in the p: namespace, its children (p, r, t, rPr) are in a:
        txBody = shape.find(f".//{{{ns_p}}}txBody")
        if txBody is None:
            return

        # Collect all runs across all paragraphs
        all_runs: list[etree._Element] = []
        paragraphs = txBody.findall(f"{{{ns_a}}}p")
        for para in paragraphs:
            runs = para.findall(f"{{{ns_a}}}r")
            all_runs.extend(runs)

        if not all_runs:
            # No runs exist — create one in the first paragraph
            if not paragraphs:
                return
            first_para = paragraphs[0]
            run = etree.SubElement(first_para, f"{{{ns_a}}}r")
            t_elem = etree.SubElement(run, f"{{{ns_a}}}t")
            t_elem.text = text
            return

        # Set text on the first run
        first_run = all_runs[0]
        t_elem = first_run.find(f"{{{ns_a}}}t")
        if t_elem is None:
            t_elem = etree.SubElement(first_run, f"{{{ns_a}}}t")
        t_elem.text = text

        # Remove all subsequent runs
        for run in all_runs[1:]:
            parent = run.getparent()
            if parent is not None:
                parent.remove(run)

        # Remove empty paragraphs (paragraphs that had only runs which were removed)
        # Keep the first paragraph always
        for para in paragraphs[1:]:
            remaining_runs = para.findall(f"{{{ns_a}}}r")
            if not remaining_runs:
                parent = para.getparent()
                if parent is not None:
                    parent.remove(para)
