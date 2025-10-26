from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime


class ControlSuggestion(BaseModel):
    priority: str = Field(..., description="Priority level: high, medium, or low")
    control_title: str = Field(..., description="Descriptive title for the control")
    control: str = Field(..., description="Detailed control description")


class ComplianceRequirement(BaseModel):
    requirement_title: str = Field(..., description="Descriptive title for the requirement")
    article_number: str = Field(..., description="Section or article number from the document")
    priority: str = Field(..., description="Priority level: high, medium, or low")
    article_text: str = Field(..., description="Full section text containing the requirement")
    requirement: str = Field(..., description="Concise requirement statement")
    requirement_description: str = Field(..., description="Detailed description of the requirement")
    controls: List[ControlSuggestion] = Field(default_factory=list, description="List of suggested controls")


class AnalysisResult(BaseModel):
    document_name: str
    total_chunks: int = 0
    processed_chunks: int = 0
    requirements_found: int = 0
    extracted_data: List[ComplianceRequirement] = Field(default_factory=list)
    processing_status: str = "pending"
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class TaskStatus(BaseModel):
    task_id: str
    status: str  # pending, processing, completed, failed
    progress: float = 0.0  # 0.0 to 1.0
    message: Optional[str] = None
    result_path: Optional[str] = None
    intermediate_path: Optional[str] = None
    created_at: datetime
    updated_at: datetime = Field(default_factory=datetime.now)
