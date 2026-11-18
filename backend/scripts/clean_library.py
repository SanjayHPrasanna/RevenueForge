"""Take client names out of answer-library entries and reviewer-correction examples saved before they were masked.

Run against TEST data only, with the data folder named explicitly:

    RF_DATA_DIR=/path/to/test-data python scripts/clean_library.py            # dry run: lists what would change
    RF_DATA_DIR=/path/to/test-data python scripts/clean_library.py --apply    # backs up, then changes

--apply first writes every affected library entry and correction example, as it was, to library_backup_<time>.json in
the data folder, then updates the text in place: question and answer for library entries; requirement text, AI value,
reviewer value and context for corrections. IDs, the source deal, origin, approver, outcome, uses, evidence,
technologies, kind, user and dates are kept. Afterwards it checks that no confidential name or alias is left in either.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

if not os.environ.get("RF_DATA_DIR"):
    sys.exit("Set RF_DATA_DIR to the test data folder explicitly; this script never guesses which database to change.")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import AnswerEntry, Deal, LearningExample  # noqa: E402
from app.services import learning  # noqa: E402


def leftovers(db) -> list[tuple[str, str]]:
    """(id, text) for every confidential name or alias still in a library question or answer or a correction example."""
    out = []
    for e in db.scalars(select(AnswerEntry)).all():
        nf = learning.library_neutraliser(db, e.tenant_id)
        if nf(e.question) != e.question or nf(e.answer) != e.answer:
            out.append((e.id, e.question[:80]))
    for x in db.scalars(select(LearningExample)).all():
        nf = learning.library_neutraliser(db, x.tenant_id)
        if any(nf(v or "") != (v or "") for v in (x.input_text, x.ai_value, x.human_value)) or \
                learning._neutral_obj(nf, x.context or {}) != (x.context or {}):
            out.append((x.id, (x.input_text or "")[:80]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="change the entries (default: dry run)")
    ap.add_argument("--tenant", default=None, help="only this workspace id")
    a = ap.parse_args()
    with SessionLocal() as db:
        n_deals = db.query(Deal).count()
        plan = learning.clean_library(db, a.tenant, apply=False)
        cplan = learning.clean_corrections(db, a.tenant, apply=False)
        print(f"{plan['checked']} library entries checked across {n_deals} deals; {plan['changed']} would change")
        print(f"{cplan['checked']} correction examples checked; {cplan['changed']} would change")
        if not a.apply or not (plan["changed"] or cplan["changed"]):
            for c in plan["changes"][:20]:
                print(" - library", c["id"], c["question"][:100])
            for c in cplan["changes"][:20]:
                print(" - correction", c["id"], c["input_text"][:100])
            return 0
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = os.path.join(os.environ["RF_DATA_DIR"], f"library_backup_{stamp}.json")
        with open(path, "w") as f:
            json.dump({"library": plan["backup"], "corrections": cplan["backup"]}, f, ensure_ascii=False, indent=1, default=str)
        print("backup written:", path)
        done = learning.clean_library(db, a.tenant, apply=True)
        cdone = learning.clean_corrections(db, a.tenant, apply=True)
        left = leftovers(db)
        print(f"{done['changed']} library entries and {cdone['changed']} correction examples cleaned; "
              f"confidential names left: {len(left)}")
        return 1 if left else 0


if __name__ == "__main__":
    sys.exit(main())
