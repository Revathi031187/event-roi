from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class GenerateRequest(BaseModel):
    event_name: str
    additional_context: Optional[str] = ""
    llm_model: str = "gemini-1.5-pro"
    databricks_host: Optional[str] = None
    databricks_token: Optional[str] = None
    genie_space_id: Optional[str] = None


class SlideOutline(BaseModel):
    id: str
    number: int
    title: str
    subtitle: Optional[str] = ""
    points: List[str] = []
    insight: Optional[str] = ""
    table_data: Optional[List[Dict[str, Any]]] = None


class ReportOutline(BaseModel):
    event_name: str
    slides: List[SlideOutline]


class GeneratePPTRequest(BaseModel):
    event_name: str
    outline: ReportOutline
    job_id: str


class JobStartResponse(BaseModel):
    job_id: str
    message: str
