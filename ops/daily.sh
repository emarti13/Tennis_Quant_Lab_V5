#!/usr/bin/env bash
# Daily job (systemd timer tql-daily). No Claude, no Actions minutes:
#   1. settle the paper trader against Kalshi results
#   2. gzip finished days of the logs
#   3. commit the logs to the data branch
#   4. bring in new code from the code branch; keep it only if the tests pass
#   5. write market_history/vm_status.md, commit, push the data branch
set -uo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"
source ops/env
PY=.venv/bin/python
LIVE=market_history/kalshi/live_scores
STATUS_ARGS=()

commit_logs() {
  git add -A market_history/kalshi/paper "$LIVE" market_history/vm_status.md 2>/dev/null
  git diff --cached --quiet || git commit -q -m "data: server logs $(date -u +%Y-%m-%d)"
}

# 1. settle (writes market_history/kalshi/paper/results.csv)
if ! $PY scripts/paper_trade_kalshi.py settle > /tmp/tql_settle.txt 2>&1; then
  STATUS_ARGS+=(--note "settle failed: $(tail -1 /tmp/tql_settle.txt)")
fi

# 2. gzip every finished day of the logs (only .csv.gz is committed; today's file keeps growing)
today=$(date -u +%Y-%m-%d)
for f in "$LIVE"/*.csv market_history/kalshi/paper/{snapshots,fills,depth}_*.csv; do
  [ -e "$f" ] || continue
  case "$f" in *"$today"*) continue ;; esac
  gzip -f "$f"
done

# 3. commit logs before touching code
commit_logs

# 4. new code: merge, test, keep or roll back
before=$(git rev-parse HEAD)
code_changed=no
if git fetch -q origin "$CODE_BRANCH" "$DATA_BRANCH"; then
  git merge -q --no-edit "origin/$DATA_BRANCH" 2>/dev/null || git merge --abort 2>/dev/null
  if git merge -q --no-edit "origin/$CODE_BRANCH"; then
    [ "$(git rev-parse HEAD)" != "$before" ] && code_changed=yes
  else
    git merge --abort
    STATUS_ARGS+=(--note "merge of $CODE_BRANCH conflicted; kept old code")
  fi
else
  STATUS_ARGS+=(--note "git fetch failed")
fi
if [ "$code_changed" = yes ]; then
  $PY -m pip install -q -r requirements.txt || true
fi
# shellcheck disable=SC2086
timeout 90m $PY -m pytest $TESTS > /tmp/tql_tests.txt 2>&1
test_rc=$?
STATUS_ARGS+=(--tests "$(tail -1 /tmp/tql_tests.txt)" --tests-rc "$test_rc")
if [ "$test_rc" -ne 0 ] && [ "$code_changed" = yes ]; then
  git reset -q --hard "$before"
  STATUS_ARGS+=(--note "tests failed on new code from $CODE_BRANCH; rolled back to ${before:0:7}")
  code_changed=no
fi
if [ "$code_changed" = yes ]; then
  sudo -n systemctl restart tql-paper.service tql-live.service 2>/dev/null \
    || STATUS_ARGS+=(--note "new code merged; services pick it up at their daily restart")
fi

# 5. status, commit, push (retries with backoff)
$PY ops/status.py --settle /tmp/tql_settle.txt "${STATUS_ARGS[@]}"
commit_logs
for wait in 2 4 8 16 0; do
  git push -q origin "HEAD:$DATA_BRANCH" && exit 0
  [ "$wait" -gt 0 ] && sleep "$wait"
done
echo "push failed" >&2
exit 1
