#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

from oddspapi_client import OddsPapiClient
from historical_odds_normalizer import flatten_history
from historical_market_mapper import map_snapshot_rows
from pull_oddspapi_quota_aware import relevant_fixture

BASE = Path(__file__).resolve().parents[1]
FIXTURE_INDEX = BASE / "oddspapi_history" / "fixtures_2026.jsonl"
REGISTRY = BASE / "oddspapi_registry" / "fixtures.csv"
LEGACY_CHUNKS = BASE / "oddspapi_history" / "chunks"
PINNACLE_CHUNKS = BASE / "oddspapi_history" / "pinnacle_2026_chunks"
LEGACY_CHECKPOINT = BASE / "oddspapi_history" / "historical_checkpoint.json"
CHECKPOINT = BASE / "market_warehouse" / "pinnacle_closing_2026_checkpoint.json"
META = BASE / "oddspapi_markets_tennis.json"
OUTDIR = BASE / "market_warehouse"
ALL_CLOSES = OUTDIR / "pinnacle_closing_2026.csv"
MONEYLINE_CLOSES = OUTDIR / "pinnacle_closing_2026_moneyline.csv"
QC = OUTDIR / "pinnacle_closing_2026_qc.json"

BOOK = "pinnacle"
COOLDOWN_SECONDS = 5.1


def _parse_dt(value):
    if value is None or not str(value).strip():
        return None
    try:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fixture_from_registry(row: dict) -> dict:
    return {
        "fixtureId": row.get("fixture_id"),
        "startTime": row.get("start_time_utc"),
        "trueStartTime": row.get("true_start_time_utc"),
        "trueEndTime": row.get("true_end_time_utc"),
        "participant1Id": row.get("participant1_id"),
        "participant1Name": row.get("participant1_name"),
        "participant2Id": row.get("participant2_id"),
        "participant2Name": row.get("participant2_name"),
        "sportId": row.get("sport_id"),
        "tournamentId": row.get("tournament_id"),
        "tournamentName": row.get("tournament_name"),
        "tournamentSlug": row.get("tournament_slug"),
        "categoryName": row.get("category_name"),
        "categorySlug": row.get("category_slug"),
        "seasonId": row.get("season_id"),
        "statusId": row.get("status_id"),
        "statusName": row.get("status_name"),
        "hasOdds": row.get("has_odds"),
    }


def load_candidates(now: datetime) -> dict[str, dict]:
    by_id: dict[str, dict] = {}
    if FIXTURE_INDEX.exists():
        for line in FIXTURE_INDEX.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            fixture = json.loads(line)
            fid = str(fixture.get("fixtureId") or "")
            if fid:
                by_id[fid] = fixture

    if REGISTRY.exists():
        with REGISTRY.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                fixture = _fixture_from_registry(row)
                fid = str(fixture.get("fixtureId") or "")
                if not fid:
                    continue
                if fid in by_id:
                    current = by_id[fid]
                    for key, value in fixture.items():
                        if value not in (None, ""):
                            current[key] = value
                else:
                    by_id[fid] = fixture

    eligible = {}
    for fid, fixture in by_id.items():
        start = _parse_dt(fixture.get("startTime"))
        if start is None or start.year != 2026 or start >= now:
            continue
        try:
            if not relevant_fixture(fixture):
                continue
        except Exception:
            continue
        eligible[fid] = fixture
    return eligible


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def legacy_terminal_not_found() -> set[str]:
    cp = load_json(LEGACY_CHECKPOINT, {})
    out = set()
    explicit = cp.get("terminal_not_found_by_bookset") or {}
    for bookset, ids in explicit.items():
        if "pinnacle" in str(bookset).lower():
            out.update(str(x) for x in ids)
    for fid, error in (cp.get("failed") or {}).items():
        text = str(error).lower()
        if "no historical odds found" in text and "pinnacle" in str(cp.get("historical_bookset","pinnacle")).lower():
            out.add(str(fid))
    return out


def iter_cached_payloads():
    paths = []
    if LEGACY_CHUNKS.exists():
        paths.extend(sorted(LEGACY_CHUNKS.glob("history_chunk_*.jsonl.gz")))
    if PINNACLE_CHUNKS.exists():
        paths.extend(sorted(PINNACLE_CHUNKS.glob("pinnacle_chunk_*.jsonl.gz")))
    for path in paths:
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    payload = item.get("historical_odds") or {}
                    fixture = item.get("fixture") or {}
                    fid = str(payload.get("fixtureId") or fixture.get("fixtureId") or "")
                    if fid:
                        yield fid, fixture, payload
        except (OSError, EOFError, json.JSONDecodeError):
            continue


def choose_closing_rows(payload: dict, fixture: dict, market_meta: list[dict]) -> tuple[list[dict], set[str]]:
    books = payload.get("bookmakers") or {}
    pinnacle = books.get(BOOK)
    if not isinstance(pinnacle, dict):
        return [], set()

    cutoff = _parse_dt(fixture.get("trueStartTime")) or _parse_dt(fixture.get("startTime"))
    if cutoff is None:
        return [], set()

    rows = [r for r in flatten_history(payload) if str(r.get("bookmaker")).lower() == BOOK]
    best = {}
    for row in rows:
        created = _parse_dt(row.get("created_at"))
        if created is None or created >= cutoff:
            continue
        # A final suspended/inactive record is not a tradable closing price.
        if row.get("active") is False:
            continue
        key = (row.get("market_id"), row.get("outcome_id"), row.get("player_id"))
        prior = best.get(key)
        if prior is None or created > _parse_dt(prior.get("created_at")):
            x = dict(row)
            x["created_at"] = created
            x["snapshot_label"] = "close"
            x["cutoff_utc"] = cutoff
            best[key] = x

    selected = list(best.values())
    mapped = map_snapshot_rows(selected, fixture, market_meta)
    mapped_keys = set()
    output = []
    for row in mapped:
        created = _parse_dt(row.get("created_at"))
        mapped_keys.add(str(row.get("market_id")))
        x = dict(row)
        x["created_at"] = created.isoformat() if created else ""
        x["cutoff_utc"] = cutoff.isoformat()
        x["scheduled_start_utc"] = fixture.get("startTime")
        x["true_start_time_utc"] = fixture.get("trueStartTime")
        x["close_cutoff_source"] = "trueStartTime" if _parse_dt(fixture.get("trueStartTime")) else "startTime"
        x["seconds_before_cutoff"] = (cutoff - created).total_seconds() if created else None
        x["tournament_id"] = fixture.get("tournamentId")
        x["participant1_id"] = fixture.get("participant1Id")
        x["participant2_id"] = fixture.get("participant2Id")
        output.append(x)
    return output, mapped_keys


def next_chunk_number() -> int:
    PINNACLE_CHUNKS.mkdir(parents=True, exist_ok=True)
    nums = []
    for path in PINNACLE_CHUNKS.glob("pinnacle_chunk_*.jsonl.gz"):
        try:
            nums.append(int(path.stem.split("_")[-1].split(".")[0]))
        except Exception:
            pass
    return max(nums, default=0) + 1


def is_not_found(exc: Exception) -> bool:
    t = str(exc).lower()
    return "no historical odds found" in t or ("not_found" in t and "historical" in t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-size", type=int, default=500)
    ap.add_argument("--cooldown", type=float, default=COOLDOWN_SECONDS)
    args = ap.parse_args()

    if not META.exists():
        raise RuntimeError("Missing cached oddspapi_markets_tennis.json; refusing a billable metadata fetch.")
    market_meta = json.loads(META.read_text(encoding="utf-8"))
    if not isinstance(market_meta, list):
        raise RuntimeError("OddsPapi market metadata cache is malformed.")

    now = datetime.now(timezone.utc)
    candidates = load_candidates(now)
    checkpoint = load_json(CHECKPOINT, {
        "terminal_not_found": [],
        "no_pinnacle_history": [],
        "retryable_failures": {},
        "updated_at_utc": None,
    })
    terminal = legacy_terminal_not_found() | set(str(x) for x in checkpoint.get("terminal_not_found", []))
    no_pinnacle = set(str(x) for x in checkpoint.get("no_pinnacle_history", []))
    retryable = dict(checkpoint.get("retryable_failures") or {})

    closing_by_key = {}
    cached_pinnacle_ids = set()
    payload_fixture_overrides = {}
    unmapped_market_ids = set()

    for fid, fixture_from_chunk, payload in iter_cached_payloads():
        if fid not in candidates:
            continue
        books = payload.get("bookmakers") or {}
        if BOOK not in books:
            continue
        cached_pinnacle_ids.add(fid)
        fixture = dict(candidates[fid])
        for k, v in fixture_from_chunk.items():
            if v not in (None, ""):
                fixture[k] = v
        payload_fixture_overrides[fid] = fixture
        rows, mapped_ids = choose_closing_rows(payload, fixture, market_meta)
        for row in rows:
            key = (
                str(row.get("fixture_id")), str(row.get("market_group")),
                str(row.get("selection")), str(row.get("line")),
                str(row.get("market_id")), str(row.get("outcome_id")), str(row.get("player_id"))
            )
            closing_by_key[key] = row

    pending = [
        fid for fid in sorted(candidates, key=lambda x: (str(candidates[x].get("startTime") or ""), x))
        if fid not in cached_pinnacle_ids and fid not in terminal and fid not in no_pinnacle
    ]
    selected = pending[: max(0, int(args.batch_size))]
    chunk_path = None
    successes = 0
    not_found_now = 0
    no_pinnacle_now = 0
    stopped_on_quota = False

    if selected:
        chunk_no = next_chunk_number()
        chunk_path = PINNACLE_CHUNKS / f"pinnacle_chunk_{chunk_no:04d}.jsonl.gz"
        client = OddsPapiClient()
        with gzip.open(chunk_path, "wt", encoding="utf-8") as gz:
            for i, fid in enumerate(selected, 1):
                fixture = candidates[fid]
                try:
                    payload = client.historical_odds(fid, BOOK)
                    if not isinstance((payload.get("bookmakers") or {}).get(BOOK), dict):
                        no_pinnacle.add(fid)
                        no_pinnacle_now += 1
                    else:
                        gz.write(json.dumps({
                            "fixture": fixture,
                            "bookmakers_requested": [BOOK],
                            "historical_odds": payload,
                        }, separators=(",", ":"), ensure_ascii=False) + "\n")
                        cached_pinnacle_ids.add(fid)
                        rows, _ = choose_closing_rows(payload, fixture, market_meta)
                        for row in rows:
                            key = (
                                str(row.get("fixture_id")), str(row.get("market_group")),
                                str(row.get("selection")), str(row.get("line")),
                                str(row.get("market_id")), str(row.get("outcome_id")), str(row.get("player_id"))
                            )
                            closing_by_key[key] = row
                        successes += 1
                        retryable.pop(fid, None)
                except Exception as exc:
                    text = str(exc)
                    if is_not_found(exc):
                        terminal.add(fid)
                        not_found_now += 1
                        retryable.pop(fid, None)
                    else:
                        retryable[fid] = text
                        if "429" in text or "request limit exceeded" in text.lower():
                            stopped_on_quota = True
                            break
                if i < len(selected):
                    time.sleep(max(5.0, float(args.cooldown)))

    OUTDIR.mkdir(parents=True, exist_ok=True)
    rows = sorted(
        closing_by_key.values(),
        key=lambda r: (
            str(r.get("scheduled_start_utc") or ""),
            str(r.get("fixture_id") or ""),
            str(r.get("market_group") or ""),
            str(r.get("market_id") or ""),
            str(r.get("selection") or ""),
        )
    )
    fields = [
        "fixture_id","scheduled_start_utc","true_start_time_utc","close_cutoff_source",
        "cutoff_utc","created_at","seconds_before_cutoff","tournament_id","tournament","tour",
        "player1","player2","participant1_id","participant2_id","bookmaker","market_group",
        "market_id","market_name","period","outcome_id","player_id","selection","line",
        "price_decimal","raw_implied_prob","no_vig_prob","market_hold","limit","active","snapshot_label"
    ]
    with ALL_CLOSES.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)

    ml_rows = [r for r in rows if r.get("market_group") == "moneyline"]
    with MONEYLINE_CLOSES.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in ml_rows:
            w.writerow(row)

    resolved = cached_pinnacle_ids | terminal | no_pinnacle
    pending_after = [
        fid for fid in candidates
        if fid not in resolved
    ]
    by_group = {}
    for group in ("moneyline","game_spread","total_games"):
        group_rows = [r for r in rows if r.get("market_group") == group]
        by_group[group] = {
            "rows": len(group_rows),
            "fixtures": len({str(r.get("fixture_id")) for r in group_rows}),
        }

    checkpoint = {
        "terminal_not_found": sorted(terminal),
        "no_pinnacle_history": sorted(no_pinnacle),
        "retryable_failures": retryable,
        "updated_at_utc": now.isoformat(),
    }
    CHECKPOINT.write_text(json.dumps(checkpoint, indent=2, sort_keys=True), encoding="utf-8")

    qc = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "2026 relevant ATP/Challenger/WTA/WTA125/Grand Slam singles fixtures observed by OddsPapi through current repository fixture registry",
        "bookmaker": BOOK,
        "definition": "latest active Pinnacle quote strictly before trueStartTime when available, otherwise scheduled startTime",
        "fixture_candidates": len(candidates),
        "cached_pinnacle_histories": len(cached_pinnacle_ids),
        "terminal_no_history": len(terminal),
        "no_pinnacle_history": len(no_pinnacle),
        "retryable_failures": len(retryable),
        "pending_before_batch": len(pending),
        "batch_selected": len(selected),
        "batch_successes": successes,
        "batch_not_found": not_found_now,
        "batch_no_pinnacle": no_pinnacle_now,
        "stopped_on_quota_429": stopped_on_quota,
        "pending_after_batch": len(pending_after),
        "closing_rows": len(rows),
        "fixtures_with_any_closing_market": len({str(r.get("fixture_id")) for r in rows}),
        "market_groups": by_group,
        "raw_incremental_chunk": None if chunk_path is None else str(chunk_path.relative_to(BASE)),
        "complete_for_observed_fixtures": len(pending_after) == 0 and len(retryable) == 0,
        "credit_policy": "Only /v4/historical-odds is called by this backfill; that endpoint is free under OddsPapi v4 quota documentation.",
    }
    QC.write_text(json.dumps(qc, indent=2), encoding="utf-8")
    print(json.dumps(qc, indent=2))


if __name__ == "__main__":
    main()
