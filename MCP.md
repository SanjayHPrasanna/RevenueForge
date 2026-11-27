# RevenueForge in Claude and Glean (MCP)

RevenueForge runs a remote MCP server at **`<your app URL>/mcp`**. For example:
`https://revenueforge-demo-bcbxa6becwdggtfx.centralindia-01.azurewebsites.net/mcp`

It uses Streamable HTTP with plain JSON responses. It supports protocol versions 2025-11-25, 2025-06-18, 2025-03-26 and 2024-11-05.

## How people connect

| Where | How |
|---|---|
| claude.ai, Claude Desktop, Claude mobile | Settings → Connectors → Add custom connector → paste the URL. Leave the OAuth client fields empty. Claude registers itself, then the person signs in to RevenueForge and presses **Allow**. |
| Claude Code | `claude mcp add --transport http revenueforge <URL>`, then `/mcp` to sign in. |
| Glean | Admin → add remote MCP server → paste the URL. Choose **Dynamic client registration**, so each person signs in. Or choose **API key** with a key from RevenueForge Settings → AI assistants, sent as `Authorization: Bearer <key>`. |
| Anything else | OAuth 2.1 with dynamic client registration, or a personal API key in `Authorization: Bearer` or `X-API-Key`. |

People can see and disconnect their connections, and make or revoke API keys, in **Settings → AI assistants**.

## Tools

| Tool | What it does | Writes? |
|---|---|---|
| `list_deals` | Lists deals with status, verdict, readiness, due date and value. | no |
| `get_deal` | Shows the verdict and the reason for it, readiness today and with a plan, the top missing technologies with the fix for each, the team and the price scenarios. | no |
| `get_requirements` | Lists requirements and how well each is met (all, gaps only, or mandatory gaps only). | no |
| `search_knowledge` | Searches people (by employee code, without names or day cost), capabilities, certifications, case studies, accelerators and rates. | no |
| `company_overview` | Shows the company profile and the library counts. | no |
| `pipeline_summary` | Shows the dashboard KPIs and the most-missing skills. | no |
| `find_opportunities` | Lists tenders from the opportunity radar, scored for fit. | no |
| `ask_workspace` | Asks Maahi, which answers from this company's data only. | no |
| `create_deal` | Starts a deal from RFP text or a base64-encoded file. Needs the Presales or Admin role. | yes |
| `list_projects` | Lists delivery projects with health (and why), milestones, value, invoiced, paid and overdue. | no |
| `get_project` | Shows one project: milestones, team, invoices, costs, changes, risks, issues, SLA months and status reports. | no |
| `client_360` | Shows one client across bids and delivery, or lists every client with headline numbers. | no |

## Security

- Every tool calls the app's own API as the connected person. Roles, masking of confidential client names and company boundaries are therefore identical to the web app.
- OAuth:
  - Authorization code flow with PKCE (S256 only).
  - Codes last 5 minutes and work once.
  - Access tokens last 1 hour.
  - Refresh tokens last 60 days and change on every use.
  - The person always sees a consent screen showing who is asking and where they will be sent back to.
- Only SHA-256 hashes of tokens and keys are stored. A key is shown once, when it is made.
- "Sign out everywhere", deactivating a user and pausing a company all cut off assistant access too.
- Not exposed through MCP: approving stages, settings, deleting anything, day costs, and employee names.

## Deployment notes

- No new packages and no new environment variables. Three tables (`oauth_clients`, `oauth_codes`, `mcp_tokens`) are created at startup.
- If `APP_URL` is set, it must be the exact address people paste (without `/mcp`). The OAuth `resource` must match the URL the person enters.
- Claude connects from `160.79.104.0/21`. Allow this range if the app sits behind a firewall.
- Test: `python tests/qa_mcp.py [knowledge-folder] [rfp-file]`.
