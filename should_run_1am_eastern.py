
from __future__ import annotations

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

event = os.getenv("GITHUB_EVENT_NAME", "")
schedule = os.getenv("GITHUB_EVENT_SCHEDULE", "")

# Manual runs always proceed.
if event == "workflow_dispatch":
    print("Manual run: refresh enabled.")
    raise SystemExit(0)

eastern = datetime.now(ZoneInfo("America/New_York"))
offset_hours = int(eastern.utcoffset().total_seconds() // 3600)

# GitHub cron is UTC. Run both 05:00 and 06:00 UTC, then let only the
# correct one proceed for the current Eastern offset.
expected = "0 5 * * *" if offset_hours == -4 else "0 6 * * *"

print(f"Eastern now: {eastern.isoformat()}")
print(f"Eastern UTC offset: {offset_hours}")
print(f"GitHub schedule: {schedule}")
print(f"Expected active schedule: {expected}")

if schedule != expected:
    print("DST/EST shadow run: skipping refresh.")
    raise SystemExit(78)

print("1:00 AM Eastern schedule selected: refresh enabled.")
