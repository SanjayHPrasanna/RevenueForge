# RevenueForge

AI deal & proposal intelligence. A company registers, uploads its capabilities, skills matrix, certifications, rate card, case studies and Word proposal template; then every RFP / RFI / RFQ / SOW it uploads becomes a reviewed deal package:

1. **Requirements**: every requirement extracted, classified (functional, non-functional, compliance, commercial) and linked to its page in the source
2. **Capability match**: each requirement scored against the company's own capabilities, case studies, accelerators, certifications and people
3. **Gaps & risks**: what can't be covered yet, with partner / upskill / hire / certify options and a bid verdict
4. **Architecture**: solution layers and technology decisions, traced to the requirements that drove them
5. **Effort & team**: workstreams, plan and a role-wise team with named (anonymised) people from the skills matrix
6. **Pricing**: rate card + cost, contingency, travel, and aggressive / target / premium margin scenarios
7. **Proposal**: a full proposal with compliance matrix, written into the company's own Word template
8. **Delivery handoff**: scope, assumptions, risks, team, plan, open items and first 30 days

Each stage is a draft the right role approves (pre-sales, architect, finance, delivery). Everything feeds a per-company **knowledge graph** that gets better with every deal and every win/loss.

---

## Run it on Windows (first time)

Prerequisites: **Python 3.11+** and **Node.js 20+** (`python --version`, `node --version`).

In VS Code's PowerShell terminal, inside the `revenueforge` folder:

```powershell
.\setup.bat      # one time: installs packages
.\start.bat      # every time: starts the API and the web app, opens http://localhost:5173
```

Then click **Create workspace**, register your company (you become its admin) and follow the onboarding wizard.

There are no built-in accounts. `reset.bat` permanently deletes all local data (companies, users, uploaded files and generated documents) so you can start fresh.

macOS / Linux: `./setup.sh` then `./start.sh`.

## Demo flow

1. Register a company and complete onboarding (capabilities, skills matrix, rate card, proposal template at minimum).
2. *Deals → New deal*: upload an RFP. Keep *client confidential* on and set an alias.
3. Walk the 8 stages: requirements (click one to see its source page), capability match, gaps, architecture, effort & team, pricing (change the margin and watch everything recalculate), proposal and handoff downloads.
4. Register a second company with a different profile and upload the same RFP to show different coverage and verdict.
5. Close on **Home** and **Knowledge graph**.

`sample-data/` contains two fictional company packs you can upload during onboarding to test the flow.

## Turning on AI (Gemini)

1. In VS Code, create the file `backend\.env` (copy `backend\.env.example`) and set:
   ```
   LLM_PROVIDER=gemini
   GEMINI_API_KEY=your-key-from-aistudio.google.com
   ```
   Keep the key in this file only. Never paste it into chats, code or documents. `.env` is excluded from git.
2. Restart `start.bat`. The top bar shows **AI: gemini**, and *Settings → AI engine* shows the model in use, calls made and any errors.

With AI on, every stage is AI-first: Gemini reads the RFP, classifies requirements, judges capability fit against your evidence (with semantic matching from Gemini embeddings), plans gap mitigations, designs the architecture and writes each answer. Estimation and pricing stay deterministic and explainable (rate card × effort), calibrated by your actuals. If any AI call fails, that step falls back to the rules engine and the deal still completes.

**Free tier caution.** On Google's free (unpaid) tier, submitted content may be used to improve Google's products and may be read by human reviewers, and Google asks you not to submit confidential information. Use the free key with sample or non-confidential documents. For client RFPs, link the key to a billed Google Cloud project and set `LLM_PAID=true`. Free keys are rate-limited; `LLM_RPM=8` keeps RevenueForge under the limit, so a large RFP takes a few minutes.

### Maahi, the landing-page assistant

Visitors can chat with Maahi about RevenueForge's features and workflow. Maahi uses the AI provider configured above and answers from product information; it cannot access workspace or deal data. The chat is limited to 10 messages per IP address per minute, and conversation history is kept in the browser only for that visit. Messages are sent to the configured AI provider to generate replies, so visitors should not share confidential information. Maahi is unavailable until an AI provider is configured.

## Sign in with Google

Works out of the box: the team's Google client ID is in `backend/team.env`, which comes with the code. Each person signing in must be added as a **test user** in Google Cloud Console (Google Auth Platform → Audience) until the app is published there. To run the app on another address (a server, a different port), add that address under *Authorised JavaScript origins* for the client. `team.env` is only for shared, non-secret settings; API keys always go in your own `backend/.env`.

### Import from Google Drive

From the **Knowledge library** page, use **Import from Google Drive** to connect to Drive, browse to a folder and import supported files into the normal review flow. The Google Cloud project for `GOOGLE_CLIENT_ID` must have the **Google Drive API** enabled, and the app's exact web origin (for local development, `http://localhost:5173`) must be listed under **Google Auth Platform → Clients → OAuth client → Authorized JavaScript origins**. The Drive button also opens Drive in a new tab. Google Docs, Sheets and Slides are exported as Word, Excel and PowerPoint files.

## Solution video for the client

In a deal's **Proposal** stage, *Make the video* creates a 60–90 second narrated MP4 of the solution: the client's needs, the layered architecture, the team and its skills from your knowledge graph, case studies and certifications, and the delivery plan. Everything shown comes from the deal's data; costs, margins, gaps and internal codes never appear. The AI writes only the narration, from facts with the client's name hidden. The voice is your computer's own (Windows speech), so no audio leaves your machine. When downloading, choose **Proposal only** or **Proposal + video** (a .zip with both). Optional settings in `backend/.env`: `GEMINI_VIDEO_API_KEY` (a second free key just for narration) and `VIDEO_VOICE`.

## How it learns (per company, never shared)

| Signal | What RevenueForge does with it |
|---|---|
| A reviewer changes a category, priority or match, or adds or removes a requirement | Stored as a correction; the most relevant past corrections go into every future AI prompt for your company |
| Requirements stage approved | Categories become training data; your **own classifier** retrains (after 30 reviewed requirements) and overrides generic AI where it is confident |
| A reviewer rewrites an answer | The AI learns your team's tone and detail level for future answers |
| Proposal stage approved | Answers go into the **answer library** and are reused on similar requirements in future RFPs |
| Deal marked won or lost (+ actual effort) | Answers from wins rank higher; actual vs planned effort calibrates future estimates; win rate by margin band informs pricing |

The **AI learning** page shows all of it: accuracy per deal over time, corrections learned, classifier status, library size and reuse, and calibration.

## Bring your own company data

Sign up a new workspace (*Create workspace*) and follow the onboarding wizard. Spreadsheets can be in **any layout**: RevenueForge maps the columns and shows you the mapping to fix before import (skills as a list or a rating grid; hourly, daily or monthly rates). Capability decks and case studies can be Word, PDF or PowerPoint. Each section has a *starter spreadsheet* download.

Proposal template: a Word file. Optional placeholders `{{TITLE}}`, `{{CLIENT}}`, `{{DATE}}`, `{{COMPANY}}`; the proposal body goes where `{{CONTENT}}` sits (or at the end).

## Measuring the "95% classification accuracy"

Two honest measures are built in:
- **Human-reviewed accuracy**: in *Requirements*, tick rows as reviewed (or correct their category). The tile shows the share of reviewed requirements whose category RevenueForge got right.
- **Labelled test set**: *Score against a labelled test set* accepts an Excel/CSV with a requirement column and a category column (e.g. one a pre-sales expert labelled by hand) and reports recall and classification accuracy.

With Gemini on, plus your team's corrections and your own trained classifier, the trend on the AI learning page shows progress toward 95%.

## Architecture

```
frontend/  React + TypeScript + Tailwind (Vite)          → http://localhost:5173
backend/   FastAPI + SQLAlchemy                           → http://localhost:8000/api
  app/services/parsing.py     PDF/DOCX/XLSX/PPTX → blocks with page + section
  app/services/extraction.py  requirements + metadata (rules engine / LLM)
  app/services/onboarding.py  column mapping for any spreadsheet layout
  app/services/matching.py    capability match, gaps, bid readiness
  app/services/solution.py    architecture, estimation, team, pricing
  app/services/docgen.py      proposal + handoff into the company's Word template
  app/services/graph.py       per-tenant knowledge graph
  app/services/pipeline.py    background 8-stage orchestration
sample-data/  two fictional company packs
```

- Multi-tenant: every record carries `tenant_id`; every query is scoped to the signed-in user's company.
- Database: SQLite by default (zero setup); set `DATABASE_URL` for PostgreSQL.
- Docker: `docker compose up --build` runs PostgreSQL + RevenueForge on http://localhost:8000.
- Hosting on Azure App Service (GitHub builds and deploys on every merge to `main`): see [DEPLOY.md](DEPLOY.md).

All companies, people and projects in `sample-data` are fictional. Real RFPs are not included in this folder's code.
