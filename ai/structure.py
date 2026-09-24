from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class Metric(BaseModel):
    metric: str = Field(description="metric name")
    value: str = Field(description="reported value, including baseline and unit when available")
    setting: Optional[str] = Field(description="dataset, traffic slice, experiment, or evaluation setting")


class ScoreBreakdown(BaseModel):
    career_relevance: float = Field(ge=0, le=3)
    institution_authority: float = Field(ge=0, le=2.5)
    evidence_strength: float = Field(ge=0, le=2)
    novelty_progress: float = Field(ge=0, le=1.5)
    potential_impact: float = Field(ge=0, le=1)


class UniversityAffiliation(BaseModel):
    name: str = Field(description="canonical university name")
    tier: int = Field(ge=0, le=3, description="computer science and AI strength tier")
    reason: str = Field(description="brief evidence-based reason for the tier")


class Structure(BaseModel):
    decision: Literal["keep", "reject"] = Field(description="single authoritative filtering decision")
    relevance_reason: str = Field(description="evidence-based reason for the filtering decision")
    evidence_level: Literal["A_real_production", "B_company_offline", "C_industry_relevant_academic"]
    company: Optional[str] = None
    team: Optional[str] = None
    universities: List[UniversityAffiliation] = Field(default_factory=list)
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
    importance_score: float = Field(ge=0, le=10)
    importance_label: Literal["必看", "强烈推荐", "值得浏览", "可选阅读", "不建议"]
    score_confidence: Literal["高", "中", "低"]
    score_breakdown: ScoreBreakdown
    institution_evidence: str
    why_read: str
    score_penalties: List[str]
