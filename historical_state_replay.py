from __future__ import annotations

from datetime import datetime


def _sort_value(row):
    value = row.get("date") or row.get("tourney_date") or row.get("startTime") or ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


class ReplayStateStore:
    """Generic chronological replay harness.

    The injected engine must expose snapshot(row) and update(row). Snapshot is always
    captured before the target match update, preventing target-match leakage.
    """

    def __init__(self, engine):
        self.engine = engine

    def capture(self, matches, *, target_ids, id_field="id") -> dict:
        targets = set(target_ids)
        out = {}
        for row in sorted(matches, key=_sort_value):
            row_id = row.get(id_field)
            if row_id in targets:
                out[row_id] = self.engine.snapshot(row)
            self.engine.update(row)
        return out
