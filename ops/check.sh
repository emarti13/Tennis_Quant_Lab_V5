#!/usr/bin/env bash
# Quick health check on the server: services, last log lines, today's row counts.
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"
for s in tql-paper tql-live tql-daily.timer; do printf '%-16s %s\n' "$s" "$(systemctl is-active "$s")"; done
echo; echo "--- paper trader, last 3 lines";  journalctl -u tql-paper -n 3 --no-pager -o cat
echo; echo "--- live logger, last 3 lines";   journalctl -u tql-live -n 3 --no-pager -o cat
echo; echo "--- last daily run";              journalctl -u tql-daily -n 15 --no-pager -o cat
echo; .venv/bin/python ops/status.py --print
