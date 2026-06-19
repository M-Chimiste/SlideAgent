from typing import Any, List, Optional

from pydantic import BaseModel, Field


class DocumentSection(BaseModel):
    title: str
    level: int
    content: str
    source_doc_id: str
    source_id: str = ""


class DocumentTable(BaseModel):
    title: Optional[str]
    headers: List[str]
    rows: List[List[str]]
    source_doc_id: str
    source_id: str = ""


class DocumentMetric(BaseModel):
    label: str
    value: float
    unit: Optional[str] = None
    source_doc_id: str
    source_id: str = ""


class DocumentMetadata(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    date: Optional[str] = None
    key_terms: List[str] = Field(default_factory=list)


class DocumentRecord(BaseModel):
    id: str
    job_id: str
    filename: str
    file_path: str
    markdown_content: Optional[str] = None
    structured_json: Optional[dict[str, Any]] = None
    created_at: str


class DocumentBundle(BaseModel):
    job_id: str
    sections: List[DocumentSection]
    tables: List[DocumentTable]
    metrics: List[DocumentMetric]
    metadata: DocumentMetadata
    content_inventory: List[str] = Field(default_factory=list)
    source_index: dict[str, dict[str, str]] = Field(default_factory=dict)
