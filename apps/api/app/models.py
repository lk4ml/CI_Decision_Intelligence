"""ORM tables — see docs/ARCHITECTURE.md (binding contract).

Every table has `id` (str uuid4) and `created_at` (UTC).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class _Common:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class Asset(_Common, Base):
    __tablename__ = "assets"
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    mechanism: Mapped[Optional[str]] = mapped_column(Text)
    indication: Mapped[str] = mapped_column(String(200), nullable=False)
    biomarker: Mapped[Optional[str]] = mapped_column(String(100))
    phase: Mapped[Optional[str]] = mapped_column(String(100))
    phase_source: Mapped[str] = mapped_column(String(16), default="user")  # user|registry
    decision_type: Mapped[str] = mapped_column(String(32), default="TPP")
    governance_forum: Mapped[Optional[str]] = mapped_column(String(200))
    governance_date: Mapped[Optional[str]] = mapped_column(String(32))
    descriptor: Mapped[Optional[str]] = mapped_column(Text)
    watch_terms: Mapped[dict] = mapped_column(JSON, default=dict)  # {own:[], competitors:[], literature:[]}
    # per-asset model configuration (Addendum A #1/#3)
    lever_schema: Mapped[list] = mapped_column(JSON, default=list)  # [{name,label,type,options?,default}]
    model_params: Mapped[dict] = mapped_column(JSON, default=dict)  # {profile, bindings:{role:"Hn"}, inputs:{name:{value,unit,basis}}}
    current_levers: Mapped[dict] = mapped_column(JSON, default=dict)
    # registry reconciliation (Addendum A #12)
    registry_phase: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    registry_nct_ids: Mapped[list] = mapped_column(JSON, default=list)
    registry_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    phase_discrepancy: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    positions: Mapped[list["Position"]] = relationship(back_populates="asset", cascade="all, delete-orphan")
    hypotheses: Mapped[list["Hypothesis"]] = relationship(back_populates="asset", cascade="all, delete-orphan")


ROLES = ["Asset lead", "Clinical", "Access & pricing", "Forecasting", "Operations", "Reviewer", "Admin"]
CATEGORIES = ["Population", "Intervention", "Comparator", "Outcomes", "Business"]
POSITION_LINES = ["Population", "Intervention", "Comparator", "Outcomes", "Price & access", "Timeline"]


class Position(_Common, Base):
    __tablename__ = "positions"
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), nullable=False, index=True)
    line: Mapped[str] = mapped_column(String(32), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    why: Mapped[Optional[str]] = mapped_column(Text)
    owner_role: Mapped[str] = mapped_column(String(64), nullable=False)
    contributor_roles: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="provisional")  # provisional|locked|reopened
    version: Mapped[int] = mapped_column(Integer, default=0)
    statement_template: Mapped[Optional[str]] = mapped_column(Text)

    asset: Mapped[Asset] = relationship(back_populates="positions")
    history: Mapped[list["PositionHistory"]] = relationship(back_populates="position", cascade="all, delete-orphan")


class PositionHistory(_Common, Base):
    __tablename__ = "position_history"
    position_id: Mapped[str] = mapped_column(ForeignKey("positions.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    locked_by: Mapped[Optional[str]] = mapped_column(String(200))
    locked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    position: Mapped[Position] = relationship(back_populates="history")


class Hypothesis(_Common, Base):
    __tablename__ = "hypotheses"
    __table_args__ = (UniqueConstraint("asset_id", "code"),)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)  # Population|Intervention|Comparator|Outcomes|Business
    position_line: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_role: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence_start: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    change_trigger_text: Mapped[Optional[str]] = mapped_column(Text)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    crossed: Mapped[bool] = mapped_column(Boolean, default=False)
    crossed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    asset: Mapped[Asset] = relationship(back_populates="hypotheses")
    agent_links: Mapped[list["HypothesisAgent"]] = relationship(cascade="all, delete-orphan")


class HypothesisAgent(_Common, Base):
    __tablename__ = "hypothesis_agents"
    __table_args__ = (UniqueConstraint("hypothesis_id", "agent_id"),)
    hypothesis_id: Mapped[str] = mapped_column(ForeignKey("hypotheses.id"), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), nullable=False, index=True)


class ConfidenceEvent(_Common, Base):
    __tablename__ = "confidence_events"
    hypothesis_id: Mapped[str] = mapped_column(ForeignKey("hypotheses.id"), nullable=False, index=True)
    signal_id: Mapped[Optional[str]] = mapped_column(ForeignKey("signals.id"), nullable=True, index=True)
    delta_proposed: Mapped[float] = mapped_column(Float, default=0)
    delta_applied: Mapped[float] = mapped_column(Float, default=0)
    actor: Mapped[str] = mapped_column(String(200), default="system")
    reason: Mapped[Optional[str]] = mapped_column(Text)
    undone: Mapped[bool] = mapped_column(Boolean, default=False)  # legacy flag; never mutated (append-only)
    reverts_event_id: Mapped[Optional[str]] = mapped_column(ForeignKey("confidence_events.id"), nullable=True)


class Agent(_Common, Base):
    __tablename__ = "agents"
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)  # always_on|daily|on_event
    reads: Mapped[str] = mapped_column(String(16), default="world")  # world|company|models
    cadence_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|supervised|planned
    description: Mapped[Optional[str]] = mapped_column(Text)
    source_keys: Mapped[list] = mapped_column(JSON, default=list)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AgentRun(_Common, Base):
    __tablename__ = "agent_runs"
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), nullable=False, index=True)
    asset_id: Mapped[Optional[str]] = mapped_column(ForeignKey("assets.id"), nullable=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ok")  # ok|source_unreachable|error|running
    items_fetched: Mapped[int] = mapped_column(Integer, default=0)
    items_new: Mapped[int] = mapped_column(Integer, default=0)
    signals_created: Mapped[int] = mapped_column(Integer, default=0)
    blocked: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Source(_Common, Base):
    __tablename__ = "sources"
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    side: Mapped[str] = mapped_column(String(16), nullable=False)  # world|company
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    access_level: Mapped[Optional[str]] = mapped_column(String(64))
    license_notes: Mapped[Optional[str]] = mapped_column(Text)
    last_fetch_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_ok_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class FetchedItem(_Common, Base):
    __tablename__ = "fetched_items"
    __table_args__ = (UniqueConstraint("source_key", "external_id"),)
    source_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(1000))
    title: Mapped[Optional[str]] = mapped_column(Text)
    content_hash: Mapped[Optional[str]] = mapped_column(String(128))
    raw: Mapped[Optional[Any]] = mapped_column(JSON)
    structured: Mapped[Optional[Any]] = mapped_column(JSON)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Trial(_Common, Base):
    __tablename__ = "trials"
    __table_args__ = (UniqueConstraint("asset_id", "nct_id"),)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), nullable=False, index=True)
    nct_id: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(Text)
    sponsor: Mapped[Optional[str]] = mapped_column(String(300))
    phase: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[Optional[str]] = mapped_column(String(64))
    start_date: Mapped[Optional[str]] = mapped_column(String(32))
    primary_completion: Mapped[Optional[str]] = mapped_column(String(32))
    enrollment: Mapped[Optional[int]] = mapped_column(Integer)
    conditions: Mapped[list] = mapped_column(JSON, default=list)
    interventions: Mapped[list] = mapped_column(JSON, default=list)
    endpoints: Mapped[list] = mapped_column(JSON, default=list)
    role: Mapped[str] = mapped_column(String(16), default="competitor")  # own|competitor|standard
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class Signal(_Common, Base):
    __tablename__ = "signals"
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), nullable=False, index=True)
    agent_id: Mapped[Optional[str]] = mapped_column(ForeignKey("agents.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    so_what: Mapped[Optional[str]] = mapped_column(Text)
    source_name: Mapped[Optional[str]] = mapped_column(String(200))
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)  # guardrail invariant
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)  # guardrail invariant
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    impact: Mapped[str] = mapped_column(String(16), default="normal")  # high|normal
    review_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|applied|dismissed
    reviewer: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    fetched_item_id: Mapped[str] = mapped_column(ForeignKey("fetched_items.id"), nullable=False, index=True)
    so_what_origin: Mapped[str] = mapped_column(String(16), default="rules")  # rules|llm

    moves: Mapped[list["SignalMove"]] = relationship(back_populates="signal", cascade="all, delete-orphan")
    agent: Mapped[Optional[Agent]] = relationship()


class SignalMove(_Common, Base):
    __tablename__ = "signal_moves"
    signal_id: Mapped[str] = mapped_column(ForeignKey("signals.id"), nullable=False, index=True)
    hypothesis_id: Mapped[str] = mapped_column(ForeignKey("hypotheses.id"), nullable=False, index=True)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    rationale: Mapped[Optional[str]] = mapped_column(Text)

    signal: Mapped[Signal] = relationship(back_populates="moves")
    hypothesis: Mapped[Hypothesis] = relationship()


class UnmatchedItem(_Common, Base):
    __tablename__ = "unmatched_items"
    fetched_item_id: Mapped[Optional[str]] = mapped_column(ForeignKey("fetched_items.id"), nullable=True)
    asset_id: Mapped[Optional[str]] = mapped_column(ForeignKey("assets.id"), nullable=True, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)


class Pattern(_Common, Base):
    __tablename__ = "patterns"
    __table_args__ = (UniqueConstraint("asset_id", "key"),)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    position_line: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_text: Mapped[Optional[str]] = mapped_column(Text)
    rationale: Mapped[Optional[str]] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSON, default=list)  # [{lever,value,label}]
    is_fired: Mapped[bool] = mapped_column(Boolean, default=False)


class ProposedDecision(_Common, Base):
    __tablename__ = "proposed_decisions"
    pattern_id: Mapped[str] = mapped_column(ForeignKey("patterns.id"), nullable=False, index=True)
    fired_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    cleared_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    hypothesis_codes: Mapped[list] = mapped_column(JSON, default=list)
    signal_ids: Mapped[list] = mapped_column(JSON, default=list)
    framing: Mapped[str] = mapped_column(String(8), default="frame")  # take|frame
    total_movement: Mapped[float] = mapped_column(Float, default=0)

    pattern: Mapped[Pattern] = relationship()


class Scenario(_Common, Base):
    __tablename__ = "scenarios"
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    levers: Mapped[dict] = mapped_column(JSON, default=dict)
    hypothesis_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    outputs: Mapped[dict] = mapped_column(JSON, default=dict)
    model_versions: Mapped[dict] = mapped_column(JSON, default=dict)


class Brief(_Common, Base):
    __tablename__ = "briefs"
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    exported_by: Mapped[Optional[str]] = mapped_column(String(200))


class AuditEvent(_Common, Base):
    """Append-only, hash-chained."""

    __tablename__ = "audit_events"
    seq: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[Optional[str]] = mapped_column(String(64))
    asset_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    before_hash: Mapped[Optional[str]] = mapped_column(String(64))
    after_hash: Mapped[Optional[str]] = mapped_column(String(64))
    payload: Mapped[Optional[Any]] = mapped_column(JSON)
    prev_hash: Mapped[Optional[str]] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
