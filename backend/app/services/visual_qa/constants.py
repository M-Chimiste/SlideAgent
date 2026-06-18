from lxml import etree

EMU_PER_INCH = 914400
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
SAFE_XML_PARSER = etree.XMLParser(resolve_entities=False, no_network=True)

QA_SYSTEM_PROMPT = """You are a visual QA inspector for PowerPoint slides.
Return a JSON object with an array of issues, each with severity (CRITICAL, WARNING, INFO) and message.
Flag text walls, overlaps, cut-off text, low contrast, missing visuals, and repeated layouts.
Return strict JSON only:
{
  "issues": [{"severity":"CRITICAL|WARNING|INFO","message":"...", "category":"...", "slide_index":0}]
}"""
