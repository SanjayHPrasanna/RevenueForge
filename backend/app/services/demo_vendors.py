"""Fictional suppliers for demonstrating the supplier network.

Every company here is invented. Each is marked demo in its settings, so buyers always see "Fictional demo supplier" next
to it, its description says so, and nobody can sign in to it. Set DEMO_VENDORS=false to leave them out.
"""
from __future__ import annotations

import logging
import os
import re

from sqlalchemy import select

log = logging.getLogger("revenueforge.demo")
DEMO_NOTE = "Fictional company created for the RevenueForge supplier-network demo. "

# (name, headquarters, regions served, industries, headcount, about,
#  capabilities [(name, service line, description, technologies)], certificates [(name, kind, issuer)],
#  case studies [(title, industry, region, year, summary, technologies, outcomes)], skills {technology: people at level 3+},
#  products [(name, description, technologies, saving %)])
V = [
    ("Northbeam Integration Partners", "Manchester, United Kingdom", ["United Kingdom", "Europe"], ["Transportation", "Public sector"], 140,
     "Integration specialist for transport and public bodies: API platforms, event streaming and 24x7 managed services.",
     [("API-led Integration", "Integration", "Design and build of API-led integration platforms with gateways, developer portals and OAuth 2.0 security.", ["MuleSoft", "Kong", "OAuth 2.0", "REST APIs"]),
      ("Event Streaming for Transport", "Integration", "Real-time vehicle telemetry, GTFS-Realtime feeds and Kafka event platforms for transit operators.", ["Kafka", "Microsoft Azure", "Kubernetes"]),
      ("Integration Managed Services", "Managed services", "24x7 monitoring, incident and problem management with SLA reporting for integration platforms.", ["ServiceNow", "Splunk", "ITIL"]),
      ("Interface Migration Factory", "Integration", "Wave-based migration of legacy interfaces from ESBs and scripts to modern platforms with automated regression testing.", ["MuleSoft", "Postman", "CI/CD"])],
     [("ISO/IEC 27001:2022", "company", "BSI"), ("ISO 9001:2015", "company", "BSI"), ("Cyber Essentials Plus", "company", "IASME"), ("MuleSoft Partner", "partner", "Salesforce")],
     [("Real-time passenger information platform for a regional bus operator", "Transportation", "United Kingdom", "2025", "Built a Kafka-based event platform streaming positions from 900 buses to passenger apps within 3 seconds.", ["Kafka", "Microsoft Azure"], ["900 buses live", "3-second end-to-end latency"]),
      ("Legacy ESB replacement for a city council", "Public sector", "United Kingdom", "2024", "Migrated 140 interfaces from a legacy ESB to MuleSoft over 10 months with no service outage.", ["MuleSoft"], ["140 interfaces migrated", "Zero unplanned downtime"])],
     {"MuleSoft": 18, "Kafka": 12, "Microsoft Azure": 15, "Kubernetes": 8, "ServiceNow": 6, "OAuth 2.0": 9, "Splunk": 5, "CI/CD": 10, "GraphQL": 3},
     [("Transit Event Accelerator", "Reusable GTFS-Realtime and vehicle telemetry pipelines on Kafka.", ["Kafka"], 15)]),
    ("Aster Cloud Engineering", "Pune, India", ["South Asia", "Middle East & North Africa", "Europe"], ["Banking", "Retail", "Manufacturing"], 420,
     "Cloud migration and platform engineering company: AWS and Azure landing zones, Kubernetes and DevOps.",
     [("Cloud Migration", "Cloud", "Assessment and migration of application estates to AWS and Azure with landing zones and FinOps.", ["AWS", "Microsoft Azure", "Terraform"]),
      ("Platform Engineering", "Cloud", "Kubernetes platforms, CI/CD pipelines and infrastructure as code for product teams.", ["Kubernetes", "Docker", "Terraform", "CI/CD"]),
      ("Cloud Managed Operations", "Managed services", "24x7 cloud operations, cost optimisation and SRE.", ["Prometheus/Grafana", "AWS"])],
     [("ISO/IEC 27001:2022", "company", "TÜV SÜD"), ("SOC 2 Type II", "company", "Independent auditor"), ("AWS Advanced Tier Services Partner", "partner", "AWS")],
     [("Core banking platform move to AWS for a mid-size bank", "Banking", "India", "2025", "Migrated 60 applications to AWS with a regulated landing zone.", ["AWS", "Terraform"], ["60 applications migrated", "28% lower run cost"]),
      ("Kubernetes platform for a retail group", "Retail", "United Arab Emirates", "2024", "Built a shared Kubernetes platform for 25 product teams.", ["Kubernetes", "CI/CD"], ["25 teams onboarded", "Releases from monthly to daily"])],
     {"AWS": 60, "Microsoft Azure": 35, "Kubernetes": 40, "Terraform": 30, "Docker": 38, "CI/CD": 45, "Python": 25, "Prometheus/Grafana": 15}, []),
    ("Meridale Health Informatics", "Toronto, Canada", ["North America", "United Kingdom"], ["Healthcare"], 95,
     "Healthcare integration and interoperability: HL7, FHIR and clinical data migration.",
     [("Clinical Interoperability", "Healthcare", "HL7 v2 and FHIR interfaces between EHR, LIS, RIS and PACS systems.", ["HL7 FHIR", "HL7 v2", "Rhapsody", "Mirth Connect"]),
      ("Clinical Data Migration", "Healthcare", "Migration of patient records between EHR platforms with validation.", ["HL7 FHIR", "SQL Server"])],
     [("ISO/IEC 27001:2022", "company", "BSI"), ("HITRUST CSF Certified", "company", "HITRUST"), ("Rhapsody Partner", "partner", "Lyniate")],
     [("FHIR gateway for a provincial health network", "Healthcare", "Canada", "2025", "Exposed patient summaries from 14 hospitals through a FHIR gateway.", ["HL7 FHIR"], ["14 hospitals connected"])],
     {"HL7 FHIR": 20, "HL7 v2": 25, "Rhapsody": 12, "Mirth Connect": 10, "SQL Server": 8}, [("FHIR Profile Library", "Reusable FHIR R4 profiles and mappings.", ["HL7 FHIR"], 20)]),
    ("Kestrel Data & Analytics", "Amsterdam, Netherlands", ["Europe", "United Kingdom"], ["Energy & utilities", "Public sector", "Transportation"], 210,
     "Data platforms, analytics and machine learning for utilities, transport and government.",
     [("Modern Data Platform", "Data", "Lakehouse platforms on Databricks and Snowflake with data governance and lineage.", ["Databricks", "Snowflake", "Python"]),
      ("Analytics & Dashboards", "Data", "Self-service dashboards and KPI reporting.", ["Power BI", "Tableau"]),
      ("Applied Machine Learning", "AI", "Forecasting and optimisation models in production.", ["Machine Learning", "Python"])],
     [("ISO/IEC 27001:2022", "company", "DNV"), ("Databricks Partner", "partner", "Databricks")],
     [("Ridership forecasting for a metro operator", "Transportation", "Netherlands", "2024", "Built ridership forecasts feeding timetable planning.", ["Machine Learning", "Databricks"], ["12% better forecast accuracy"]),
      ("Grid data lakehouse for a utility", "Energy & utilities", "Germany", "2025", "Consolidated 30 data sources into a governed lakehouse with lineage.", ["Databricks"], ["30 sources consolidated"])],
     {"Databricks": 30, "Snowflake": 18, "Python": 60, "Power BI": 25, "Tableau": 12, "Machine Learning": 28, "Kafka": 6}, []),
    ("Sentinel Shield Security", "Dubai, United Arab Emirates", ["Middle East & North Africa", "South Asia"], ["Banking", "Government"], 160,
     "Cybersecurity services: SOC, penetration testing, identity and compliance programmes.",
     [("Managed SOC", "Security", "24x7 security operations centre with SIEM and incident response.", ["SIEM", "Splunk"]),
      ("Penetration Testing", "Security", "Independent application, API and infrastructure penetration testing.", []),
      ("Identity & Access", "Security", "IAM, SSO, MFA and privileged access programmes.", ["IAM", "MFA", "SAML", "OpenID Connect"])],
     [("ISO/IEC 27001:2022", "company", "BSI"), ("PCI DSS v4.0 QSA company", "company", "PCI SSC"), ("SOC 2 Type II", "company", "Independent auditor")],
     [("SOC for a regional bank", "Banking", "United Arab Emirates", "2025", "Runs the bank's 24x7 SOC with a 15-minute response target.", ["SIEM"], ["15-minute P1 response", "99.9% detection SLA met"])],
     {"SIEM": 25, "Splunk": 15, "IAM": 20, "MFA": 12, "PKI/TLS": 10}, []),
    ("Lumen ERP Consulting", "Singapore", ["East Asia & Pacific", "South Asia"], ["Manufacturing", "Retail", "Logistics"], 300,
     "SAP and Microsoft Dynamics implementations and support.",
     [("SAP S/4HANA Implementation", "ERP", "Greenfield and brownfield S/4HANA programmes.", ["SAP"]),
      ("Dynamics 365", "ERP", "Dynamics 365 finance and supply chain implementations.", ["Microsoft Dynamics"]),
      ("ERP Application Management", "Managed services", "Support and enhancements for SAP and Dynamics.", ["SAP", "ServiceNow"])],
     [("ISO 9001:2015", "company", "SGS"), ("SAP Gold Partner", "partner", "SAP")],
     [("S/4HANA for a regional distributor", "Logistics", "Malaysia", "2024", "Moved 12 warehouses onto S/4HANA in 14 months.", ["SAP"], ["12 sites live"])],
     {"SAP": 120, "SAP PI/PO": 20, "Microsoft Dynamics": 40, "ServiceNow": 10}, []),
    ("Harbourline Digital Studio", "Sydney, Australia", ["East Asia & Pacific"], ["Retail", "Public sector", "Transportation"], 75,
     "Digital agency building web and mobile products and passenger apps.",
     [("Mobile & Web Apps", "Digital", "Native and cross-platform apps and web portals.", ["React", "iOS", "Android", "JavaScript/TypeScript"]),
      ("UX & Service Design", "Digital", "Research-led service design and accessibility.", [])],
     [("ISO/IEC 27001:2022", "company", "SAI Global")],
     [("Passenger app for a ferry operator", "Transportation", "Australia", "2025", "Built a journey planner app with live arrivals.", ["React", "iOS", "Android"], ["4.7 app store rating"])],
     {"React": 25, "iOS": 10, "Android": 10, "JavaScript/TypeScript": 30, "GraphQL": 8}, []),
    ("Quanta Test Labs", "Kraków, Poland", ["Europe", "United Kingdom", "North America"], ["Banking", "Telecom", "Public sector"], 230,
     "Independent software testing: functional, performance, security and test automation.",
     [("Test Automation", "Quality engineering", "Automated regression for web, API and mobile.", ["Postman", "CI/CD", "Java"]),
      ("Performance Engineering", "Quality engineering", "Load and stress testing of high-volume platforms.", []),
      ("Integration Testing", "Quality engineering", "End-to-end interface and API testing with evidence for go-live.", ["Postman"])],
     [("ISO 9001:2015", "company", "TÜV"), ("ISO/IEC 27001:2022", "company", "TÜV")],
     [("Performance testing for a national payments switch", "Banking", "Poland", "2024", "Tested 5,000 transactions per second before launch.", [], ["5,000 TPS validated"])],
     {"Postman": 40, "Java": 50, "CI/CD": 35, "Python": 20}, []),
    ("Ironbark Service Management", "Melbourne, Australia", ["East Asia & Pacific", "United Kingdom"], ["Public sector", "Healthcare", "Education"], 120,
     "ServiceNow partner: ITSM, HR service delivery and managed platform support.",
     [("ServiceNow ITSM", "Service management", "ITSM implementations and upgrades.", ["ServiceNow", "ITIL"]),
      ("ServiceNow Managed Service", "Managed services", "Platform support and enhancements.", ["ServiceNow"])],
     [("ISO/IEC 27001:2022", "company", "BSI"), ("ServiceNow Premier Partner", "partner", "ServiceNow")],
     [("ITSM for a state health department", "Healthcare", "Australia", "2024", "Implemented ITSM for 40,000 users.", ["ServiceNow"], ["40,000 users"])],
     {"ServiceNow": 70, "ITIL": 40, "JavaScript/TypeScript": 25}, []),
    ("Volta Fintech Engineering", "London, United Kingdom", ["United Kingdom", "Europe", "Middle East & North Africa"], ["Banking", "Insurance"], 180,
     "Payments, open banking and fraud prevention engineering.",
     [("Payments Engineering", "Fintech", "Card and real-time payment platforms built to PCI DSS.", ["Java", "Kafka", "PostgreSQL"]),
      ("Open Banking APIs", "Fintech", "Open banking API platforms with consent management.", ["OAuth 2.0", "Apigee"]),
      ("Fraud Analytics", "Fintech", "Real-time fraud scoring and monitoring.", ["Machine Learning", "Device Fingerprinting"])],
     [("ISO/IEC 27001:2022", "company", "BSI"), ("PCI DSS v4.0 Level 1 Service Provider", "company", "QSA"), ("SOC 2 Type II", "company", "Independent auditor")],
     [("Open banking platform for a challenger bank", "Banking", "United Kingdom", "2025", "Launched 40 open banking APIs in six months.", ["Apigee", "OAuth 2.0"], ["40 APIs live"])],
     {"Java": 60, "Kafka": 20, "Apigee": 12, "OAuth 2.0": 18, "Machine Learning": 10, "PostgreSQL": 25}, []),
    ("Tundra GIS Solutions", "Calgary, Canada", ["North America", "Latin America & Caribbean"], ["Energy & utilities", "Public sector", "Transportation"], 60,
     "Geospatial systems: GIS, asset mapping and field mobility for utilities and municipalities.",
     [("Enterprise GIS", "Geospatial", "Esri ArcGIS implementations and spatial data management.", ["PostgreSQL", "Python"]),
      ("Field Mobility", "Geospatial", "Field data collection apps for inspections.", ["Android", "iOS"])],
     [("ISO 9001:2015", "company", "SGS")],
     [("Asset mapping for a water utility", "Energy & utilities", "Canada", "2024", "Digitised 8,000 km of network assets.", ["PostgreSQL"], ["8,000 km mapped"])],
     {"PostgreSQL": 15, "Python": 20, "Android": 6, "iOS": 4}, []),
    ("Cobalt Lane Learning Technologies", "Nairobi, Kenya", ["Sub-Saharan Africa", "South Asia"], ["Education", "Public sector"], 85,
     "Education technology: learning platforms and education management information systems (EMIS).",
     [("Education Management Information Systems", "EdTech", "EMIS design, development and integration for ministries of education.", ["PostgreSQL", "React", "Python"]),
      ("Learning Platforms", "EdTech", "Online learning platforms and content.", ["React"])],
     [("ISO 9001:2015", "company", "Bureau Veritas")],
     [("National EMIS for a ministry of education", "Education", "Kenya", "2024", "Built an EMIS covering 30,000 schools, integrated with the national ID register.", ["PostgreSQL", "React"], ["30,000 schools", "Quarterly census now monthly"]),
      ("School information system upgrade", "Education", "Uganda", "2025", "Integrated legacy school modules into a new EMIS.", ["Python"], ["5 legacy modules integrated"])],
     {"PostgreSQL": 15, "React": 18, "Python": 20, "Android": 5}, []),
    ("Saffron GovTech", "Bengaluru, India", ["South Asia", "Sub-Saharan Africa", "East Asia & Pacific"], ["Government", "Public sector", "Education"], 260,
     "E-government platforms, citizen portals and case management for public bodies.",
     [("Citizen Service Portals", "GovTech", "Citizen portals with identity integration and case management.", ["Java", "React", "PostgreSQL"]),
      ("Government Case Management", "GovTech", "Configurable case management and workflow.", ["Java"]),
      ("Data Integration for Government", "Integration", "Integration of registries and ministries via APIs.", ["WSO2", "REST APIs"])],
     [("ISO/IEC 27001:2022", "company", "STQC"), ("CMMI Level 3", "company", "CMMI Institute"), ("ISO 9001:2015", "company", "STQC")],
     [("State welfare portal", "Government", "India", "2024", "Portal serving 12 million citizens with integrated payments.", ["Java", "React"], ["12 million users"]),
      ("Education management system for a state", "Education", "India", "2025", "Developed and maintains a school information management system with EMIS integration.", ["Java", "PostgreSQL"], ["45,000 schools"])],
     {"Java": 90, "React": 40, "PostgreSQL": 35, "WSO2": 12, "Python": 25}, []),
    ("Polaris Telecom Systems", "Stockholm, Sweden", ["Europe", "Middle East & North Africa"], ["Telecom"], 140,
     "OSS/BSS integration and network automation for telecom operators.",
     [("OSS/BSS Integration", "Telecom", "Integration of billing, CRM and network inventory.", ["Kafka", "Java"]),
      ("Network Automation", "Telecom", "Automation of network provisioning.", ["Python", "Kubernetes"])],
     [("ISO/IEC 27001:2022", "company", "DNV"), ("TL 9000", "company", "QuEST Forum")],
     [("BSS consolidation for a mobile operator", "Telecom", "Sweden", "2024", "Consolidated three billing stacks.", ["Kafka"], ["3 stacks to 1"])],
     {"Kafka": 15, "Java": 40, "Python": 30, "Kubernetes": 12}, []),
    ("Juniper Bay CRM", "Austin, United States", ["North America", "United Kingdom"], ["Public sector", "Healthcare", "Non-profit"], 110,
     "Salesforce and Microsoft Dynamics CRM, case management and employer engagement solutions.",
     [("Salesforce Implementation", "CRM", "Sales, service and public sector case management on Salesforce.", ["Salesforce"]),
      ("Dynamics CRM", "CRM", "Customer and case management on Dynamics 365.", ["Microsoft Dynamics"]),
      ("CRM Managed Service", "Managed services", "Support, hosting and enhancement of CRM platforms.", ["Salesforce", "Microsoft Dynamics"])],
     [("SOC 2 Type II", "company", "Independent auditor"), ("Salesforce Summit Partner", "partner", "Salesforce")],
     [("Employability case management for a workforce board", "Public sector", "United States", "2025", "Case management and employer relationship management for 12 agencies.", ["Salesforce"], ["12 agencies", "One shared client record"])],
     {"Salesforce": 50, "Microsoft Dynamics": 20, "JavaScript/TypeScript": 15}, []),
    ("Ember Rail Systems", "Lyon, France", ["Europe", "Middle East & North Africa"], ["Transportation"], 190,
     "Rail and transit operations software: scheduling, passenger information and fleet telematics.",
     [("Passenger Information Systems", "Transport", "On-board and station passenger information, displays and audio announcements.", []),
      ("Fleet Telematics", "Transport", "Vehicle telematics, CCTV and tachograph integration.", ["Kafka"]),
      ("Timetable & Scheduling", "Transport", "Scheduling and rostering software.", ["Java"])],
     [("ISO 9001:2015", "company", "AFNOR"), ("ISO/IEC 27001:2022", "company", "AFNOR")],
     [("On-board displays for a tram network", "Transportation", "France", "2024", "Supplied and integrated displays and announcements on 180 trams.", [], ["180 vehicles"])],
     {"Java": 35, "Kafka": 8, "Linux": 20}, []),
    ("Oakridge IT Services", "Johannesburg, South Africa", ["Sub-Saharan Africa"], ["Mining", "Banking", "Public sector"], 350,
     "IT infrastructure, end-user services and managed service desk.",
     [("Managed Service Desk", "Managed services", "24x7 service desk and end-user support.", ["ServiceNow", "ITIL"]),
      ("Infrastructure Services", "Infrastructure", "Data centre, network and hybrid cloud operations.", ["VMware", "Microsoft Azure", "Windows Server"])],
     [("ISO/IEC 20000-1", "company", "SABS"), ("ISO/IEC 27001:2022", "company", "SABS")],
     [("Service desk for a mining group", "Mining", "South Africa", "2024", "Service desk for 18,000 users across 9 sites.", ["ServiceNow"], ["18,000 users", "92% first-contact resolution"])],
     {"ServiceNow": 20, "VMware": 30, "Microsoft Azure": 25, "Windows Server": 40, "ITIL": 35}, []),
    ("Andes Digital Partners", "Bogotá, Colombia", ["Latin America & Caribbean", "North America"], ["Banking", "Retail", "Government"], 170,
     "Nearshore software development and digital transformation.",
     [("Custom Software Development", "Engineering", "Agile delivery of web platforms and APIs.", [".NET", "React", "Microsoft Azure"]),
      ("API & Integration", "Integration", "API development and integration.", ["REST APIs", "Azure Integration Services"])],
     [("ISO 9001:2015", "company", "ICONTEC"), ("Microsoft Solutions Partner", "partner", "Microsoft")],
     [("Digital onboarding for a bank", "Banking", "Colombia", "2025", "Built digital account opening with ID verification.", [".NET", "React"], ["Onboarding in 8 minutes"])],
     {".NET": 50, "React": 40, "Microsoft Azure": 30, "Azure Integration Services": 10}, []),
    ("Bluefin Maritime Tech", "Singapore", ["East Asia & Pacific", "Middle East & North Africa"], ["Logistics", "Transportation"], 70,
     "Port community systems, logistics tracking and IoT for ports and shipping.",
     [("Port Community Systems", "Logistics", "Platforms connecting terminals, carriers and customs.", ["Kafka", "Java"]),
      ("IoT Tracking", "Logistics", "Container and vehicle tracking with IoT sensors.", ["Kafka", "AWS"])],
     [("ISO/IEC 27001:2022", "company", "SGS")],
     [("Port community platform", "Logistics", "Singapore", "2024", "Connected 60 port stakeholders to one data exchange.", ["Kafka"], ["60 stakeholders"])],
     {"Kafka": 12, "Java": 25, "AWS": 15}, []),
    ("Clearwater Document Systems", "Dublin, Ireland", ["Europe", "United Kingdom"], ["Public sector", "Legal", "Insurance"], 55,
     "Document and records management, e-signature and archive digitisation.",
     [("Records Management", "Content", "Electronic records management and retention.", []),
      ("Scanning & Digitisation", "Content", "Archive digitisation with OCR.", [])],
     [("ISO 15489-aligned practice", "company", "Self-declared"), ("ISO/IEC 27001:2022", "company", "NSAI")],
     [("Archive digitisation for a county council", "Public sector", "Ireland", "2024", "Digitised 2 million pages.", [], ["2 million pages"])],
     {"SQL Server": 6, ".NET": 10}, []),
    ("Granite Peak AI Labs", "Toronto, Canada", ["North America", "Europe"], ["Healthcare", "Insurance", "Public sector"], 45,
     "Applied AI: document understanding, generative AI assistants and model risk management.",
     [("Generative AI Assistants", "AI", "Retrieval-augmented assistants on enterprise content.", ["Generative AI", "Python"]),
      ("Document AI", "AI", "Classification and extraction from forms and claims.", ["Machine Learning", "Python"])],
     [("SOC 2 Type II", "company", "Independent auditor")],
     [("Claims document triage for an insurer", "Insurance", "Canada", "2025", "Automated triage of incoming claims documents.", ["Machine Learning"], ["70% auto-classified"])],
     {"Python": 30, "Machine Learning": 25, "Generative AI": 15}, []),
    ("Riverstone Network Services", "Riyadh, Saudi Arabia", ["Middle East & North Africa"], ["Government", "Energy & utilities"], 240,
     "Networks, data centres and secure communications.",
     [("Enterprise Networks", "Infrastructure", "LAN, WAN, SD-WAN and Wi-Fi.", []),
      ("Data Centre Build", "Infrastructure", "Tier III data centre design and build.", ["VMware"])],
     [("ISO/IEC 27001:2022", "company", "SGS"), ("ISO 9001:2015", "company", "SGS")],
     [("Ministry WAN refresh", "Government", "Saudi Arabia", "2024", "Upgraded the WAN across 220 sites.", [], ["220 sites"])],
     {"VMware": 20, "Linux": 25}, []),
    ("Willow Analytics for Health", "Leeds, United Kingdom", ["United Kingdom"], ["Healthcare"], 40,
     "Population health analytics and NHS data platforms.",
     [("Health Data Platforms", "Data", "Trusted research environments and health data platforms.", ["Microsoft Azure", "Databricks"]),
      ("Population Health Analytics", "Data", "Risk stratification and dashboards.", ["Power BI", "Python"])],
     [("ISO/IEC 27001:2022", "company", "BSI"), ("Cyber Essentials Plus", "company", "IASME")],
     [("Population health dashboards for an integrated care board", "Healthcare", "United Kingdom", "2025", "Dashboards for 1.5 million patients.", ["Power BI"], ["1.5 million patients covered"])],
     {"Microsoft Azure": 12, "Databricks": 8, "Power BI": 15, "Python": 15}, []),
    ("Coral Reef Hospitality Tech", "Bali, Indonesia", ["East Asia & Pacific"], ["Hospitality", "Retail"], 50,
     "Booking, loyalty and point-of-sale integrations for hotels and resorts.",
     [("Booking & Loyalty Platforms", "Digital", "Reservation and loyalty systems.", ["React", "Node.js"]),
      ("POS Integration", "Integration", "Integration of point-of-sale and property systems.", ["REST APIs"])],
     [("PCI DSS v4.0 SAQ D (merchant)", "company", "Self-assessed")],
     [("Loyalty app for a resort group", "Hospitality", "Indonesia", "2024", "Loyalty app for 14 resorts.", ["React"], ["14 resorts"])],
     {"React": 12, "JavaScript/TypeScript": 15}, []),
    ("Atlas Programme Partners", "Nairobi, Kenya", ["Sub-Saharan Africa", "Middle East & North Africa", "South Asia"], ["Development finance", "Public sector", "Government"], 65,
     "Programme management, PMO and monitoring and evaluation for donor-funded projects.",
     [("Programme Management Office", "Advisory", "PMO set-up and delivery assurance for donor-funded programmes.", ["Agile/Scrum"]),
      ("Monitoring & Evaluation", "Advisory", "M&E frameworks and digital reporting.", ["Power BI"])],
     [("ISO 9001:2015", "company", "Bureau Veritas")],
     [("PMO for a digital acceleration project", "Public sector", "Republic of the Congo", "2025", "Runs the PMO for a World Bank-financed digital programme.", [], ["7 delivery units supported"])],
     {"Power BI": 6, "Agile/Scrum": 20}, []),
]


def _slug(name: str) -> str:
    return "demo-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50]


def ensure(force: bool = False) -> int:
    """Create the demo suppliers that don't exist yet. Returns how many were created."""
    if os.getenv("DEMO_VENDORS", "true").lower() in ("0", "false", "no", "off") and not force:
        return 0
    from ..db import SessionLocal
    from ..models import Accelerator, CaseStudy, Capability, Certification, Employee, Tenant, User
    from ..security import hash_password
    import secrets
    db = SessionLocal()
    made = 0
    try:
        for (name, hq, regions, industries, headcount, about, caps, certs, cases, skills, products) in V:
            slug = _slug(name)
            if db.scalar(select(Tenant).where(Tenant.slug == slug)):
                continue
            t = Tenant(name=name, slug=slug, industry="IT services", headquarters=hq, headcount=headcount, about=DEMO_NOTE + about,
                       kind="vendor", onboarding={}, settings={"demo": True, "network": {"listed": True, "regions": regions, "industries": industries,
                                                                                          "summary": DEMO_NOTE + about}})
            db.add(t)
            db.flush()
            db.add(User(tenant_id=t.id, email=f"{slug}@demo.invalid", name="Demo admin", role="admin",
                        password_hash=hash_password(secrets.token_urlsafe(32)), is_active=False))  # nobody can sign in
            for cname, line, desc, techs in caps:
                db.add(Capability(tenant_id=t.id, name=cname, service_line=line, description=desc, technologies=techs, industries=industries))
            for cname, kind, issuer in certs:
                db.add(Certification(tenant_id=t.id, name=cname, kind=kind, issuer=issuer))
            for title, ind, region, year, summary, techs, outcomes in cases:
                db.add(CaseStudy(tenant_id=t.id, title=title, client="(fictional client)", industry=ind, region=region, year=year,
                                 summary=summary, technologies=techs, outcomes=outcomes))
            for pname, desc, techs, saving in products:
                db.add(Accelerator(tenant_id=t.id, name=pname, description=desc, technologies=techs, effort_saving_pct=saving))
            # people with the stated skill depth (anonymous codes, used only as head-counts)
            n_people = max(skills.values() or [1])
            people = [{"skills": []} for _ in range(n_people)]
            for tech, count in skills.items():
                for i in range(count):
                    people[i]["skills"].append({"name": tech, "level": 4 if i % 3 == 0 else 3})
            prefix = "".join(w[0] for w in name.split()[:3]).upper()
            for i, p in enumerate(people, start=1):
                db.add(Employee(tenant_id=t.id, code=f"{prefix}-{i:03d}", role="Engineer", level="Senior" if i % 4 == 0 else "Mid",
                                years=3 + i % 9, location=hq.split(",")[-1].strip(), skills=p["skills"], availability=60))
            made += 1
        db.commit()
    except Exception as e:
        db.rollback()
        log.warning("Demo suppliers could not be created: %s", e)
    finally:
        db.close()
    if made:
        log.info("Created %d fictional demo suppliers.", made)
    return made
