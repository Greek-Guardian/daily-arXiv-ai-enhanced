from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class Metric(BaseModel):
    metric: str = Field(description="metric name")
    value: str = Field(description="reported value, including baseline and unit when available")
    setting: Optional[str] = Field(description="dataset, traffic slice, experiment, or evaluation setting")


class Structure(BaseModel):
    decision: Literal["keep", "reject"] = Field(description="single authoritative filtering decision")
    relevance_reason: str = Field(description="evidence-based reason for the filtering decision")
    evidence_level: Literal["A_real_production", "B_company_offline", "C_industry_relevant_academic"]
    company: Optional[str] = None
    team: Optional[str] = None
    business_scenario: Optional[str] = None
    paper_domain: List[str]
    pipeline_stage: List[str]
    core_problem: str
    core_innovations: List[str]
    offline_gains: List[Metric]
    online_gains: List[Metric]
    model_scale: Optional[str] = None
    training_resources: Optional[str] = None
    inference_resources: Optional[str] = None
    architecture_detail: str = Field(description="detailed architecture and end-to-end data flow")
    executive_summary: str = Field(description="concise industrial-context summary for the paper card")
