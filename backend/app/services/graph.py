"""The Deal Knowledge Graph: Requirement ↔ Capability ↔ Technology ↔ Skill ↔ Case Study ↔ Accelerator
↔ Architecture ↔ Resource ↔ Cost, plus Deals and their outcomes. Stored as node/edge tables per tenant."""
from __future__ import annotations

import re

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import knowledge as K
from ..models import (Accelerator, CaseStudy, Capability, Certification, Deal, DealStage, Employee, GraphEdge, GraphNode,
                      RateCard, Requirement)

COMPANY_TYPES = ["Capability", "Technology", "Skill", "CaseStudy", "Accelerator", "Certification", "Resource", "Cost"]


def _key(t: str, name: str) -> str:
    return f"{t}:{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')}"[:290]


class _G:
    def __init__(self, db: Session, tid: str):
        self.db, self.tid = db, tid
        self.nodes: dict[str, GraphNode] = {n.key: n for n in db.scalars(select(GraphNode).where(GraphNode.tenant_id == tid))}
        self.edges: set[tuple] = {(e.src, e.dst, e.rel) for e in db.scalars(select(GraphEdge).where(GraphEdge.tenant_id == tid))}

    def node(self, t: str, label: str, **props) -> str:
        k = _key(t, label)
        n = self.nodes.get(k)
        if n is None:
            n = GraphNode(tenant_id=self.tid, key=k, type=t, label=label[:290], props=props)
            self.db.add(n)
            self.nodes[k] = n
        elif props:
            n.props = {**(n.props or {}), **props}
        return k

    def edge(self, a: str, b: str, rel: str, weight: float = 1.0, **props):
        if (a, b, rel) in self.edges:
            return
        self.edges.add((a, b, rel))
        self.db.add(GraphEdge(tenant_id=self.tid, src=a, dst=b, rel=rel, weight=weight, props=props))


def rebuild_company_graph(db: Session, tid: str) -> dict:
    keys = [n.key for n in db.scalars(select(GraphNode).where(GraphNode.tenant_id == tid, GraphNode.type.in_(COMPANY_TYPES)))]
    if keys:
        db.execute(delete(GraphEdge).where(GraphEdge.tenant_id == tid, (GraphEdge.src.in_(keys)) | (GraphEdge.dst.in_(keys))))
        db.execute(delete(GraphNode).where(GraphNode.tenant_id == tid, GraphNode.type.in_(COMPANY_TYPES)))
        db.flush()
    g = _G(db, tid)
    for c in db.scalars(select(Capability).where(Capability.tenant_id == tid)):
        ck = g.node("Capability", c.name, service_line=c.service_line, id=c.id)
        for t in c.technologies or []:
            g.edge(ck, g.node("Technology", K.canonical_tech(t)), "uses")
    skills: dict[str, int] = {}
    roles: dict[str, dict] = {}
    for e in db.scalars(select(Employee).where(Employee.tenant_id == tid)):
        role = K.normalize_role(e.role)
        rd = roles.setdefault(role, {"count": 0, "skills": {}})
        rd["count"] += 1
        for s in e.skills or []:
            name = K.canonical_tech(s["name"])
            skills[name] = skills.get(name, 0) + 1
            rd["skills"][name] = rd["skills"].get(name, 0) + 1
    for s, n in skills.items():
        sk = g.node("Skill", s, people=n)
        tk = _key("Technology", s)
        if tk in g.nodes:
            g.edge(sk, tk, "applies_to")
    for role, rd in roles.items():
        rk = g.node("Resource", role, headcount=rd["count"])
        for s, n in sorted(rd["skills"].items(), key=lambda kv: -kv[1])[:8]:
            g.edge(rk, _key("Skill", s), "has_skill", weight=n)
    for rc in db.scalars(select(RateCard).where(RateCard.tenant_id == tid)):
        role = K.normalize_role(rc.role)
        ck = g.node("Cost", f"{role} · {rc.location}", day_rate=rc.day_rate, day_cost=rc.day_cost, currency=rc.currency)
        g.edge(g.node("Resource", role), ck, "priced_at")
    caps = [(c, {K.canonical_tech(t) for t in c.technologies or []} - K.COMMODITY_TECH)
            for c in db.scalars(select(Capability).where(Capability.tenant_id == tid))]
    for cs in db.scalars(select(CaseStudy).where(CaseStudy.tenant_id == tid)):
        k = g.node("CaseStudy", cs.title, industry=cs.industry, id=cs.id)
        techs = {K.canonical_tech(t) for t in cs.technologies or []}
        for t in techs:
            g.edge(k, g.node("Technology", t), "used")
        for c, ctechs in caps:
            # A case study proves a capability only when it used most of what makes that capability: two shared
            # technologies, or the capability's only one. One shared umbrella name ("TIBCO", "Azure") isn't proof.
            shared = techs & ctechs
            if ctechs and len(shared) >= min(2, len(ctechs)):
                g.edge(k, _key("Capability", c.name), "proves", weight=round(len(shared) / len(ctechs), 2))
    for a in db.scalars(select(Accelerator).where(Accelerator.tenant_id == tid)):
        k = g.node("Accelerator", a.name, saving=a.effort_saving_pct)
        for t in a.technologies or []:
            g.edge(k, g.node("Technology", K.canonical_tech(t)), "accelerates")
    for c in db.scalars(select(Certification).where(Certification.tenant_id == tid)):
        k = g.node("Certification", c.name, kind=c.kind)
        for t in K.find_technologies(c.name + " " + c.issuer):
            g.edge(k, g.node("Technology", t), "certifies")
    db.flush()
    return {"nodes": len(g.nodes), "edges": len(g.edges)}


def add_deal_to_graph(db: Session, deal: Deal) -> None:
    tid = deal.tenant_id
    # remove previous deal subgraph
    prefix = f"Requirement:{deal.id[:8]}-"
    old = [n.key for n in db.scalars(select(GraphNode).where(GraphNode.tenant_id == tid, GraphNode.key.like(f"{prefix}%")))]
    dk = f"Deal:{deal.id}"
    old_arch = [n.key for n in db.scalars(select(GraphNode).where(GraphNode.tenant_id == tid, GraphNode.type == "Architecture",
                                                                 GraphNode.key.like(f"Architecture:{deal.id[:8]}-%")))]
    drop = old + old_arch + [dk]
    db.execute(delete(GraphEdge).where(GraphEdge.tenant_id == tid, (GraphEdge.src.in_(drop)) | (GraphEdge.dst.in_(drop))))
    db.execute(delete(GraphNode).where(GraphNode.tenant_id == tid, GraphNode.key.in_(drop)))
    db.flush()
    g = _G(db, tid)
    dk = f"Deal:{deal.id}"
    label = f"{deal.client_alias or 'Client'} · {deal.name}" if deal.confidential else f"{deal.client_name} · {deal.name}"
    if dk not in g.nodes:
        n = GraphNode(tenant_id=tid, key=dk, type="Deal", label=label[:290], props={})
        db.add(n)
        g.nodes[dk] = n
    g.nodes[dk].label = label[:290]
    g.nodes[dk].props = {"deal_id": deal.id, "status": deal.status, "industry": deal.industry}
    reqs = db.scalars(select(Requirement).where(Requirement.deal_id == deal.id)).all()
    for r in reqs:
        if r.category == "Commercial" or r.match_status == "confirm":
            continue
        rk = f"Requirement:{deal.id[:8]}-{r.code.lower()}"
        if rk not in g.nodes:
            n = GraphNode(tenant_id=tid, key=rk, type="Requirement", label=f"{r.source_ref or r.code}: {r.text[:120]}",
                          props={"deal_id": deal.id, "status": r.match_status, "category": r.category, "page": r.page})
            db.add(n)
            g.nodes[rk] = n
        g.edge(rk, dk, "part_of")
        for e in (r.match or {}).get("evidence", [])[:2]:
            t = {"Capability": "Capability", "Case study": "CaseStudy", "Accelerator": "Accelerator", "Certification": "Certification"}.get(e["type"])
            if t and _key(t, e["name"]) in g.nodes:
                g.edge(rk, _key(t, e["name"]), "matched", weight=e.get("score", 0.5))
        for t in r.technologies or []:
            if t in K.COMMODITY_TECH:
                continue
            g.edge(rk, g.node("Technology", t), "needs")
    arch = db.scalar(select(DealStage).where(DealStage.deal_id == deal.id, DealStage.stage == "architecture"))
    if arch and arch.data:
        for l in arch.data.get("layers", []):
            for c in l.get("components", [])[:5]:
                ak = f"Architecture:{deal.id[:8]}-{re.sub(r'[^a-z0-9]+', '-', c['name'].lower())}"[:290]
                if ak not in g.nodes:
                    n = GraphNode(tenant_id=tid, key=ak, type="Architecture", label=c["name"], props={"layer": l["layer"], "deal_id": deal.id, "source": c["source"]})
                    db.add(n)
                    g.nodes[ak] = n
                g.edge(dk, ak, "designs")
                tk = _key("Technology", c["name"])
                if tk in g.nodes:
                    g.edge(ak, tk, "uses")
    est = db.scalar(select(DealStage).where(DealStage.deal_id == deal.id, DealStage.stage == "estimation"))
    if est and est.data:
        for t in est.data.get("team", []):
            rk = _key("Resource", t["role"])
            if rk in g.nodes:
                g.edge(dk, rk, "staffs", weight=t["fte"])
    db.flush()


def subgraph(db: Session, tid: str, deal_id: str | None = None, types: list[str] | None = None, limit: int = 600) -> dict:
    nodes = db.scalars(select(GraphNode).where(GraphNode.tenant_id == tid)).all()
    edges = db.scalars(select(GraphEdge).where(GraphEdge.tenant_id == tid)).all()
    keep = {n.key for n in nodes}
    if deal_id:
        seed = {n.key for n in nodes if (n.props or {}).get("deal_id") == deal_id}
        frontier = set(seed)
        for _ in range(2):
            nxt = set()
            for e in edges:
                if e.src in frontier and e.dst not in seed:
                    nxt.add(e.dst)
                if e.dst in frontier and e.src not in seed and not e.src.startswith(("Requirement:", "Deal:")):
                    nxt.add(e.src)
            seed |= nxt
            frontier = nxt
        keep = seed
    if types:
        keep = {k for k in keep if k.split(":", 1)[0] in types}
    nodes = [n for n in nodes if n.key in keep][:limit]
    keep = {n.key for n in nodes}
    deg: dict[str, int] = {}
    out_edges = []
    for e in edges:
        if e.src in keep and e.dst in keep:
            out_edges.append({"source": e.src, "target": e.dst, "rel": e.rel, "weight": e.weight})
            deg[e.src] = deg.get(e.src, 0) + 1
            deg[e.dst] = deg.get(e.dst, 0) + 1
    return {"nodes": [{"id": n.key, "type": n.type, "label": n.label, "props": n.props or {}, "degree": deg.get(n.key, 0)} for n in nodes],
            "edges": out_edges}
