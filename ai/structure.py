from pydantic import BaseModel, Field, field_validator
import re

class Structure(BaseModel):
    is_relevant: bool = Field(description="whether the paper matches the requested industrial scope")
    relevance_reason: str = Field(description="brief evidence-based reason for keeping or rejecting the paper")
    tldr: str = Field(description="concise industrial-context executive summary")
    motivation: str = Field(description="business scenario, pipeline stage, and problem being solved")
    method: str = Field(description="model architecture, core idea, and technical innovations")
    result: str = Field(description="offline and online results, model scale, and resource costs")
    conclusion: str = Field(description="practical value, limitations, and transferable lessons")
