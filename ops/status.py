"""Write market_history/vm_status.md: one page a person or a fresh Claude session reads to see
what the server did (services, data collected, paper results, tests, problems).

Usage:  python ops/status.py [--settle FILE] [--tests LINE --tests-rc N] [--note TEXT ...] [--print]
"""
from __future__ import annotations

import argparse
import gzip
import shutil
import subprocess
import sys
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


def poll_gap() -> str:
    files = sorted(LIVE.glob("*.csv*"), key=lambda p: p.name)
    if not files:
        return "no log"
    try:
        sys.path.insert(0, str(BASE))
        from scripts.log_kalshi_live import read_log
        df = read_log(files[-1])
        t = pd.to_datetime(df["polled_utc"], utc=True, errors="coerce")
        gaps = df.assign(t=t).sort_values("t").groupby("event_ticker")["t"].diff().dt.total_seconds().dropna()
        return f"{gaps.median():.0f}" if len(gaps) else "n/a"
    except Exception as exc:                                     # the status page must not fail
        return f"unreadable ({type(exc).__name__})"


def registrations() -> list[str]:
    files = sorted((BASE / "market_history" / "kalshi" / "registrations").glob("*_summary.json"))
    if not files:
        return ["none yet"]
    import json
    lines = ["| test | status | settled / needed | cents per contract | 95% range | favourite won |", "|---|---|---|---|---|---|"]
    for p in files:
        s = json.loads(p.read_text())
        lines.append(f"| {p.stem.replace('_summary', '')} | {s.get('status')} | {s.get('settled')} / {s.get('min_matches')} | "
                     f"{s.get('cents_per_contract', '')} | {s.get('range_cents', '')} | {s.get('favourite_won', '')} |")
    return lines


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


def settle_text(text: str) -> str:
    """Settle output, with a traceback cut down to this repo's frames and the error line."""
    lines = text.strip().splitlines()
    if not any(l.startswith("Traceback") for l in lines):
        return "\n".join(lines[-40:])
    keep = []
    for i, l in enumerate(lines):
        if l.startswith('  File "') and "site-packages" not in l and "pandas/_libs" not in l:
            keep += [l] + ([lines[i + 1]] if i + 1 < len(lines) else [])
    return "\n".join(keep + lines[-1:])


def build(settle: str | None, tests: str | None, tests_rc: str | None, notes: list[str]) -> str:
    now = pd.Timestamp.now(tz="UTC").floor("s")
    disk = shutil.disk_usage(BASE)
    services = {s: _sh("systemctl", "is-active", s) for s in ("tql-paper", "tql-live", "tql-daily.timer")}
    live_cmd = _sh("systemctl", "show", "tql-live", "-p", "ExecStart", "--value")
    live_cmd = live_cmd.split("argv[]=")[-1].split(";")[0].strip() if "argv[]=" in live_cmd else live_cmd
    parts = [f"# Server status, {now.isoformat()}", "",
             f"Code: `{_sh('git', '-C', str(BASE), 'log', '-1', '--format=%h %s', '--', '.', ':!market_history')}`  ",
             f"Disk free: {disk.free / 2**30:.1f} GB  ",
             "Services: " + ", ".join(f"{k} {v}" for k, v in services.items()) + "  ",
             f"Live logger command: `{live_cmd}`  ",
             f"Live polling gap (median seconds between a match's rows, latest day): {poll_gap()}", ""]
    if tests is not None:
        parts += [f"Tests ({'pass' if tests_rc == '0' else 'FAIL'}): `{tests}`", ""]
    parts += ["## Problems", ""] + ([f"- {n}" for n in notes] or ["- none"]) + [""]
    parts += ["## Live score log (last 7 days)", "", "| day | rows | matches |", "|---|---|---|"] + live_days() + [""]
    parts += ["## Registered forward tests (paper)", ""] + registrations() + [""]
    parts += ["## Paper market-making (settled markets)", ""] + paper_summary() + [""]
    if settle and Path(settle).exists():
        parts += ["Settle output:", "```", settle_text(Path(settle).read_text()), "```", ""]
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
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
