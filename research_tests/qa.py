"""Sanity checks that research scripts run on their own data before reporting anything.

Each check states an expected range taken from facts known independently of the result being
tested (base rates, join coverage, margins). A value outside the range stops the script with
the check's name, value and range, instead of letting a broken join or a silent NaN flow into a
conclusion. Every script writes its checks next to its results (`qa_<name>.json`), so a reader
can see what was verified.

    qa = QA("kaggle_join")
    qa.check("player A win share", share, 0.47, 0.53)
    qa.count("rows after join", n)          # recorded, not range-checked
    qa.save(folder)
"""
from __future__ import annotations

import json
import math
import os


class QAError(AssertionError):
    pass


class QA:
    def __init__(self, name: str):
        self.name = name
        self.rows: list[dict] = []

    def check(self, label: str, value, lo=None, hi=None, hard: bool = True):
        v = float(value)
        ok = math.isfinite(v) and (lo is None or v >= lo) and (hi is None or v <= hi)
        self.rows.append({"check": label, "value": round(v, 6), "lo": lo, "hi": hi, "ok": bool(ok)})
        print(f"[qa:{self.name}] {'ok  ' if ok else 'FAIL'} {label} = {v:.6g} (expected {lo}..{hi})", flush=True)
        if not ok and hard:
            raise QAError(f"{self.name}: {label} = {v} outside [{lo}, {hi}]")
        return ok

    def zero(self, label: str, value):
        """value must be exactly 0 (missing values, duplicate keys, impossible rows)."""
        return self.check(label, value, 0, 0)

    def count(self, label: str, value):
        self.rows.append({"check": label, "value": int(value), "lo": None, "hi": None, "ok": True})
        print(f"[qa:{self.name}] n    {label} = {int(value)}", flush=True)

    def save(self, folder: str):
        path = os.path.join(folder, f"qa_{self.name}.json")
        json.dump(self.rows, open(path, "w"), indent=1)
        return path
