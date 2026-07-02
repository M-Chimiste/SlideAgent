from typing import Any, Optional

from pydantic import BaseModel, Field


class EvidenceUnit(BaseModel):
    id: str
    title: str
    source_doc_id: str
    source_type: str = "section"
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)


class SourceCompression(BaseModel):
    quality_profile: str = "balanced"
    section_count: int = 0
    included_section_count: int = 0
    omitted_section_count: int = 0
    coverage: str = "none"
    estimated_tokens: int = 0
    document_manifest: list[dict[str, Any]] = Field(default_factory=list)
    evidence_units: list[EvidenceUnit] = Field(default_factory=list)
    key_claims: list[str] = Field(default_factory=list)
    tensions: list[str] = Field(default_factory=list)
    metrics: list[dict[str, Any]] = Field(default_factory=list)
    tables: list[dict[str, Any]] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)


class StoryBeat(BaseModel):
    beat_number: int
    role: str = "evidence"
    claim: str
    source_refs: list[str] = Field(default_factory=list)
    preferred_exhibit: str = "callouts"
    rationale: str = ""
    # Substantive source points bound from the matching EvidenceUnit(s), used to
    # generate dense content and to enrich/repair thin slides.
    evidence: list[str] = Field(default_factory=list)


class StoryMap(BaseModel):
    status: str = "fallback"
    thesis: str = ""
    narrative_arc: str = "Situation -> Complication -> Resolution"
    recommendation: str = ""
    beats: list[StoryBeat] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    fallback_reason: Optional[str] = None


class SpecGateIssue(BaseModel):
    slide_number: Optional[int] = None
    severity: str = "WARNING"
    category: str
    message: str
    repaired: bool = False


class SpecGateRepair(BaseModel):
    slide_number: Optional[int] = None
    action: str
    before: Optional[str] = None
    after: Optional[str] = None


class SpecGateReport(BaseModel):
    status: str = "pass"
    issues: list[SpecGateIssue] = Field(default_factory=list)
    repairs: list[SpecGateRepair] = Field(default_factory=list)
    issue_count: int = 0
    repaired_count: int = 0
    unresolved_count: int = 0
    summary: dict[str, Any] = Field(default_factory=dict)
