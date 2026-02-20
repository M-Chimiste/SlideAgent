from app.services.visual_qa_agent import VisualQAAgent


def test_extract_json_from_fenced_block() -> None:
    agent = VisualQAAgent()
    report = """Some explanation
```json
{"issues":[{"severity":"CRITICAL","message":"Overlap"}]}
```
"""
    payload = agent._extract_json(report)
    assert payload is not None
    assert payload["issues"][0]["message"] == "Overlap"


def test_parse_report_schema_fallback_warning() -> None:
    agent = VisualQAAgent()
    issues = agent._parse_report("not-json", 2)
    assert len(issues) == 1
    assert issues[0].severity == "WARNING"
    assert issues[0].slide_index == 2
