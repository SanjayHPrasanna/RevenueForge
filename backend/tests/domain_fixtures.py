"""Fixtures for the five-domain IT acceptance pack (qa_domains.py).

Five RFPs from different IT domains (software, cybersecurity, cloud migration, networking with a 24x7 NOC, data platform
with managed operations), each with the facts a correct pipeline must find, and one supplier library: an IT services firm
strong in healthcare apps and integration, with a small honest set of security, network, cloud and data people. All names
are fictional. The library also holds approved answers from earlier healthcare deals, to prove they are not pasted into
unrelated bids.
"""
from __future__ import annotations

import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures", "domains")


# --------------------------------------------------------------------------- RFP builder (Word)
def _docx(title: str, client: str, facts: list[tuple[str, str]], background: str, reqs: list[tuple[str, str, str]],
          eligibility: list[tuple[str, str]], evaluation: list[tuple[str, str]] | str) -> bytes:
    from docx import Document
    d = Document()
    d.add_heading("Request for Proposal", 1)
    d.add_paragraph(title).style = d.styles["Title"]
    d.add_paragraph(client)
    d.add_heading("1. Key facts", 1)
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Item", "Detail"
    for k, v in facts:
        r = t.add_row().cells
        r[0].text, r[1].text = k, v
    d.add_heading("2. Background", 1)
    d.add_paragraph(background)
    d.add_heading("3. Scope and requirements", 1)
    t = d.add_table(rows=1, cols=3)
    for i, h in enumerate(("ID", "Requirement", "Priority")):
        t.rows[0].cells[i].text = h
    for rid, text, prio in reqs:
        r = t.add_row().cells
        r[0].text, r[1].text, r[2].text = rid, text, prio
    d.add_heading("4. Eligibility", 1)
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "ID", "Condition"
    for rid, text in eligibility:
        r = t.add_row().cells
        r[0].text, r[1].text = rid, text
    d.add_heading("5. Evaluation", 1)
    if isinstance(evaluation, str):
        d.add_paragraph(evaluation)
    else:
        t = d.add_table(rows=1, cols=2)
        t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Criterion", "Weight"
        for k, v in evaluation:
            r = t.add_row().cells
            r[0].text, r[1].text = k, v
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------- the five RFPs and what must be found
DOMAINS = {
    "software": {
        "file": "software_portal.docx",
        "build": lambda: _docx(
            "Citizen Grievance Portal and Mobile App Development", "Northwind Municipal Corporation",
            [("RFP reference", "NMC/IT/2026/077"), ("Bid submission deadline", "15 January 2027"),
             ("Contract period", "9 months development followed by 12 months of warranty support"),
             ("Estimated contract value", "USD 1.2 – 1.5 million"), ("Hosting", "The Corporation provides its AWS account")],
            "Northwind Municipal Corporation serves 2.1 million residents and wants citizens to raise and track grievances online and on mobile.",
            [("SW-01", "The bidder shall build a responsive citizen portal in React with a Node.js backend and PostgreSQL database.", "Mandatory"),
             ("SW-02", "The bidder shall deliver Android and iOS apps built with Flutter.", "Mandatory"),
             ("SW-03", "Citizen sign-in shall use Keycloak with OTP-based login.", "Mandatory"),
             ("SW-04", "The application shall run on Amazon EKS in the Corporation's AWS account, deployed through CI/CD pipelines.", "Mandatory"),
             ("SW-05", "The portal shall meet WCAG 2.1 AA and OWASP ASVS Level 2.", "Mandatory"),
             ("SW-06", "Code quality shall be tracked in SonarQube with no critical issues at release.", "Desirable"),
             ("SW-07", "The platform shall support 5,000 concurrent users with page loads under 2 seconds.", "Mandatory"),
             ("SW-08", "During warranty the bidder shall fix defects with P1 resolution within 8 business hours.", "Mandatory")],
            [("EL-01", "Bidders must hold ISO 9001 certification."),
             ("EL-02", "Bidders must have delivered at least two citizen- or customer-facing web portals in the last five years.")],
            [("Technical solution", "70%"), ("Commercial bid", "30%")]),
        "expect": {"due": "15 January 2027", "budget_high": 1_500_000, "currency": "USD", "weights": [70, 30],
                   "build_months": 9, "run_months": 12, "transition_months": 0,
                   "techs": ["React", "Node.js", "PostgreSQL", "Flutter", "Keycloak", "Amazon EKS", "SonarQube"],
                   "standards": ["WCAG 2.1 AA", "OWASP ASVS"],
                   "gates_fail": [], "verdict_ok": {"Bid", "Bid with mitigations", "Bid with partners", "Qualify carefully"},
                   "role_families": [r"(software|frontend|backend|full[- ]?stack|developer|engineer)", r"mobile|flutter", r"qa|test"],
                   "licences": False, "partner": False},
    },
    "cybersecurity": {
        "file": "cyber_soc_iam.pdf",
        "build": None,
        "expect": {"due": "22 December 2026", "budget_high": 65_000_000, "currency": "INR", "weights": [45, 25, 30],
                   "build_months": 0, "run_months": 36, "transition_months": 3,
                   "techs": ["Microsoft Sentinel", "CrowdStrike Falcon", "Microsoft Entra ID", "CyberArk", "Active Directory"],
                   "standards": ["MITRE ATT&CK", "OWASP Top 10", "ISO/IEC 27001", "CISSP", "OSCP"],
                   "gates_fail": ["CMP-02", "EL-01"], "not_held": ["CERT-In empanelled", "CISSP", "OSCP", "SOC 2"], "verdict_ok": {"No bid", "Bid in a consortium"},
                   "role_families": [r"analyst|soc", r"identity|iam|security engineer", r"lead|manager"],
                   "licences": False, "partner": True},
    },
    "cloud": {
        "file": "cloud_migration.docx",
        "build": lambda: _docx(
            "Data Centre Exit and Migration to Microsoft Azure with Managed Cloud Operations", "Eastbay Housing Finance Ltd",
            [("RFP reference", "EHF/CLD/2026/12"), ("Bid submission deadline", "30 January 2027"),
             ("Contract period", "10 months of migration followed by 24 months of managed cloud operations"),
             ("Estimated contract value", "USD 2.0 – 2.6 million"), ("Cloud consumption", "Azure consumption is paid directly by Eastbay")],
            "Eastbay runs 220 virtual machines and 45 applications in a leased data centre whose lease ends in December 2027.",
            [("CL-01", "The bidder shall migrate 220 virtual machines and 45 applications to Microsoft Azure using Azure Migrate.", "Mandatory"),
             ("CL-02", "The bidder shall build an Azure landing zone with Terraform following the Cloud Adoption Framework.", "Mandatory"),
             ("CL-03", "Disaster recovery shall use Azure Site Recovery with an RPO of 30 minutes.", "Mandatory"),
             ("CL-04", "Cloud security posture shall be monitored with Microsoft Defender for Cloud.", "Mandatory"),
             ("CL-05", "After migration the bidder shall operate the platform 8x5 with incident management in ServiceNow.", "Mandatory"),
             ("CL-06", "The bidder shall provide monthly FinOps reports with cost optimisation recommendations.", "Desirable")],
            [("EL-01", "Bidders must be a Microsoft Solutions Partner for Infrastructure (Azure)."),
             ("EL-02", "Bidders must hold ISO/IEC 27001 certification.")],
            "Proposals will be evaluated on technical merit (50%), delivery approach and team (20%) and price (30%)."),
        "expect": {"due": "30 January 2027", "budget_high": 2_600_000, "currency": "USD", "weights": [50, 20, 30],
                   "build_months": 10, "run_months": 24, "transition_months": 0,
                   "techs": ["Microsoft Azure", "Azure Migrate", "Terraform", "Azure Site Recovery", "Microsoft Defender for Cloud", "ServiceNow"],
                   "standards": ["ISO/IEC 27001"],
                   "gates_fail": [], "verdict_ok": {"Bid", "Bid with mitigations", "Bid with partners", "Qualify carefully"},
                   "role_families": [r"cloud|migration|platform", r"architect", r"ops|sre|support|devops"],
                   "licences": False, "partner": False},
    },
    "network": {
        "file": "network_sdwan.docx",
        "build": lambda: _docx(
            "SD-WAN and Campus Network Refresh with 24x7 Network Operations Centre", "Rivermark Business Parks plc",
            [("RFP reference", "RBP/NET/2026/03"), ("Bid submission deadline", "12 February 2027"),
             ("Contract period", "6 months rollout followed by 48 months of managed network services"),
             ("Estimated contract value", "GBP 2.4 – 2.8 million"), ("Sites", "85 sites across the UK")],
            "Rivermark operates 85 business parks connected by ageing MPLS links and wants SD-WAN, new campus switching and a 24x7 NOC.",
            [("NW-01", "The bidder shall supply and install Fortinet FortiGate SD-WAN appliances at 85 sites.", "Mandatory"),
             ("NW-02", "The bidder shall replace 1,200 access switches with FortiSwitch and configure 802.1X network access control.", "Mandatory"),
             ("NW-03", "Routing shall use BGP between sites and OSPF within campuses.", "Mandatory"),
             ("NW-04", "The bidder shall run a 24x7 Network Operations Centre with P1 response within 15 minutes.", "Mandatory"),
             ("NW-05", "Network monitoring shall use SolarWinds with NetFlow analysis.", "Desirable"),
             ("NW-06", "Field engineers shall attend site faults within 4 hours.", "Mandatory")],
            [("EL-01", "Bidders must hold Fortinet Expert Partner status."),
             ("EL-02", "Bidders must hold Cyber Essentials Plus certification.")],
            [("Technical solution", "40%"), ("Price", "40%"), ("Social value", "20%")]),
        "expect": {"due": "12 February 2027", "budget_high": 2_800_000, "currency": "GBP", "weights": [40, 40, 20],
                   "build_months": 6, "run_months": 48, "transition_months": 0,
                   "techs": ["Fortinet FortiGate", "FortiSwitch", "SD-WAN", "BGP", "OSPF", "SolarWinds", "NetFlow"],
                   "standards": ["802.1X", "Cyber Essentials Plus"],
                   "gates_fail": ["EL-01", "EL-02"], "not_held": ["Fortinet Expert Partner", "Cyber Essentials Plus"], "verdict_ok": {"No bid", "Bid in a consortium"},
                   "role_families": [r"network", r"noc|operations|analyst", r"field"],
                   "licences": True, "partner": True},
    },
    "data": {
        "file": "data_platform.docx",
        "build": lambda: _docx(
            "Enterprise Data Platform on Snowflake with Managed Data Operations", "Halcyon Retail Group",
            [("RFP reference", "HRG/DATA/2026/21"), ("Bid submission deadline", "5 February 2027"),
             ("Contract period", "8 months implementation followed by 12 months of managed data operations"),
             ("Estimated contract value", "EUR 900,000 – 1,100,000"), ("Licences", "Snowflake credits are procured by Halcyon")],
            "Halcyon runs 410 stores and wants one governed data platform for sales, stock and loyalty analytics.",
            [("DP-01", "The bidder shall ingest data from 40 source systems into Snowflake using Fivetran.", "Mandatory"),
             ("DP-02", "Fivetran licences for the contract term shall be supplied by the bidder.", "Mandatory"),
             ("DP-03", "Transformations shall be built in dbt and orchestrated with Apache Airflow.", "Mandatory"),
             ("DP-04", "Data quality checks shall use Great Expectations with alerts on failure.", "Mandatory"),
             ("DP-05", "The bidder shall deliver 25 Power BI reports for sales, stock and loyalty.", "Mandatory"),
             ("DP-06", "Managed data operations shall run business hours with pipeline failures fixed within 4 hours.", "Mandatory")],
            [("EL-01", "Bidders must be a Snowflake Select Partner or higher."),
             ("EL-02", "Bidders must have delivered at least one cloud data platform in the last three years.")],
            [("Technical approach", "60%"), ("Commercial", "40%")]),
        "expect": {"due": "5 February 2027", "budget_high": 1_100_000, "currency": "EUR", "weights": [60, 40],
                   "build_months": 8, "run_months": 12, "transition_months": 0,
                   "techs": ["Snowflake", "Fivetran", "dbt", "Apache Airflow", "Great Expectations", "Power BI"],
                   "standards": [],
                   "gates_fail": ["EL-01"], "not_held": ["Snowflake Select Partner"], "verdict_ok": {"No bid", "Bid in a consortium"},
                   "role_families": [r"data engineer|analytics engineer", r"bi|report|power bi|analyst", r"architect"],
                   "licences": True, "partner": True},
    },
}


def rfp_bytes(domain: str) -> tuple[str, bytes]:
    spec = DOMAINS[domain]
    if spec["build"] is None:
        with open(os.path.join(FIX, spec["file"]), "rb") as f:
            return spec["file"], f.read()
    return spec["file"], spec["build"]()


# --------------------------------------------------------------------------- the supplier library
def _sk(*names, level=4):
    return [{"name": n, "level": level} for n in names]


CAPABILITIES = [
    {"name": "API & Integration Engineering", "description": "REST APIs, event streaming and integration platforms.",
     "technologies": ["REST APIs", "OAuth 2.0", "OpenID Connect", "Azure API Management", "Apache Kafka", "MuleSoft", "Python FastAPI", "Java Spring Boot"],
     "industries": ["Healthcare", "Retail & Distribution"]},
    {"name": "Cloud-native Application Development", "description": "Web applications and APIs on containers.",
     "technologies": ["Python", "FastAPI", "Java", "Spring Boot", "React", "JavaScript/TypeScript", "Node.js", "PostgreSQL", "Docker", "Azure Kubernetes Service (AKS)", "Microsoft Azure"],
     "industries": ["Healthcare", "Public Sector"]},
    {"name": "Patient & Customer Portals", "description": "Accessible self-service portals.",
     "technologies": ["React", "Next.js", "WCAG 2.1 AA", "Figma"], "industries": ["Healthcare"]},
    {"name": "Mobile App Development", "description": "Cross-platform mobile apps.",
     "technologies": ["Flutter", "Dart", "Firebase Cloud Messaging", "iOS", "Android"], "industries": ["Healthcare"]},
    {"name": "Data Engineering & Analytics", "description": "Data platforms and reporting.",
     "technologies": ["Azure Data Factory", "Azure Databricks", "dbt", "Snowflake", "SQL", "Power BI"], "industries": ["Insurance", "Retail & Distribution"]},
    {"name": "Healthcare Interoperability", "description": "HL7 and FHIR integration for hospitals.",
     "technologies": ["HL7 FHIR R4", "HL7 v2"], "industries": ["Healthcare"]},
    {"name": "Cloud Operations & DevOps", "description": "Azure operations, CI/CD and DR.",
     "technologies": ["Microsoft Azure", "CI/CD", "Terraform", "Kubernetes", "Azure Monitor", "Azure Site Recovery", "Azure Migrate"],
     "industries": ["BFSI", "Logistics"]},
    {"name": "Quality Engineering", "description": "Functional, performance and accessibility testing.",
     "technologies": ["Playwright", "Selenium", "JMeter", "axe accessibility testing"], "industries": []},
    {"name": "Application Managed Services", "description": "L2/L3 application support under SLAs.",
     "technologies": ["ServiceNow", "Azure Monitor", "ITIL"], "industries": ["Healthcare"]},
]

PEOPLE = [
    {"code": "KD001", "role": "Engagement Manager", "years": 16, "availability": 50, "skills": _sk("Program management", "ITIL", "Stakeholder management"), "certifications": ["PMP"]},
    {"code": "KD002", "role": "Solution Architect", "years": 12, "availability": 60, "skills": _sk("Microsoft Azure", "Microservices", "OAuth 2.0", "Apache Kafka", "Kubernetes", "Security architecture"), "certifications": ["Microsoft Certified: Azure Solutions Architect Expert"]},
    {"code": "KD003", "role": "Senior Software Engineer", "years": 8, "availability": 100, "skills": _sk("Python", "FastAPI", "PostgreSQL", "Apache Kafka", "Docker", "REST APIs"), "certifications": []},
    {"code": "KD004", "role": "Software Engineer", "years": 5, "availability": 100, "skills": _sk("Java", "Spring Boot", "Node.js", "REST APIs", "SQL Server"), "certifications": []},
    {"code": "KD005", "role": "Senior Frontend Engineer", "years": 7, "availability": 80, "skills": _sk("React", "JavaScript/TypeScript", "Next.js", "WCAG 2.1 AA", "Figma"), "certifications": []},
    {"code": "KD006", "role": "Mobile Engineer", "years": 4, "availability": 100, "skills": _sk("Flutter", "Dart", "Android", "iOS release"), "certifications": []},
    {"code": "KD007", "role": "Data Engineer", "years": 7, "availability": 70, "skills": _sk("Azure Data Factory", "SQL", "Power BI", "dbt", "Snowflake"), "certifications": ["Microsoft Certified: Azure Data Engineer Associate (DP-203)"]},
    {"code": "KD008", "role": "DevOps / SRE Engineer", "years": 9, "availability": 50, "skills": _sk("CI/CD", "Terraform", "Kubernetes", "Azure Monitor", "Azure Site Recovery", "Linux"), "certifications": ["Certified Kubernetes Administrator (CKA)"]},
    {"code": "KD009", "role": "QA Lead", "years": 8, "availability": 100, "skills": _sk("Playwright", "Selenium", "JMeter", "Accessibility testing"), "certifications": ["ISTQB Advanced Test Manager"]},
    {"code": "KD010", "role": "ML Engineer", "years": 4, "availability": 100, "skills": _sk("Python", "scikit-learn", "Azure OpenAI", "LangChain"), "certifications": []},
    # the small, honest additions: one each for security, network, cloud and data
    {"code": "KD011", "role": "Security Analyst", "years": 5, "availability": 100, "skills": _sk("Microsoft Sentinel", "KQL", "Incident response", "Threat hunting"), "certifications": ["CompTIA Security+", "Certified Ethical Hacker (CEH)"]},
    {"code": "KD012", "role": "Network Engineer", "years": 8, "availability": 80, "skills": _sk("Cisco IOS", "BGP", "OSPF", "SD-WAN", "Fortinet FortiGate"), "certifications": ["Cisco CCNP Enterprise"]},
    {"code": "KD013", "role": "Cloud Engineer", "years": 6, "availability": 100, "skills": _sk("Microsoft Azure", "Azure Migrate", "Terraform", "Azure Landing Zone"), "certifications": ["Microsoft Certified: Azure Administrator Associate (AZ-104)"]},
    {"code": "KD014", "role": "Data Engineer", "years": 5, "availability": 60, "skills": _sk("Snowflake", "dbt", "Apache Airflow", "Python"), "certifications": ["SnowPro Core"]},
]

CERTIFICATIONS = [
    {"name": "ISO 9001:2015 Quality Management", "kind": "company", "issuer": "BSI", "valid_until": "2028-03-31"},
    {"name": "ISO/IEC 27001:2022 Information Security", "kind": "company", "issuer": "BSI", "valid_until": "2028-03-31"},
    {"name": "Microsoft Solutions Partner - Infrastructure (Azure)", "kind": "partner", "issuer": "Microsoft", "valid_until": "2027-06-30"},
]

CASE_STUDIES = [
    {"title": "Unified API layer for a multi-specialty hospital chain", "client": "Confidential hospital chain", "industry": "Healthcare", "region": "India", "year": 2024,
     "summary": "Replaced point-to-point links between the HIS, lab and billing systems with a governed API layer.", "technologies": ["Azure API Management", "Apache Kafka", "HL7 FHIR R4"], "outcomes": ["42 legacy endpoints replaced"]},
    {"title": "Patient appointment and reminders app", "client": "Confidential hospital group", "industry": "Healthcare", "region": "India", "year": 2023,
     "summary": "Patient web portal and Flutter app for booking, reports and payments.", "technologies": ["React", "Flutter", "Node.js"], "outcomes": ["120,000 downloads in year one"]},
    {"title": "Customer self-service portal for a regional lender", "client": "Confidential NBFC", "industry": "BFSI", "region": "India", "year": 2025,
     "summary": "Customer web portal with loan tracking and document upload.", "technologies": ["React", "Node.js", "PostgreSQL"], "outcomes": ["35% fewer branch visits"]},
    {"title": "Azure landing zone and migration for an NBFC", "client": "Confidential NBFC", "industry": "BFSI", "region": "India", "year": 2025,
     "summary": "Moved 140 VMs to Azure with a Terraform landing zone and Azure Site Recovery.", "technologies": ["Microsoft Azure", "Azure Migrate", "Terraform", "Azure Site Recovery"], "outcomes": ["Data centre exited in 9 months"]},
    {"title": "Snowflake analytics platform for a regional retailer", "client": "Confidential retailer", "industry": "Retail & Distribution", "region": "UAE", "year": 2024,
     "summary": "Snowflake and dbt platform with Power BI reporting for 120 stores.", "technologies": ["Snowflake", "dbt", "Power BI"], "outcomes": ["Daily sales reports 6 hours earlier"]},
    {"title": "GenAI discharge-summary assistant (pilot)", "client": "Confidential teaching hospital", "industry": "Healthcare", "region": "India", "year": 2025,
     "summary": "Pilot assistant drafting discharge summaries for doctors.", "technologies": ["Azure OpenAI", "LangChain"], "outcomes": ["Drafting time down 60%"]},
]

ACCELERATORS = [
    {"name": "Azure Landing Zone Blueprints", "description": "Terraform modules for Azure landing zones.", "technologies": ["Terraform", "Microsoft Azure"], "effort_saving_pct": 15},
    {"name": "Healthcare KPI Dashboard Pack", "description": "Power BI dashboards for hospital KPIs.", "technologies": ["Power BI"], "effort_saving_pct": 10},
]

RATES = [{"role": r, "level": "", "location": loc, "day_rate": rate * (2.2 if loc == "Onsite" else 1), "day_cost": cost * (2.2 if loc == "Onsite" else 1), "currency": "INR"}
         for r, rate, cost in [("Engagement Manager", 42000, 24000), ("Project Manager", 32000, 18000), ("Solution Architect", 45000, 25000),
                               ("Software Engineer", 18000, 9000), ("QA Engineer", 15000, 7500), ("DevOps Engineer", 22000, 11000),
                               ("Data Engineer", 22000, 11000), ("Support Engineer", 14000, 7000)]
         for loc in ("Offshore", "Onsite")]

# Approved answers from earlier healthcare and logistics deals: realistic, but wrong for any other domain.
OLD_ANSWERS = [
    ("The bidder shall build SOAR playbooks for phishing, ransomware and account takeover using automation.",
     "We will build a data platform consolidating data from the HIS, laboratory system, and billing system, leveraging our Data Engineering & Analytics and Healthcare Interoperability capabilities."),
    ("Bidders must have operated managed services for at least three clients in the last five years.",
     "We leverage our dedicated Healthcare Interoperability capability and Healthcare KPI Dashboard Pack accelerator to deliver robust domain solutions. To fully substantiate our experience with two similar healthcare implementations in the last five years, we will add a reference project, demo, or named expert."),
    ("The bidder shall operate a 24x7 Network Operations Centre with P1 response within 15 minutes.",
     "We bring proven expertise through our Application Managed Services capability and relevant project experience. To address the thin evidence for 24x7 L1 support with a 15-minute response time, we will add a reference project, demo, or named expert to our final response."),
    ("The bidder shall hold ISO/IEC 27001 certification.",
     "We hold a current ISO/IEC 27001:2022 Information Security certification, demonstrating our ongoing commitment to robust information security management across all operations."),
    ("The bidder shall build a responsive citizen portal where customers can track the status of requests.",
     "We will deliver a responsive patient web portal for appointment booking, report download, and bill payment, leveraging our Patient & Customer Portals capability."),
    ("The bidder shall deliver 25 Power BI reports for operations with daily refresh.",
     "We will provide Power BI dashboards for bed occupancy, OPD footfall, report turnaround time, and revenue cycle, using our Healthcare KPI Dashboard Pack."),
    ("The bidder shall be a CERT-In empanelled information security auditing organisation.",
     "Kestrel Test Works is a CERT-In empanelled auditing organisation with a dedicated security assurance practice."),
]

# Words that only belong to the earlier deals' domains: none of these five RFPs uses them.
FOREIGN_TERMS = ["patient", "hospital", "HIS", "laboratory system", "discharge", "OPD", "bed occupancy", "healthcare implementations",
                 "shipment", "consignment", "appointment booking"]
INTERNAL_PHRASES = ["add a reference project", "named expert to our final response", "thin evidence", "to be hired", "to hire",
                    "knowledge library", "evidence is thin", "internal review"]
