import io
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from lxml import etree


CHART_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.drawingml.chart+xml"
)


@dataclass
class SlideReplacement:
    template_slide_number: int
    flexible_slide_number: int


class HybridAssembler:
    def assemble(
        self,
        template_path: Path,
        flexible_path: Path,
        replacements: Iterable[SlideReplacement],
        output_path: Path,
    ) -> None:
        replacements = list(replacements)
        with zipfile.ZipFile(template_path, "r") as template_zip:
            template_entries = {name: template_zip.read(name) for name in template_zip.namelist()}
        with zipfile.ZipFile(flexible_path, "r") as flex_zip:
            flex_entries = {name: flex_zip.read(name) for name in flex_zip.namelist()}

        media_mapping = self._build_media_mapping(template_entries, flex_entries)
        content_types = etree.fromstring(template_entries["[Content_Types].xml"])

        replaced_files = set()
        updated_files = {}
        for replacement in replacements:
            slide_name = f"ppt/slides/slide{replacement.template_slide_number}.xml"
            rel_name = (
                f"ppt/slides/_rels/slide{replacement.template_slide_number}.xml.rels"
            )
            flex_slide_name = f"ppt/slides/slide{replacement.flexible_slide_number}.xml"
            flex_rel_name = (
                f"ppt/slides/_rels/slide{replacement.flexible_slide_number}.xml.rels"
            )
            slide_xml = flex_entries[flex_slide_name]
            rel_xml = flex_entries.get(flex_rel_name, None)
            if rel_xml is not None:
                rel_xml = self._rewrite_relationships(
                    rel_xml, flex_entries, media_mapping, updated_files
                )
            updated_files[slide_name] = slide_xml
            if rel_xml is not None:
                updated_files[rel_name] = rel_xml
            replaced_files.update({slide_name, rel_name})

        self._update_content_types(content_types, updated_files.keys())
        updated_files["[Content_Types].xml"] = etree.tostring(
            content_types, xml_declaration=True, encoding="UTF-8", standalone="yes"
        )

        with zipfile.ZipFile(output_path, "w") as output_zip:
            for name, data in template_entries.items():
                if name in replaced_files:
                    continue
                output_zip.writestr(name, data)
            for name, data in updated_files.items():
                output_zip.writestr(name, data)

    def _build_media_mapping(self, template_entries: dict, flex_entries: dict) -> dict[str, str]:
        existing_media = {
            name.split("/")[-1]
            for name in template_entries
            if name.startswith("ppt/media/")
        }
        mapping = {}
        for name in flex_entries:
            if not name.startswith("ppt/media/"):
                continue
            filename = name.split("/")[-1]
            if filename in existing_media or filename in mapping.values():
                base, ext = filename.rsplit(".", 1)
                new_name = f"{base}_flex.{ext}"
                mapping[filename] = new_name
            else:
                mapping[filename] = filename
        return mapping

    def _rewrite_relationships(
        self,
        rel_xml: bytes,
        flex_entries: dict[str, bytes],
        media_mapping: dict[str, str],
        updated_files: dict[str, bytes],
    ) -> bytes:
        tree = etree.fromstring(rel_xml)
        for rel in tree.findall(".//{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"):
            target = rel.get("Target")
            if not target:
                continue
            if target.startswith("../media/"):
                filename = target.split("/")[-1]
                mapped = media_mapping.get(filename, filename)
                rel.set("Target", f"../media/{mapped}")
                source_name = f"ppt/media/{filename}"
                target_name = f"ppt/media/{mapped}"
                if target_name not in updated_files and source_name in flex_entries:
                    updated_files[target_name] = flex_entries[source_name]
            if target.startswith("../charts/"):
                chart_name = target.split("/")[-1]
                source_name = f"ppt/charts/{chart_name}"
                if source_name in flex_entries and source_name not in updated_files:
                    updated_files[source_name] = flex_entries[source_name]
        return etree.tostring(tree, xml_declaration=True, encoding="UTF-8", standalone="yes")

    def _update_content_types(self, content_types: etree._Element, part_names: Iterable[str]) -> None:
        existing = {
            override.get("PartName")
            for override in content_types.findall(
                ".//{http://schemas.openxmlformats.org/package/2006/content-types}Override"
            )
        }
        for name in part_names:
            if not name.startswith("ppt/charts/"):
                continue
            part_name = f"/{name}"
            if part_name in existing:
                continue
            override = etree.Element(
                "{http://schemas.openxmlformats.org/package/2006/content-types}Override"
            )
            override.set("PartName", part_name)
            override.set("ContentType", CHART_CONTENT_TYPE)
            content_types.append(override)
