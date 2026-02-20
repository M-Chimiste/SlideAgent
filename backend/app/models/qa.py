from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class QAIssue(BaseModel):
    severity: Literal["CRITICAL", "WARNING", "INFO"] = "INFO"
    message: str
    slide_index: Optional[int] = None
    category: Optional[str] = None


class QAResult(BaseModel):
    issues: List[QAIssue] = Field(default_factory=list)
    passed: bool


class QAEnvelope(BaseModel):
    issues: List[QAIssue] = Field(default_factory=list)
