# Five-domain acceptance scorecard

Produced by `python tests/qa_domains.py`. Offline (no AI key), so it measures the deterministic path every deal falls back to.

## Phase 0 baseline (switch off = today's pipeline, main @ d69507c)

| Domain | Score | Understanding | Decision | Team | Proposal | Commercial |
|---|---|---|---|---|---|---|
| software | 50% | 3/6 | 1/1 | 2/5 | 3/5 | 0/1 |
| cybersecurity | 38% | 3/7 | 0/2 | 2/5 | 3/5 | 0/2 |
| cloud | 56% | 2/6 | 1/1 | 3/5 | 4/5 | 0/1 |
| network | 33% | 3/6 | 0/2 | 1/5 | 3/5 | 0/3 |
| data | 52% | 3/6 | 0/2 | 4/5 | 4/5 | 0/3 |
| **all** | **45%** | 45 of 99 checks |||||

## After Phases 1–5 (branch generalised-response)

The pack grew to 114 checks while the phases were built (proposal checks for internal notes, duplicated answers, cited
evidence and relevant case studies; commercial checks for partner and licence lines). Same RFPs, same library, offline.

| Domain | Switch off | Switch on | Understanding | Decision | Team | Proposal | Commercial |
|---|---|---|---|---|---|---|---|
| software | 57% | **100%** | 6/6 | 1/1 | 5/5 | 8/8 | 1/1 |
| cybersecurity | 29% | **100%** | 7/7 | 2/2 | 5/5 | 8/8 | 2/2 |
| cloud | 62% | **100%** | 6/6 | 1/1 | 5/5 | 8/8 | 1/1 |
| network | 38% | **100%** | 6/6 | 2/2 | 5/5 | 8/8 | 3/3 |
| data | 58% | **100%** | 6/6 | 2/2 | 5/5 | 8/8 | 3/3 |
| **all** | **48%** (55/114) | **100%** (114/114) ||||||

What the checks don't measure: effort per requirement (still the earlier 3/8/18-day heuristic, so build phases are thin
and software, cloud and data prices land 40–75% under the stated budgets), and the AI paths (Profile, team planner), which
run only with a live AI provider.
