# QA suites

Run from the `backend` folder. Each one makes a throwaway database, so it never touches real data, and needs no AI key.

| Suite | What it checks |
|---|---|
| `python tests/qa_matrix.py` | Every API route × every role (admin, presales, architect, finance, delivery, viewer) × three companies (two suppliers, one buyer) + signed out: the right people get in, everyone else gets 403/404, and nothing returns a server error. |
| `python tests/qa_security.py` | Forged/expired/`alg=none` tokens, login throttling (including a faked `X-Forwarded-For`), hostile uploads (wrong types, corrupt files, path tricks, a zip bomb, oversize), 1,400+ malformed request bodies, formula injection in the Excel export, header injection, SQL-looking searches, CORS and security headers. |
| `python tests/qa_fairness.py` | Nothing scores well because of a keyword ("Azure" in an unrelated requirement, keyword stuffing, a one-word requirement), a company name, the demo flag or list order; certificates count only from the register and only while valid; the AI can't mark a match strong without library evidence. |
| `python tests/qa_e2e.py` | A whole deal by a 6-person team (each role approving its own stage), overrides and price arithmetic, downloads, comments, clarifications, outcomes and learning, the opportunity radar with broken sources, the supplier network with a buyer team, market insights. |
| `python tests/qa_drive_sync.py` | The connected Google Drive folder: connect, an unchanged refresh, then a changed file, a new file and deleted files; only those are touched, items added in the app are kept, edits made in the app are reported, deletions only happen when ticked, other companies can't see or change it. |
| `python tests/qa_compliance.py` | Trust facts come from the real setup, tender licences, the free-tier AI confirmation, company export (no secrets, nothing from other companies) and permanent delete. |
| `python tests/qa_db_tools.py` | Damages a real SQLite file, then checks detection, that background writes stop, `repair_db` rescue and switch-over, and (with `QA_POSTGRES_URL`) `copy_db` to PostgreSQL. |

Any suite can run on PostgreSQL: set `DATABASE_URL` to an empty database first.

Each prints `N passed, M failed` and exits non-zero on any failure.
