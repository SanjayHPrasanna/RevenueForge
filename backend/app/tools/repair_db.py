"""Check the SQLite database and, if it's damaged, build a repaired copy.

    python -m app.tools.repair_db           check only
    python -m app.tools.repair_db --apply   build the repaired copy and switch to it on the next restart

The damaged file is never changed or deleted. The repaired copy gets a new name (revenueforge-repaired-<time>.db) and
db-current.txt points at it, so restarting the app switches over. Public tenders that can't be read are fetched again on
the next refresh.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from ..config import DATA_DIR, settings
from .dbtools import quick_check, salvage_copy


def main(argv: list[str]) -> int:
    url = settings.database_url
    if not url.startswith("sqlite:///"):
        print("This server uses", url.split(":")[0], "- the repair tool is only for SQLite files.")
        return 2
    path = url[len("sqlite:///"):]
    print("Database:", path)
    state = quick_check(path)
    if state == "ok":
        print("Check: OK. Nothing to repair.")
        return 0
    print("Check: DAMAGED ->", state[:300])
    if "--apply" not in argv:
        print("\nRun again with --apply to build a repaired copy (the damaged file is kept as it is).")
        return 1
    name = f"revenueforge-repaired-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.db"
    target = DATA_DIR / name
    print(f"\nCopying every readable row into {name} ...")
    report = salvage_copy(url, f"sqlite:///{target.as_posix()}")
    after = quick_check(str(target))
    if after != "ok":
        print("The repaired copy didn't pass its own check:", after[:300], "\nNothing was switched.")
        return 3
    (DATA_DIR / "db-current.txt").write_text(name, encoding="utf-8")
    lost = {t: l for t, (c, l) in report.items() if l}
    print("\nRepaired copy is OK and will be used after the next restart.")
    if lost:
        print("Rows that couldn't be read:", ", ".join(f"{t} {'(whole table)' if l < 0 else l}" for t, l in lost.items()))
        if set(lost) <= {"tenders", "tender_fits", "tender_sources", "embedding_cache"}:
            print("Only public tender data and caches were lost; they're rebuilt automatically.")
    print("\nNow restart the app (Azure portal -> your App Service -> Restart).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
