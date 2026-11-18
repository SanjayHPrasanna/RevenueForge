#!/bin/bash
# Runs every QA suite from the backend folder and prints one summary line per suite.
cd "$(dirname "$0")/.."
fail=0
for t in qa_fixes qa_review qa_platform qa_azure qa_ai_fallback qa_fairness qa_matrix qa_security qa_e2e qa_compliance qa_drive_sync qa_db_tools qa_customers qa_generalised qa_ai_privacy ${EXTRA_SUITES}; do
  out=$(python3 tests/$t.py 2>&1); rc=$?
  line=$(echo "$out" | grep -E "passed, [0-9]+ failed" | tail -1)
  echo "== $t: $line"
  if [ $rc -ne 0 ]; then fail=1; echo "$out" | grep -E "FAIL" | head -8; fi
done
exit $fail
