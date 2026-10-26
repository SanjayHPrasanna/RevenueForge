"""Database models. Every business table carries tenant_id; all queries are scoped by it."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    industry: Mapped[str] = mapped_column(String(120), default="")
    website: Mapped[str] = mapped_column(String(200), default="")
    about: Mapped[str] = mapped_column(Text, default="")
    headquarters: Mapped[str] = mapped_column(String(120), default="")
    headcount: Mapped[int] = mapped_column(Integer, default=0)
    founded: Mapped[str] = mapped_column(String(10), default="")
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    # pricing & delivery policy
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    onboarding: Mapped[dict] = mapped_column(JSON, default=dict)  # step -> status
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(30), default="admin")  # admin, presales, architect, finance, delivery, viewer
    password_hash: Mapped[str] = mapped_column(String(300))
    google_sub: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # Google account id once linked
    ms_oid: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # Microsoft (Entra ID) account id once linked
    prefs: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)  # personal settings, e.g. which emails to get
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Document(Base):
    """Any uploaded file: onboarding inputs, RFPs, templates."""
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))  # capabilities, skills, certifications, rates, case_study, accelerators, template, rfp, past_deal
    filename: Mapped[str] = mapped_column(String(300))
    path: Mapped[str] = mapped_column(String(500))
    size: Mapped[int] = mapped_column(Integer, default=0)
    pages: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="uploaded")  # uploaded, parsed, review, imported, failed
    parsed: Mapped[dict] = mapped_column(JSON, default=dict)  # blocks / preview / mapping
    error: Mapped[str] = mapped_column(Text, default="")
    uploaded_by: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Capability(Base):
    __tablename__ = "capabilities"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    service_line: Mapped[str] = mapped_column(String(120), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    technologies: Mapped[list] = mapped_column(JSON, default=list)
    industries: Mapped[list] = mapped_column(JSON, default=list)
    maturity: Mapped[str] = mapped_column(String(30), default="")  # core, established, emerging
    source_doc: Mapped[str] = mapped_column(String(32), default="")


class Employee(Base):
    __tablename__ = "employees"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(120), default="")
    level: Mapped[str] = mapped_column(String(60), default="")
    years: Mapped[float] = mapped_column(Float, default=0)
    location: Mapped[str] = mapped_column(String(120), default="")
    practice: Mapped[str] = mapped_column(String(120), default="")
    skills: Mapped[list] = mapped_column(JSON, default=list)  # [{name, level(1-5)}]
    certifications: Mapped[list] = mapped_column(JSON, default=list)
    availability: Mapped[float] = mapped_column(Float, default=100)  # percent available
    source_doc: Mapped[str] = mapped_column(String(32), default="")


class Certification(Base):
    __tablename__ = "certifications"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(40), default="company")  # company, partner, individual
    issuer: Mapped[str] = mapped_column(String(160), default="")
    holders: Mapped[int] = mapped_column(Integer, default=0)
    valid_until: Mapped[str] = mapped_column(String(20), default="")
    source_doc: Mapped[str] = mapped_column(String(32), default="")


class CaseStudy(Base):
    __tablename__ = "case_studies"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    client: Mapped[str] = mapped_column(String(200), default="")
    industry: Mapped[str] = mapped_column(String(120), default="")
    region: Mapped[str] = mapped_column(String(120), default="")
    year: Mapped[str] = mapped_column(String(10), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    technologies: Mapped[list] = mapped_column(JSON, default=list)
    outcomes: Mapped[list] = mapped_column(JSON, default=list)
    source_doc: Mapped[str] = mapped_column(String(32), default="")


class Accelerator(Base):
    __tablename__ = "accelerators"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    technologies: Mapped[list] = mapped_column(JSON, default=list)
    effort_saving_pct: Mapped[float] = mapped_column(Float, default=0)
    source_doc: Mapped[str] = mapped_column(String(32), default="")


class RateCard(Base):
    __tablename__ = "rate_cards"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(120))
    level: Mapped[str] = mapped_column(String(60), default="")
    location: Mapped[str] = mapped_column(String(60), default="Offshore")  # Onsite / Offshore / Nearshore
    day_rate: Mapped[float] = mapped_column(Float, default=0)  # sell rate per person-day
    day_cost: Mapped[float] = mapped_column(Float, default=0)  # internal cost per person-day
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    source_doc: Mapped[str] = mapped_column(String(32), default="")


class Deal(Base):
    __tablename__ = "deals"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    client_name: Mapped[str] = mapped_column(String(200), default="")
    client_alias: Mapped[str] = mapped_column(String(200), default="")
    client_aliases: Mapped[list] = mapped_column(JSON, default=list)  # extra names to mask, e.g. acronyms
    confidential: Mapped[bool] = mapped_column(Boolean, default=True)
    industry: Mapped[str] = mapped_column(String(120), default="")
    sector: Mapped[str] = mapped_column(String(60), default="")  # Public / Private
    region: Mapped[str] = mapped_column(String(120), default="")
    doc_type: Mapped[str] = mapped_column(String(20), default="RFP")  # RFP, RFI, RFQ, SOW
    engagement_type: Mapped[str] = mapped_column(String(40), default="")  # implementation, managed_services, consulting, product
    currency: Mapped[str] = mapped_column(String(8), default="")
    due_date: Mapped[str] = mapped_column(String(30), default="")
    status: Mapped[str] = mapped_column(String(30), default="new")  # new, processing, in_review, submitted, won, lost, failed
    outcome_notes: Mapped[str] = mapped_column(Text, default="")
    final_value: Mapped[float] = mapped_column(Float, default=0)
    actual_effort_days: Mapped[float] = mapped_column(Float, default=0)
    owner_id: Mapped[str] = mapped_column(String(32), default="")
    rfp_document_id: Mapped[str] = mapped_column(String(32), default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)  # extracted metadata, evaluation criteria, timings
    progress: Mapped[dict] = mapped_column(JSON, default=dict)  # {stage, pct, message}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    requirements: Mapped[list["Requirement"]] = relationship(back_populates="deal", cascade="all, delete-orphan")
    stages: Mapped[list["DealStage"]] = relationship(back_populates="deal", cascade="all, delete-orphan")


class Requirement(Base):
    __tablename__ = "requirements"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    deal_id: Mapped[str] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    code: Mapped[str] = mapped_column(String(40))
    source_ref: Mapped[str] = mapped_column(String(40), default="")  # id used in the RFP itself, e.g. BB-02
    text: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(30))
    subcategory: Mapped[str] = mapped_column(String(60), default="")
    priority: Mapped[str] = mapped_column(String(20), default="Mandatory")
    page: Mapped[int] = mapped_column(Integer, default=1)
    section: Mapped[str] = mapped_column(String(300), default="")
    block_idx: Mapped[int] = mapped_column(Integer, default=-1)
    class_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    technologies: Mapped[list] = mapped_column(JSON, default=list)
    # matching
    match_status: Mapped[str] = mapped_column(String(20), default="")  # strong, partial, gap, confirm
    match_score: Mapped[float] = mapped_column(Float, default=0.0)
    match: Mapped[dict] = mapped_column(JSON, default=dict)
    gap: Mapped[dict] = mapped_column(JSON, default=dict)
    # estimation
    workstream: Mapped[str] = mapped_column(String(120), default="")
    complexity: Mapped[str] = mapped_column(String(10), default="")
    effort_days: Mapped[float] = mapped_column(Float, default=0)
    # how it was classified: ai, company_model, rules, human
    classified_by: Mapped[str] = mapped_column(String(20), default="rules")
    # proposal response for this requirement
    response: Mapped[str] = mapped_column(Text, default="")
    response_source: Mapped[str] = mapped_column(String(20), default="")  # library, ai, rules, human
    response_ref: Mapped[str] = mapped_column(String(32), default="")  # answer-library entry reused
    # human review
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    original_category: Mapped[str] = mapped_column(String(30), default="")
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")

    deal: Mapped[Deal] = relationship(back_populates="requirements")


class RequirementComment(Base):
    """A discussion note on one requirement. Mentions (@name) email the people named."""
    __tablename__ = "requirement_comments"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    deal_id: Mapped[str] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), index=True)
    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String(32), default="")
    author: Mapped[str] = mapped_column(String(200), default="")
    text: Mapped[str] = mapped_column(Text)
    mentions: Mapped[list] = mapped_column(JSON, default=list)  # user ids
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


STAGES = ["requirements", "matching", "gaps", "architecture", "estimation", "pricing", "proposal", "handoff"]


class DealStage(Base):
    __tablename__ = "deal_stages"
    __table_args__ = (UniqueConstraint("deal_id", "stage"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    deal_id: Mapped[str] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, running, draft, approved, failed
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    approved_by: Mapped[str] = mapped_column(String(200), default="")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    deal: Mapped[Deal] = relationship(back_populates="stages")


class GraphNode(Base):
    __tablename__ = "graph_nodes"
    __table_args__ = (UniqueConstraint("tenant_id", "key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    key: Mapped[str] = mapped_column(String(300))  # type:normalized-name
    type: Mapped[str] = mapped_column(String(30))  # Requirement, Capability, Technology, Skill, CaseStudy, Accelerator, Architecture, Resource, Cost, Certification, Deal
    label: Mapped[str] = mapped_column(String(300))
    props: Mapped[dict] = mapped_column(JSON, default=dict)


class GraphEdge(Base):
    __tablename__ = "graph_edges"
    __table_args__ = (UniqueConstraint("tenant_id", "src", "dst", "rel"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    src: Mapped[str] = mapped_column(String(300))
    dst: Mapped[str] = mapped_column(String(300))
    rel: Mapped[str] = mapped_column(String(40))
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    props: Mapped[dict] = mapped_column(JSON, default=dict)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    user: Mapped[str] = mapped_column(String(200), default="")
    action: Mapped[str] = mapped_column(String(80))
    target: Mapped[str] = mapped_column(String(200), default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class LearningExample(Base):
    """A human correction of something the AI (or rules engine) decided. Fed back into future AI runs."""
    __tablename__ = "learning_examples"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # category, subcategory, priority, match, response, added, removed
    deal_id: Mapped[str] = mapped_column(String(32), default="")
    input_text: Mapped[str] = mapped_column(Text)
    ai_value: Mapped[str] = mapped_column(Text, default="")
    human_value: Mapped[str] = mapped_column(Text, default="")
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    user: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AnswerEntry(Base):
    """Reusable, approved proposal answer (the answer library)."""
    __tablename__ = "answer_library"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(30), default="")
    subcategory: Mapped[str] = mapped_column(String(60), default="")
    source_deal: Mapped[str] = mapped_column(String(32), default="")
    source_label: Mapped[str] = mapped_column(String(300), default="")
    outcome: Mapped[str] = mapped_column(String(20), default="pending")  # pending, won, lost
    origin: Mapped[str] = mapped_column(String(20), default="ai")  # ai, human
    uses: Mapped[int] = mapped_column(Integer, default=0)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    approved_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class EmbeddingCache(Base):
    __tablename__ = "embedding_cache"
    __table_args__ = (UniqueConstraint("tenant_id", "key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    key: Mapped[str] = mapped_column(String(64))  # sha1 of text + task
    vector: Mapped[list] = mapped_column(JSON)


class ModelState(Base):
    """A model RevenueForge trained for one company (e.g. its requirement classifier)."""
    __tablename__ = "model_states"
    __table_args__ = (UniqueConstraint("tenant_id", "kind"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    blob: Mapped[str] = mapped_column(Text, default="")  # base64 pickle
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
