
from __future__ import annotations
import json
from pathlib import Path

p = Path("v5_refresh_last.json")
if not p.exists():
    raise SystemExit("No v5_refresh_last.json found yet.")

data = json.loads(p.read_text(encoding="utf-8"))
print("Status:", data.get("status"))
print("Started UTC:", data.get("started_utc"))
print("Finished UTC:", data.get("finished_utc"))
print("Year:", data.get("year"))

for name, info in (data.get("files") or {}).items():
    print(
        f"{name}: prior={info.get('prior_rows')} "
        f"new={info.get('rows')} warnings={info.get('warnings')}"
    )

for name, info in (data.get("outputs") or {}).items():
    print(f"{name}: {info.get('rows')} rows")
