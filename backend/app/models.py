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
    # "vendor": a company that bids (the original RevenueForge workspace); "buyer": an organisation that issues RFPs
    kind: Mapped[str] = mapped_column(String(20), default="vendor")
    # Set by a platform admin to pause the whole company: nobody in it can sign in or use the app until reactivated.
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspend_reason: Mapped[str] = mapped_column(String(300), default="")
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
    tokens_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # "sign out everywhere"
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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


class StageComment(Base):
    """A reviewer's note on one stage of a deal, optionally pinned to one line of it (a role, a phase, a requirement...).
    Open notes are the deal owner's to-do list; whoever fixes one marks it resolved."""
    __tablename__ = "stage_comments"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    deal_id: Mapped[str] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(30))
    line_key: Mapped[str] = mapped_column(String(160), default="")  # stable id of the line, "" = the stage as a whole
    line: Mapped[str] = mapped_column(String(300), default="")  # what the line said when the note was written
    text: Mapped[str] = mapped_column(Text)
    user_id: Mapped[str] = mapped_column(String(32), default="")
    author: Mapped[str] = mapped_column(String(200), default="")
    author_role: Mapped[str] = mapped_column(String(30), default="")
    mentions: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(12), default="open")  # open, resolved
    resolved_by: Mapped[str] = mapped_column(String(200), default="")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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


class AiUsage(Base):
    """AI calls per company, provider and model per day: counts and timings only, never prompts or answers."""
    __tablename__ = "ai_usage"
    __table_args__ = (UniqueConstraint("day", "tenant_id", "provider", "model"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD (UTC)
    tenant_id: Mapped[str] = mapped_column(String(32), default="", index=True)  # "" = not a company (website chat)
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(120), default="")
    calls: Mapped[int] = mapped_column(Integer, default=0)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    ms: Mapped[int] = mapped_column(Integer, default=0)  # total time of the calls


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


# --------------------------------------------------------------------------- opportunity radar
class Tender(Base):
    """A public tender notice read from an open-data source (shared by every company; it is public information)."""
    __tablename__ = "tenders"
    __table_args__ = (UniqueConstraint("source", "source_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    source: Mapped[str] = mapped_column(String(20), index=True)  # ted, uk_fts, worldbank, canadabuys, sam
    source_id: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(600), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(8), default="en")  # language of the description
    buyer: Mapped[str] = mapped_column(String(300), default="")
    country: Mapped[str] = mapped_column(String(80), default="")
    region: Mapped[str] = mapped_column(String(40), default="", index=True)
    categories: Mapped[list] = mapped_column(JSON, default=list)  # [{"code", "label"}]
    notice_type: Mapped[str] = mapped_column(String(80), default="")
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="")
    published: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    url: Mapped[str] = mapped_column(String(600), default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Award(Base):
    """A published contract award: who bought what, from which supplier, for how much, and (where the notice says) until
    when. Public information shared by every company, used by "Find customers"."""
    __tablename__ = "awards"
    __table_args__ = (UniqueConstraint("source", "source_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    source: Mapped[str] = mapped_column(String(20), index=True)  # ted, uk_fts, canadabuys
    source_id: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(600), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(8), default="en")
    buyer: Mapped[str] = mapped_column(String(300), default="", index=True)
    country: Mapped[str] = mapped_column(String(80), default="")
    region: Mapped[str] = mapped_column(String(40), default="", index=True)
    categories: Mapped[list] = mapped_column(JSON, default=list)
    suppliers: Mapped[list] = mapped_column(JSON, default=list)  # organisation names of the winners
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="")
    awarded: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    contract_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    end_basis: Mapped[str] = mapped_column(String(40), default="")  # "published end date", "start + duration", ""
    url: Mapped[str] = mapped_column(String(600), default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TenderSource(Base):
    """When each source was last read, and whether it worked."""
    __tablename__ = "tender_sources"
    key: Mapped[str] = mapped_column(String(20), primary_key=True)
    last_run: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_ok: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    cursor: Mapped[str] = mapped_column(String(40), default="")  # awards: oldest date read so far (back-filling)


class TenderFit(Base):
    """How well one company fits one tender, and what the company decided about it."""
    __tablename__ = "tender_fits"
    __table_args__ = (UniqueConstraint("tenant_id", "tender_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    tender_id: Mapped[str] = mapped_column(String(32), ForeignKey("tenders.id", ondelete="CASCADE"), index=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="new")  # new, saved, dismissed, deal
    deal_id: Mapped[str] = mapped_column(String(32), default="")
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# --------------------------------------------------------------------------- supplier network
class NetworkRequest(Base):
    """A buyer's RFP, read once so suppliers can be shortlisted against it."""
    __tablename__ = "network_requests"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)  # the buyer
    title: Mapped[str] = mapped_column(String(300), default="")
    region: Mapped[str] = mapped_column(String(60), default="")
    industry: Mapped[str] = mapped_column(String(120), default="")
    due_date: Mapped[str] = mapped_column(String(30), default="")
    document_id: Mapped[str] = mapped_column(String(32), default="")
    requirements: Mapped[list] = mapped_column(JSON, default=list)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class NetworkInvite(Base):
    """A buyer invited a listed supplier to bid on one request."""
    __tablename__ = "network_invites"
    __table_args__ = (UniqueConstraint("request_id", "vendor_tenant_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    request_id: Mapped[str] = mapped_column(String(32), index=True)
    buyer_tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    vendor_tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(20), default="invited")  # invited, accepted, declined
    message: Mapped[str] = mapped_column(Text, default="")
    fit: Mapped[int] = mapped_column(Integer, default=0)
    deal_id: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
