"""Pydantic request models (responses are plain dicts shaped per docs/ARCHITECTURE.md)."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

Category = Literal["Population", "Intervention", "Comparator", "Outcomes", "Business"]
Line = Literal["Population", "Intervention", "Comparator", "Outcomes", "Price & access", "Timeline"]
Role = Literal["Asset lead", "Clinical", "Access & pricing", "Forecasting", "Operations", "Reviewer", "Admin"]

ROLE_DEFAULTS = {
    "Asset lead": {"model_tab": "business", "step": "workbench"},
    "Clinical": {"model_tab": "ptrs", "step": "signals"},
    "Access & pricing": {"model_tab": "access", "step": "simulate"},
    "Forecasting": {"model_tab": "demand", "step": "hypotheses"},
    "Operations": {"model_tab": "feasibility", "step": "positions"},
    "Reviewer": {"model_tab": "business", "step": "positions"},
    "Admin": {"model_tab": "business", "step": "studio"},
}

CATEGORY_TO_LINE = {"Population": "Population", "Intervention": "Intervention", "Comparator": "Comparator",
                    "Outcomes": "Outcomes", "Business": "Price & access"}


class ApplyBody(BaseModel):
    overrides: Optional[dict[str, float]] = None
    reason: Optional[str] = None
    actor: Optional[str] = None


class ReasonBody(BaseModel):
    reason: Optional[str] = None
    actor: Optional[str] = None


class HypothesisCreate(BaseModel):
    statement: str = Field(min_length=20)
    category: Category
    position_line: Optional[Line] = None
    owner_role: Role
    confidence_start: float = Field(ge=5, le=95)
    threshold: float = Field(ge=5, le=95)
    change_trigger_text: Optional[str] = None
    keywords: list[str] = []
    agent_ids: list[str] = []

    @model_validator(mode="after")
    def _thr(self):
        if self.threshold <= self.confidence_start:
            raise ValueError("threshold must be greater than starting confidence")
        if self.position_line is None:
            self.position_line = CATEGORY_TO_LINE[self.category]
        return self


class HypothesisPatch(BaseModel):
    statement: Optional[str] = Field(default=None, min_length=20)
    threshold: Optional[float] = Field(default=None, ge=5, le=95)
    change_trigger_text: Optional[str] = None
    keywords: Optional[list[str]] = None
    owner_role: Optional[Role] = None


class LeversBody(BaseModel):
    levers: dict[str, Any]


class ModelRunBody(BaseModel):
    asset: str
    levers: dict[str, Any] = {}
    hypotheses: Optional[dict[str, float]] = None  # optional what-if confidences (0–100) by code


class MonteCarloBody(ModelRunBody):
    n: int = 500


class ScenarioCreate(BaseModel):
    name: str = Field(min_length=1)
    levers: dict[str, Any] = {}
    n: int = 500


class LockBody(BaseModel):
    scenario_id: Optional[str] = None
    actor: Optional[str] = None
    role: Optional[Role] = None


class AgentPatch(BaseModel):
    cadence_minutes: Optional[int] = Field(default=None, ge=60, le=10080)
    status: Optional[Literal["running", "supervised", "planned"]] = None
    description: Optional[str] = None
    name: Optional[str] = None


class AgentCreate(BaseModel):
    name: str = Field(min_length=3)
    key: Optional[str] = None
    category: Literal["always_on", "daily", "on_event"]
    reads: Literal["world", "company", "models"] = "world"
    cadence_minutes: Optional[int] = None
    description: Optional[str] = None
    source_keys: list[str] = []
    hypothesis_ids: list[str] = []


class AssetCreate(BaseModel):
    code: str = Field(min_length=2)
    name: str
    indication: str
    slug: Optional[str] = None
    mechanism: Optional[str] = None
    biomarker: Optional[str] = None
    phase: Optional[str] = None
    governance_forum: Optional[str] = None
    governance_date: Optional[str] = None
    watch_terms: dict[str, list[str]] = {}
