"""Domain vocabulary used by the rules engine: requirement taxonomy, technology dictionary,
synonyms and role catalogue. Kept in one place so it can be extended without touching logic."""
from __future__ import annotations

import re

CATEGORIES = ["Functional", "Non-functional", "Compliance", "Commercial"]

# subcategory -> (category, keyword patterns). Order matters: first strong hit wins ties.
SUBCATEGORIES: dict[str, tuple[str, list[str]]] = {
    # Commercial
    "Pricing & Payment": ("Commercial", [r"\bpric(e|es|ing)\b", r"\bpayments?\b(?!\s+card)", r"\binvoice", r"\bcurrency\b", r"\bdirham|\bdinar|\baed\b|\bkwd\b|\busd\b",
                                         r"\bcost(s)?\b", r"\bfee(s)?\b", r"\brates? (for|of|shall|will|are|must)\b", r"\bboq\b", r"\bunit rate", r"\bwith ?holding tax|\bvat\b|\btax"]),
    "Bonds & Guarantees": ("Commercial", [r"\bperformance bond|\bbid bond|\btender bond", r"\bbond\b", r"\b(bank|performance|bid|tender|advance payment|parent company|financial) guarantee", r"\btender fee"]),
    "Insurance & Liability": ("Commercial", [r"\binsurance", r"\bindemn", r"\bliabilit", r"\bpenalt", r"\bliquidated damages"]),
    "Contract Terms": ("Commercial", [r"\bcontract (term|terms|duration|period)", r"\bterminat", r"\bwarrant(y|ies)", r"\bsub-?contract", r"\bjoint venture",
                                      r"\bvalidity", r"\bdraft contract", r"\bsignator", r"\bintellectual property|\bownership\b", r"\bterms and conditions"]),
    "Evaluation & Award": ("Commercial", [r"\bevaluation criteri|\bbe evaluated\b|\bevaluation of (the )?proposals?", r"\bweight(ing)?\b", r"\baward(ed)?\b",
                                          r"\b(technical|financial|commercial) (score|evaluation)", r"\bshortlist", r"\bproduct demonstration|\bdemo\b"]),
    "Submission": ("Compliance", [r"\bsubmi(t|ssion)", r"\bupload", r"\bportal\b", r"\bclosing date", r"\bdeadline", r"\bproposal must be prepared",
                                  r"\bformat\b", r"\bheadings\b", r"\bqueries\b", r"\bpassword", r"\btrade licen[cs]e", r"\bvendor profile", r"\backnowledg"]),
    # Compliance
    "Regulatory": ("Compliance", [r"\bregulat", r"\bcentral bank", r"\blaw(s)?\b", r"\blegislat", r"\bstatut", r"\bgovernment of", r"\bcbk\b"]),
    "Data Protection & Privacy": ("Compliance", [r"\bprivacy", r"\bpersonal data", r"\bdata[- ]protection", r"\bgdpr\b", r"\bpdpl\b", r"\bhipaa", r"\bconsent",
                                                 r"\bdata[- ]residency", r"\bdata locations?\b", r"\bpatient privacy", r"\bpii\b"]),
    "Standards & Certifications": ("Compliance", [r"\biso\s?\d{4,5}", r"\bcertif", r"\bsoc ?2\b", r"\bpci[- ]?dss", r"\baccredit", r"\bihe\b", r"\bnesa\b", r"\bnist\b"]),
    "Information Security Policy": ("Compliance", [r"\binformation security (policy|policies|standards|article|requirements)", r"\bsecurity governance",
                                                   r"\baudit (and|&) inspection", r"\baudit rights", r"\bconfidential"]),
    "Accessibility & Sustainability": ("Compliance", [r"\bpeople of determination", r"\baccessibility (for|of|requirements)|\bwcag", r"\bgreen (it|energy|computing|procurement)\b|\bcarbon\b|\bnet[- ]zero", r"\bsustainab", r"\boccupational health"]),
    # Non-functional
    "Availability & Continuity": ("Non-functional", [r"\bavailab", r"\bdisaster recovery|\bdr\b", r"\bfailover", r"\bbackup", r"\bbusiness continuity",
                                                     r"\brto\b|\brpo\b", r"\bhigh[- ]availability|\bclustering", r"\bresilien", r"\buptime"]),
    "Performance & Scalability": ("Non-functional", [r"\bperformance", r"\blatency", r"\bresponse time\b(?!.*(p\d|incident))", r"\b\d+\s?ms\b", r"\bthroughput",
                                                     r"\btransactions per second|\btps\b", r"\bscalab", r"\bcapacity"]),
    "Service Levels": ("Non-functional", [r"\bsla\b|\bslas\b", r"\bp[1-4]\b", r"\bresolution time", r"\bresponse time", r"\bseverity", r"\bkpi",
                                          r"\bservice level", r"\bfulfil+ment time", r"\b24\s?x\s?7"]),
    "Security": ("Non-functional", [r"\bencrypt", r"\btls\b", r"\baccess control", r"\baudit log", r"\bauthenticat", r"\bauthori[sz]", r"\biam\b",
                                    r"\bvulnerab", r"\bpenetration", r"\bsecure\b", r"\bspoof", r"\btamper", r"\bcryptograph", r"\bkey management"]),
    "Monitoring & Operations": ("Non-functional", [r"\bmonitor", r"\balert", r"\blogging\b", r"\bobservab", r"\bhealth check", r"\bdashboard",
                                                   r"\bqueue", r"\bpatch", r"\bupgrade", r"\bmaintenance"]),
    "Maintainability & Quality": ("Non-functional", [r"\bversion control", r"\brollback", r"\bblue[- ]green|\bcanary|\bzero[- ]downtime|\bno planned downtime", r"\benvironment separation|\bdev, test", r"\bdocumentation",
                                                     r"\bchange (and|&) release|\brelease management|\bconfiguration management"]),
    # Functional
    "Integration & APIs": ("Functional", [r"\bintegrat", r"\binterface", r"\bapi(s)?\b", r"\bmiddleware", r"\bhl7\b", r"\bfhir\b", r"\bmessag", r"\besb\b",
                                          r"\bevent[- ]driven", r"\bat[- ]least[- ]once|\bexactly[- ]once|\bidempoten", r"\bmllp\b", r"\bsoap\b", r"\brest(ful)?\b", r"\bmapping", r"\binteroperab", r"\bwebhook"]),
    "Fraud & Risk Analytics": ("Functional", [r"\bfraud", r"\brisk scor", r"\banomal", r"\bbehavio(u)?ral", r"\bbiometric", r"\bdevice (fingerprint|intelligence|identifier)",
                                              r"\bgeolocat", r"\bbots?\b", r"\bmule", r"\bvpns?\b|\bprox(y|ies)\b|\btor\b|\bip address|\basn\b", r"\breputation",
                                              r"\bscam|\bsocial[- ]engineer|\bcoercion", r"\bmalware|\bremote[- ]access|\bthreat", r"\baccount takeover|\bcredential stuffing", r"\bimpossible travel", r"\bkeystroke", r"\bemulator", r"\bjailbroken|\brooted"]),
    "Data & Analytics": ("Functional", [r"\bdata (platform|warehouse|lake|model|quality|governance|migration)", r"\banalytic", r"\banalytic(al)? report", 
                                        r"\bbi\b", r"\bmachine learning|\bml\b|\b(ml|ai|risk|scoring|analytic(al)?) models?\b", r"\bai\b", r"\bdashboards?\b"]),
    "Application Development": ("Functional", [r"\bdevelop", r"\bbuild\b", r"\benhancements?\b", r"\bcustomi[sz]", r"\bconfigur", r"\bworkflow", r"\bscript", r"\bsdk\b",
                                               r"\bmobile app", r"\bweb app", r"\bportal\b", r"\buser interface|\bui\b"]),
    "Testing & QA": ("Functional", [r"\btest", r"\bvalidat", r"\bquality assurance|\bqa\b", r"\buat\b", r"\bgo-live"]),
    "Transition & Knowledge Transfer": ("Functional", [r"\btransition", r"\bknowledge (transfer|sharing|acquisition)", r"\bonboarding of", r"\bincumbent",
                                                       r"\bhandover", r"\btraining"]),
    "Support & Incident Management": ("Functional", [r"\bincident", r"\bproblem management", r"\broot[- ]cause|\brca\b", r"\btroubleshoot", r"\b(production|technical|l[123]|24x7|operational|post[- ]go[- ]live) support|\bsupport (services|desk|coverage|team|model|and maintenance)",
                                                     r"\bservice desk", r"\bescalation"]),
    "Architecture & Advisory": ("Functional", [r"\barchitect", r"\bassessment", r"\broadmap", r"\bstrateg", r"\bmaturity", r"\btarget state|\bcurrent state",
                                               r"\bframework\b", r"\btogaf", r"\bgovernance\b", r"\bbest practice", r"\badvisory|\bconsult"]),
    "Project Management": ("Functional", [r"\bproject (plan|management|structure|organi[sz]ation)", r"\bwork ?plan", r"\btimeline", r"\bmilestone",
                                          r"\bpmo\b", r"\bagile|\bsprint", r"\bstakeholder", r"\bgovernance meeting|\bservice review", r"\breporting cadence",
                                          r"\boperational reporting|\bstatus report", r"\bdeliverables?\b", r"\bagreed timelines", r"\bsign(ed)?[- ]off"]),
    "Team & Experience": ("Functional", [r"\byears of experience", r"\bteam profile|\bcvs?\b|\bresumes?\b", r"\bsubject matter expert|\bsme", r"\breferences?\b",
                                         r"\bsimilar (implementation|projects?|organi[sz]ations)", r"\bcase stud", r"\bproposed staff"]),
}

_COMPILED = {k: (cat, [re.compile(p, re.I) for p in pats]) for k, (cat, pats) in SUBCATEGORIES.items()}

# Words that indicate an obligation on the bidder.
MANDATORY_RE = re.compile(r"\b(request(s|ed)? (from )?(the )?(vendors?|bidders?|tenderers?|suppliers?|proposers?)|comply with|shall|must|is required|are required|required to|mandatory|will be required|needs? to|has to|have to|is expected to|are expected to|ensure)\b", re.I)
DESIRABLE_RE = re.compile(r"\b(should|may|preferred|preferably|desirable|advantage|nice to have|optional|where (possible|applicable|available)|if (required|applicable))\b", re.I)
VENDOR_SUBJECT_RE = re.compile(r"\b(tenderers?|bidders?|proposers?|vendors?|suppliers?|contractors?|second party|service providers?|solution|system|platform|the winner|winning bidder|successful tenderer|you|your)\b", re.I)
ACTION_START_RE = re.compile(r"^(provide|support|ensure|deliver|maintain|integrate|design|develop|implement|perform|detect|identify|analy[sz]e|generate|enable|"
                             r"allow|configure|monitor|manage|prepare|submit|include|comply|demonstrate|describe|explain|state|offer|establish|"
                             r"conduct|review|define|document|participate|coordinate|troubleshoot|resolve|correlate|display|collect|distinguish|"
                             r"prevent|reduce|meet|protect|track|assess|recommend|produce|create|build|deploy|test|validate|upgrade|patch|"
                             r"compatibility|knowledge transfer|access provisioning|real-time|alerting|audit|secure|disaster|backup|version|"
                             r"adherence|unit testing|structured|environment|incident|sla-based|regular|proactive|24x7|agile|participation|"
                             r"rhapsody|hl7|json|integration|performance|identification)\b", re.I)
CLIENT_SUBJECT_RE = re.compile(r"^(the )?(company|bank|authority|client|purchaser|employer|department|committee|government)\b.*\b(reserves|may|will|shall not pay|is not|does not|has the right)\b", re.I)

SKIP_SECTION_RE = re.compile(r"(definition|table of content|contents|overview of (the )?(company|bank|organi[sz]ation|authority)|about (us|the)|"
                             r"contact (information|details)|rfi schedule|copyright|history|structure of this document|introduction|"
                             r"purpose of the rfi|address|bribes)", re.I)
INFO_ONLY_RE = re.compile(r"^(this (rfp|rfi|document|section)|the following|an overview|the (bank|authority|company) (intends|operates)|the primary objective|"
                          r"duration:|note:?$|in this proposal|all information presented)", re.I)


STRONG_COMMERCIAL_RE = re.compile(r"\b(pric(e|es|ing)|invoic\w*|payment (terms|schedule|milestones?)|paid|bonds?|insurance|indemn\w*|liabilit\w*|"
                                  r"penalt\w*|liquidated|currency|gst|vat|tax(es)?|award\w*|evaluation|contract (term|value|period)|"
                                  r"terminat\w*|warrant(y|ies)|quoted?|exclusive of|inclusive of|tender fee|rates?)\b", re.I)
TECHNICAL_RE = re.compile(r"\b(solution|system|platform|interfaces?|apis?|data|consumers?|messages?|delivery|deliver|support|enhancements?|"
                          r"releases?|monitor\w*|integrat\w*|service levels?|availability|latency|encrypt\w*|cards?)\b", re.I)

# A tender-process instruction talks about the bid itself. "Upload", "portal", "format" or "password" in a sentence about the
# system ("users shall upload documents", "return data in JSON format") is a product requirement, not a submission rule.
SUBMISSION_RE = re.compile(r"\b(submi(t|ts|tted|ssions?)|closing date|deadline|proposals?|bids?|bidders?|tenders?|tenderers?|responses?|"
                           r"respondents?|e-?tendering|clarifications?|pages?|appendi(x|ces)|trade licen[cs]e|vendor profile)\b", re.I)


def classify(text: str, section: str = "") -> tuple[str, str, float]:
    """Return (category, subcategory, confidence) using keyword evidence from text + section."""
    scores: dict[str, float] = {}
    t = text
    s = section or ""
    for sub, (cat, pats) in _COMPILED.items():
        sc = 0.0
        for p in pats:
            m = p.search(t)
            if m:
                sc += 1.0 + min(len(m.group(0)) / 25, 0.8)  # longer phrases are more specific
            if s and p.search(s):
                sc += 0.6
        if sc:
            scores[sub] = sc
    if not scores:
        return "Functional", "General Scope", 0.45
    # A requirement is only Commercial when it is about money or contract terms. A lone "fee" or "guarantee" in a
    # technical sentence ("guarantee at-least-once delivery", "within the managed service fee") is not enough.
    best_sub = max(scores, key=scores.get)
    if _COMPILED[best_sub][0] == "Commercial" and not STRONG_COMMERCIAL_RE.search(t) and TECHNICAL_RE.search(t):
        tech = {k: v for k, v in scores.items() if _COMPILED[k][0] != "Commercial"}
        if not tech:
            return "Functional", "General Scope", 0.5
        scores = tech
    if max(scores, key=scores.get) == "Submission" and not SUBMISSION_RE.search(t):
        scores = {k: v for k, v in scores.items() if k != "Submission"}
        if not scores:
            return "Functional", "General Scope", 0.5
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best, best_sc = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    conf = min(0.97, 0.55 + 0.12 * best_sc - 0.08 * second + (0.1 if best_sc - second >= 1 else 0))
    return _COMPILED[best][0], best, round(max(conf, 0.5), 2)


def priority(text: str) -> str:
    if MANDATORY_RE.search(text):
        return "Mandatory"
    if DESIRABLE_RE.search(text):
        return "Desirable"
    return "Mandatory"


# --------------------------------------------------------------------------- technologies
TECHNOLOGIES: dict[str, list[str]] = {
    # integration platforms
    "Rhapsody": ["rhapsody"], "MuleSoft": ["mulesoft", "mule esb", "anypoint"], "Boomi": ["boomi"], "TIBCO": ["tibco"],
    "Workato": ["workato"], "Apigee": ["apigee"], "Azure Integration Services": ["azure integration", "logic apps", "azure service bus"],
    "WSO2": ["wso2"], "IBM App Connect": ["ibm app connect", "ibm integration bus", "iib"], "Kafka": ["kafka"], "RabbitMQ": ["rabbitmq"],
    "Kong": ["kong gateway", "kong"], "Mirth Connect": ["mirth"], "Postman": ["postman"], "Neo4j": ["neo4j"], "Confluence": ["confluence"], "Informatica": ["informatica"], "SAP PI/PO": ["sap pi", "sap po", "sap cpi"],
    # healthcare
    "HL7 v2": ["hl7 v2", "hl7v2", "hl7 2.", "hl7"], "HL7 FHIR": ["fhir"], "IHE": ["ihe"], "DICOM": ["dicom"], "MLLP": ["mllp"],
    "EHR/EMR": ["ehr", "emr"], "HIS": ["his"], "LIS": ["lis"], "RIS": ["ris"], "PACS": ["pacs"],
    # protocols/formats
    "REST APIs": ["rest", "restful"], "SOAP": ["soap"], "JSON": ["json"], "XML": ["xml"], "GraphQL": ["graphql"], "TCP/IP": ["tcp/ip"],
    "SFTP": ["sftp"], "OAuth 2.0": ["oauth"], "OpenID Connect": ["openid", "oidc"], "SAML": ["saml"],
    # cloud/infra
    "Microsoft Azure": ["azure"], "AWS": ["aws", "amazon web services"], "Google Cloud": ["gcp", "google cloud"],
    "Kubernetes": ["kubernetes", "k8s", "aks", "eks"], "Docker": ["docker", "container"], "Terraform": ["terraform"],
    "Linux": ["linux"], "Windows Server": ["windows server"], "VMware": ["vmware"],
    # devops/observability
    "CI/CD": ["ci/cd", "devops", "jenkins", "azure devops", "github actions", "gitlab"], "Git": ["git", "version control"],
    "Splunk": ["splunk"], "Dynatrace": ["dynatrace"], "Prometheus/Grafana": ["prometheus", "grafana"], "ELK": ["elk", "elasticsearch", "kibana"],
    "ServiceNow": ["servicenow"], "Jira": ["jira"],
    # data/ai
    "SQL Server": ["sql server", "mssql"], "Oracle DB": ["oracle database", "oracle db"], "PostgreSQL": ["postgres"], "MongoDB": ["mongodb"],
    "Snowflake": ["snowflake"], "Databricks": ["databricks"], "Power BI": ["power bi"], "Tableau": ["tableau"],
    "Machine Learning": ["machine learning", "ml model", "ml models"], "Generative AI": ["generative ai", "genai", "llm", "large language model"],
    "Graph Analytics": ["graph analytics", "link analysis", "fraud ring", "network analysis"], "Denodo": ["denodo"], "Reltio": ["reltio"],
    # security/fraud
    "Behavioral Biometrics": ["behavioral biometric", "behavioural biometric", "keystroke dynamics", "touchscreen behavior"],
    "Device Fingerprinting": ["device fingerprint", "device identifier", "device binding"], "Geolocation Intelligence": ["geolocation", "geofenc", "impossible travel"],
    "Bot Detection": ["bot detection", "bot activity", "credential stuffing"], "Mobile App Security SDK": ["sdk", "jailbroken", "rooted", "emulator", "hooking"],
    "SIEM": ["siem"], "IAM": ["iam", "identity and access"], "PKI/TLS": ["tls", "certificates", "pki"], "MFA": ["mfa", "multi-factor", "step-up"],
    "Fraud Monitoring Platform": ["fraud-monitoring", "fraud monitoring", "enterprise fraud"],
    # apps / languages
    "Java": ["java"], ".NET": [".net", "c#"], "Python": ["python"], "JavaScript/TypeScript": ["javascript", "typescript", "node.js"],
    "React": ["react"], "Angular": ["angular"], "iOS": ["ios"], "Android": ["android"], "Salesforce": ["salesforce"], "SAP": ["sap"],
    "Microsoft Dynamics": ["dynamics 365"], "Glean": ["glean"],
    # architecture
    "TOGAF": ["togaf"], "Enterprise Architecture": ["enterprise architecture"], "ArchiMate": ["archimate"], "ITIL": ["itil"], "Agile/Scrum": ["agile", "scrum", "sprint"],
}

_TECH_RES = {name: [re.compile(r"(?<![a-z0-9])" + re.escape(a) + r"(?![a-z0-9])", re.I) for a in aliases] for name, aliases in TECHNOLOGIES.items()}
# Short acronyms that need case-sensitive matching to avoid false positives.
_CASE_SENSITIVE = {"HIS", "LIS", "RIS", "IAM", "SAP", "Git", "iOS"}


def find_technologies(text: str, extra: list[str] | None = None) -> list[str]:
    found = []
    for name, res in _TECH_RES.items():
        if name in _CASE_SENSITIVE:
            if any(re.search(r"(?<![A-Za-z])" + re.escape(a.upper() if name != "iOS" else "iOS") + r"(?![A-Za-z])", text) for a in TECHNOLOGIES[name]):
                found.append(name)
        elif any(r.search(text) for r in res):
            found.append(name)
    for e in extra or []:
        if e and e not in found and re.search(r"(?<![a-z0-9])" + re.escape(e.lower()) + r"(?![a-z0-9])", text.lower()):
            found.append(e)
    # collapse HL7 v2 when FHIR only
    if "HL7 v2" in found and "HL7 FHIR" in found and not re.search(r"hl7 ?v?2", text, re.I) and text.lower().count("hl7") <= text.lower().count("fhir"):
        found.remove("HL7 v2")
    return found


def canonical_tech(name: str) -> str:
    n = name.strip().lower()
    for canon, aliases in TECHNOLOGIES.items():
        if n == canon.lower() or n in aliases:
            return canon
    return name.strip()


# --------------------------------------------------------------------------- synonyms for matching
SYNONYMS = {
    "sso": "single sign on authentication identity", "dr": "disaster recovery continuity", "ha": "high availability failover",
    "apim": "api management gateway", "esb": "enterprise service bus integration middleware", "ehr": "electronic health record clinical",
    "emr": "electronic medical record clinical", "rca": "root cause analysis incident problem", "sla": "service level agreement support",
    "kt": "knowledge transfer transition", "ml": "machine learning model", "ai": "artificial intelligence", "iam": "identity access management",
    "mfa": "multi factor authentication", "siem": "security monitoring", "fhir": "hl7 healthcare interoperability api",
    "hl7": "healthcare messaging interoperability integration", "uat": "user acceptance testing", "pmo": "project management office",
    "ea": "enterprise architecture", "bfsi": "banking financial services insurance", "kyc": "know your customer",
    "biometric": "biometrics behavioral authentication fraud", "fingerprint": "device fingerprinting identification",
    "interface": "integration interfaces api", "middleware": "integration platform esb", "managed": "managed services support operations",
    "monitoring": "observability monitoring alerting operations", "fraud": "fraud risk detection analytics",
}


def expand(text: str) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())
    extra = [SYNONYMS[w] for w in words if w in SYNONYMS]
    return text + " " + " ".join(extra)


# --------------------------------------------------------------------------- roles
ROLE_KEYWORDS = {
    "Engagement Manager": ["engagement manager", "delivery manager", "account manager", "service delivery manager"],
    "Project Manager": ["project manager", "program manager", "pmo", "scrum master"],
    "Solution Architect": ["solution architect", "technical architect", "integration architect", "enterprise architect", "architect"],
    "Integration Engineer": ["integration engineer", "integration developer", "middleware", "esb developer", "api developer", "mulesoft", "boomi", "tibco", "rhapsody"],
    "Software Engineer": ["software engineer", "developer", "full stack", "backend", "frontend", "java developer", ".net developer"],
    "Data Engineer": ["data engineer", "etl", "data analyst", "bi developer"],
    "Data Scientist": ["data scientist", "ml engineer", "ai engineer", "machine learning"],
    "QA Engineer": ["qa", "test engineer", "tester", "quality"],
    "DevOps Engineer": ["devops", "cloud engineer", "site reliability", "sre", "platform engineer"],
    "Support Engineer": ["support engineer", "l2", "l3", "operations engineer", "production support", "noc"],
    "Security Specialist": ["security", "infosec", "cyber", "iam specialist"],
    "Business Analyst": ["business analyst", "functional consultant", "ba"],
    "Technical Writer": ["technical writer", "documentation"],
}


def normalize_role(title: str) -> str:
    t = (title or "").lower()
    for role, kws in ROLE_KEYWORDS.items():
        if any(k in t for k in kws):
            return role
    return title.strip().title() if title else "Software Engineer"


# Technology families: used to tell "we know the neighbourhood" (upskill) from "new territory" (hire/partner).
FAMILIES: dict[str, list[str]] = {
    "Integration platforms": ["Rhapsody", "Mirth Connect", "MuleSoft", "Boomi", "TIBCO", "Workato", "WSO2", "IBM App Connect", "Azure Integration Services",
                              "SAP PI/PO", "Informatica", "Kafka", "RabbitMQ", "Apigee", "Kong"],
    "Healthcare standards": ["HL7 v2", "HL7 FHIR", "IHE", "DICOM", "MLLP", "EHR/EMR", "HIS", "LIS", "RIS", "PACS"],
    "Cloud & infrastructure": ["Microsoft Azure", "AWS", "Google Cloud", "Kubernetes", "Docker", "Terraform", "Linux", "Windows Server", "VMware"],
    "Fraud & identity intelligence": ["Behavioral Biometrics", "Device Fingerprinting", "Geolocation Intelligence", "Bot Detection", "Fraud Monitoring Platform",
                                      "Graph Analytics", "Mobile App Security SDK"],
    "Security": ["SIEM", "IAM", "PKI/TLS", "MFA", "OAuth 2.0", "OpenID Connect", "SAML"],
    "Data & AI": ["Machine Learning", "Generative AI", "Databricks", "Snowflake", "Power BI", "Tableau", "SQL Server", "Oracle DB", "PostgreSQL", "MongoDB", "Denodo", "Reltio", "Neo4j"],
    "Operations": ["ServiceNow", "Splunk", "Dynatrace", "Prometheus/Grafana", "ELK", "ITIL", "Jira", "Confluence"],
    "Engineering": ["Java", ".NET", "Python", "JavaScript/TypeScript", "React", "Angular", "iOS", "Android", "CI/CD", "Git", "Postman"],
    "Architecture": ["TOGAF", "Enterprise Architecture", "ArchiMate", "Agile/Scrum"],
}
TECH_FAMILY = {t: f for f, ts in FAMILIES.items() for t in ts}

# Packaged products a services firm would usually bring in through a partner rather than build.
PARTNER_PRODUCTS = {"Behavioral Biometrics", "Device Fingerprinting", "Geolocation Intelligence", "Bot Detection", "Fraud Monitoring Platform", "SIEM"}
# Generic protocols/formats: never a gap on their own.
COMMODITY_TECH = {"JSON", "XML", "REST APIs", "SOAP", "TCP/IP", "SFTP", "Git", "Agile/Scrum", "EHR/EMR", "HIS", "LIS", "RIS", "PACS", "iOS", "Android"}


def best_subcategory(text: str, section: str, category: str) -> str:
    """Best subcategory for a text within a given category (used when a category is corrected)."""
    best, best_sc = "General Scope" if category == "Functional" else next(k for k, (c, _) in SUBCATEGORIES.items() if c == category), 0.0
    for sub, (cat, pats) in _COMPILED.items():
        if cat != category:
            continue
        sc = sum(1.0 for p in pats if p.search(text)) + sum(0.6 for p in pats if section and p.search(section))
        if sc > best_sc:
            best, best_sc = sub, sc
    return best
