"""Server status page: lists problems, live-log days (plain or gzipped) and paper results."""
from __future__ import annotations

import gzip

import pandas as pd

import ops.status as st


def test_status_page_reports_logs_results_and_problems(tmp_path, monkeypatch):
    live, paper = tmp_path / "live", tmp_path / "paper"
    live.mkdir(), paper.mkdir()
    pd.DataFrame({"event_ticker": ["A", "A", "B"]}).to_csv(live / "2026-10-21.csv", index=False)
    with gzip.open(live / "2026-10-20.csv.gz", "wt") as f:
        f.write("event_ticker\nC\n")
    pd.DataFrame({"ticker": ["T", "T"], "h": ["join", "0.03"], "result": ["yes", "no"], "contracts": [10, 0],
                  "held": [1.5, 0], "held_after_maker_fee": [1.4, 0], "marked": [0.2, 0]}).to_csv(paper / "results.csv", index=False)
    monkeypatch.setattr(st, "LIVE", live)
    monkeypatch.setattr(st, "PAPER", paper)
    text = st.build(None, "3 passed", "0", ["merge conflicted"])
    assert "- merge conflicted" in text and "Tests (pass)" in text
    assert "| 2026-10-20 | 1 | 1 |" in text and "| 2026-10-21 | 3 | 2 |" in text
    assert "| join | 1 | 10 | 1.50 | 1.40 | 0.20 |" in text
