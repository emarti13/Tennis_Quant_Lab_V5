from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pandas as pd


EXPECTED_SHA256 = "147752287ccb3ced80df0a06f68f4c380bda5cf769ee6b5e702c92bae02da2e1"
EXPECTED_BYTES = 34860
EXPECTED_ROWS = 354
EXPECTED_YEAR_COUNTS = {2025: 118, 2026: 118, 2027: 118}

parts_dir = Path(".tmp_schedule_parts")
encoded = "".join((parts_dir / f"part{i}.b64").read_text(encoding="utf-8").strip() for i in range(6))
payload = base64.b64decode(encoded)

actual_sha = hashlib.sha256(payload).hexdigest()
if actual_sha != EXPECTED_SHA256:
    raise SystemExit(f"schedule checksum mismatch: {actual_sha} != {EXPECTED_SHA256}")
if len(payload) != EXPECTED_BYTES:
    raise SystemExit(f"schedule byte count mismatch: {len(payload)} != {EXPECTED_BYTES}")

out = Path("context_registry/tennis_master_schedule.csv")
out.write_bytes(payload)

df = pd.read_csv(out, low_memory=False)
if len(df) != EXPECTED_ROWS:
    raise SystemExit(f"schedule row count mismatch: {len(df)} != {EXPECTED_ROWS}")
year_counts = df["Year"].value_counts().sort_index().to_dict()
if year_counts != EXPECTED_YEAR_COUNTS:
    raise SystemExit(f"schedule year counts mismatch: {year_counts} != {EXPECTED_YEAR_COUNTS}")

print({"sha256": actual_sha, "bytes": len(payload), "rows": len(df), "year_counts": year_counts})
