"""Write market_history/vm_status.md: one page a person or a fresh Claude session reads to see
what the server did (services, data collected, paper results, tests, problems).

Usage:  python ops/status.py [--settle FILE] [--tests LINE --tests-rc N] [--note TEXT ...] [--print]
"""
from __future__ import annotations

import argparse
import gzip
import shutil
import subprocess
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parents[1]
PAPER = BASE / "market_history" / "kalshi" / "paper"
LIVE = BASE / "market_history" / "kalshi" / "live_scores"
OUT = BASE / "market_history" / "vm_status.md"


def _sh(*cmd: str) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "?"


def _rows(path: Path) -> int:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt") as f:
        return max(0, sum(1 for _ in f) - 1)


def live_days(n: int = 7) -> list[str]:
    files = sorted(LIVE.glob("*.csv*"), key=lambda p: p.name)[-n:]
    out = []
    for p in files:
        try:
            df = pd.read_csv(p, usecols=["event_ticker"])
            out.append(f"| {p.name.split('.')[0]} | {len(df)} | {df['event_ticker'].nunique()} |")
        except (OSError, ValueError, pd.errors.EmptyDataError):
            out.append(f"| {p.name.split('.')[0]} | unreadable | |")
    return out


def paper_summary() -> list[str]:
    p = PAPER / "results.csv"
    if not p.exists():
        return ["No settled results yet."]
    r = pd.read_csv(p)
    done = r[r["result"].isin(["yes", "no"])]
    lines = ["| setting | markets | contracts | held $ | held after fee $ | marked $ |", "|---|---|---|---|---|---|"]
    for h, g in done.groupby(done["h"].astype(str)):
        lines.append(f"| {h} | {g['ticker'].nunique()} | {g['contracts'].sum():.0f} | {g['held'].sum():.2f} | "
                     f"{g['held_after_maker_fee'].sum():.2f} | {g['marked'].sum():.2f} |")
    fails = PAPER / "run_failures.log"
    if fails.exists():
        lines.append(f"\nrun_failures.log: {_rows(fails) + 1} lines")
    return lines


def build(settle: str | None, tests: str | None, tests_rc: str | None, notes: list[str]) -> str:
    now = pd.Timestamp.now(tz="UTC").floor("s")
    disk = shutil.disk_usage(BASE)
    services = {s: _sh("systemctl", "is-active", s) for s in ("tql-paper", "tql-live", "tql-daily.timer")}
    parts = [f"# Server status, {now.isoformat()}", "",
             f"Code: `{_sh('git', '-C', str(BASE), 'log', '-1', '--format=%h %s')}`  ",
             f"Disk free: {disk.free / 2**30:.1f} GB  ",
             "Services: " + ", ".join(f"{k} {v}" for k, v in services.items()), ""]
    if tests is not None:
        parts += [f"Tests ({'pass' if tests_rc == '0' else 'FAIL'}): `{tests}`", ""]
    parts += ["## Problems", ""] + ([f"- {n}" for n in notes] or ["- none"]) + [""]
    parts += ["## Live score log (last 7 days)", "", "| day | rows | matches |", "|---|---|---|"] + live_days() + [""]
    parts += ["## Paper market-making (settled markets)", ""] + paper_summary() + [""]
    if settle and Path(settle).exists():
        parts += ["Settle output:", "```", Path(settle).read_text().strip()[-2000:], "```", ""]
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--settle")
    ap.add_argument("--tests")
    ap.add_argument("--tests-rc")
    ap.add_argument("--note", action="append", default=[])
    ap.add_argument("--print", action="store_true", help="print instead of writing the file")
    a = ap.parse_args()
    text = build(a.settle, a.tests, a.tests_rc, a.note)
    if a.print:
        print(text)
    else:
        OUT.write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
