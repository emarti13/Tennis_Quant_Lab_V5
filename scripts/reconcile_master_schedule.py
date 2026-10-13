"""Reconcile the master schedule with TennisMyLife and OddsPapi for one season.

Usage:
    python scripts/reconcile_master_schedule.py \
        --sheet context_registry/master_schedule/master_schedule_2026.csv \
        --year 2026 --as-of 2026-10-12

Writes context_registry/master_schedule/reconciliation/<year>/:
    master_schedule.csv        normalized sheet (UTF-8, ISO dates, flags)
    sheet_issues.csv           every problem found in the sheet
    oddspapi_matches.csv       each OddsPapi tournament block -> edition (or why not)
    tennismylife_matches.csv   each TennisMyLife tournament -> edition (or why not)
    confirmation.csv           each matched tournament checked against the other source's matches
    REPORT.md                  summary and the review list
Also updates the stored crosswalks (context_registry/master_schedule/crosswalk_<source>.csv):
confirmed, user and rejected rows are kept; the rest are re-decided from this run.
Nothing in production reads the crosswalks yet.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from v5_tournament_identity import (  # noqa: E402
    build_crosswalk,
    confirm_matches,
    enrich_locations,
    load_crosswalk,
    load_countries,
    load_master_schedule,
    match_source,
    oddspapi_tournaments,
    tennismylife_tournaments,
)


def _table(frame: pd.DataFrame, cols: list[str]) -> str:
    if frame.empty:
        return "_None._\n"
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in frame[cols].iterrows():
        lines.append("| " + " | ".join(str(r[c]).replace("|", "/") for c in cols) + " |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--as-of", required=True, help="Editions starting after this date are not expected in results yet.")
    ap.add_argument("--fixtures", default="oddspapi_registry/fixtures.csv")
    ap.add_argument("--results", default="v5_results_ready/tennismylife_results.csv")
    ap.add_argument("--out", default=None)
    ap.add_argument("--geocode-cache", default="context_registry/master_schedule/geocode_cache.csv",
                    help="Filled by scripts/geocode_master_schedule.py; missing cache means locations stay empty.")
    ap.add_argument("--crosswalk-dir", default="context_registry/master_schedule")
    args = ap.parse_args()

    out = Path(args.out or f"context_registry/master_schedule/reconciliation/{args.year}")
    out.mkdir(parents=True, exist_ok=True)

    editions, issues = load_master_schedule(args.sheet)
    cache_path = Path(args.geocode_cache)
    cache = pd.read_csv(cache_path, dtype=str, keep_default_na=False) if cache_path.exists() else pd.DataFrame(columns=["location_key", "results_json"])
    alias_path = Path("context_registry/master_schedule/location_aliases.csv")
    aliases = pd.read_csv(alias_path, dtype=str, keep_default_na=False) if alias_path.exists() else None
    editions, loc_issues = enrich_locations(editions, cache, load_countries(), aliases=aliases)
    issues += loc_issues
    odds = oddspapi_tournaments(pd.read_csv(args.fixtures, low_memory=False), args.year)
    tml = tennismylife_tournaments(pd.read_csv(args.results, low_memory=False), args.year)
    om = match_source(odds, editions)
    tm = match_source(tml, editions)
    oc = confirm_matches(odds, om, tml, tm)
    tc = confirm_matches(tml, tm, odds, om)
    xdir = Path(args.crosswalk_dir)
    crosswalks, drifts = {}, {}
    for name, matches, conf in (("oddspapi", om, oc), ("tennismylife", tm, tc)):
        path = xdir / f"crosswalk_{name}.csv"
        crosswalks[name], drifts[name] = build_crosswalk(matches, conf, load_crosswalk(path), set_on=args.as_of)
        crosswalks[name].to_csv(path, index=False, encoding="utf-8")

    issues_df = pd.DataFrame([i.__dict__ for i in issues])
    editions.to_csv(out / "master_schedule.csv", index=False, encoding="utf-8")
    issues_df.to_csv(out / "sheet_issues.csv", index=False, encoding="utf-8")
    om.to_csv(out / "oddspapi_matches.csv", index=False, encoding="utf-8")
    tm.to_csv(out / "tennismylife_matches.csv", index=False, encoding="utf-8")
    pd.concat([oc.assign(source="oddspapi"), tc.assign(source="tennismylife")]).to_csv(
        out / "confirmation.csv", index=False, encoding="utf-8")

    # Editions that should have been seen by now but no source matched.
    as_of = pd.Timestamp(args.as_of)
    seen = set(om.loc[om.status == "matched", "edition_key"]) | set(tm.loc[tm.status == "matched", "edition_key"])
    past = editions[(pd.to_datetime(editions.end_date) < as_of)]
    unseen = past[~past.edition_key.isin(seen)]
    cancelled_seen = editions[(editions.status == "cancelled")]
    multi_tml = tm[tm.status == "matched"].groupby("edition_key").source_id.unique()
    multi_tml = multi_tml[multi_tml.map(len) > 1]
    surf = tm[(tm.status == "matched") & (tm.source_surface != "") & (tm.source_surface != tm.sheet_surface)]
    names = {**dict(zip(odds.source_id, odds.name)), **dict(zip(tml.source_id, tml.name))}
    checks = pd.concat([oc.assign(source="oddspapi"), tc.assign(source="tennismylife")], ignore_index=True)
    checks["source_name"] = checks["source_id"].map(names)
    flagged = checks[checks.confirmation.isin(["conflict", "unconfirmed"])].sort_values(["confirmation", "source_id"])
    xw = pd.concat([crosswalks["oddspapi"], crosswalks["tennismylife"]], ignore_index=True)
    drift = pd.concat([drifts["oddspapi"], drifts["tennismylife"]], ignore_index=True)
    orphan = xw[(xw.edition_key != "") & ~xw.edition_key.isin(editions.edition_key)]

    sev = Counter((i.severity, i.message.split(";")[0].split(" (")[0]) for i in issues)
    r = [f"# Master schedule reconciliation, {args.year}", "",
         f"Sheet: `{args.sheet}` · as of {args.as_of} · generated by `scripts/reconcile_master_schedule.py`.", "",
         "## Summary", "",
         f"- Sheet: {len(editions)} editions ({editions.tour_family.value_counts().to_dict()}); "
         f"status {editions.status.value_counts().to_dict()}.",
         f"- OddsPapi: {len(om)} tournament blocks → {om.status.value_counts().to_dict()}.",
         f"- TennisMyLife: {len(tm)} tournaments (Davis Cup ties excluded) → {tm.status.value_counts().to_dict()}.",
         f"- Confirmation by shared matches (same two players in both sources): OddsPapi "
         f"{oc.confirmation.value_counts().to_dict()}; TennisMyLife {tc.confirmation.value_counts().to_dict()}.",
         f"- Crosswalks: OddsPapi {crosswalks['oddspapi'].status.value_counts().to_dict()}; "
         f"TennisMyLife {crosswalks['tennismylife'].status.value_counts().to_dict()}.",
         f"- Past editions (ended before {args.as_of}) with no match from either source: {len(unseen)}.",
         f"- Locations: {editions.location_source.value_counts().to_dict()}; time zone filled for "
         f"{(editions.time_zone != '').sum()} of {len(editions)} editions.",
         "", "## Sheet issues (counts)", "",
         _table(pd.DataFrame([{"severity": k[0], "issue": k[1], "rows": v} for k, v in sev.most_common()]), ["severity", "issue", "rows"]),
         "Details per row: `sheet_issues.csv`.", "",
         "## Review list", "",
         "### TennisMyLife tournaments not matched to exactly one edition", "",
         _table(tm[tm.status != "matched"], ["source_id", "source_name", "family", "first_date", "status", "candidates"]),
         "### OddsPapi tournament blocks not matched to exactly one edition", "",
         _table(om[om.status != "matched"], ["source_id", "source_name", "family", "first_date", "status", "candidates"]),
         "### Editions with more than one TennisMyLife tournament", "",
         _table(pd.DataFrame({"edition_key": multi_tml.index, "tennismylife_ids": [", ".join(v) for v in multi_tml.values]}), ["edition_key", "tennismylife_ids"]),
         "### Matches the other source does not confirm", "",
         "conflict: the other source's results point to a different tournament, so the mapping is held for review "
         "and gives no price. unconfirmed: too few shared matches to tell (a fragment, or an event still running); "
         "the mapping stays usable.", "",
         _table(flagged, ["source", "source_id", "source_name", "edition_key", "confirmation",
                          "pairs_same_edition", "pairs_best_other", "best_other"]),
         "### Stored mappings the fresh run would change", "",
         "Confirmed and user rows are never changed automatically. Check each one.", "",
         _table(drift, ["source_id", "stored", "fresh", "fresh_status"]),
         "### Stored mappings to editions no longer in the sheet", "",
         "A renamed or re-dated sheet row changes its edition key. Re-point these rows.", "",
         _table(orphan, ["source", "source_id", "source_name", "edition_key", "status"]),
         "### Surface disagreements (TennisMyLife vs sheet)", "",
         _table(surf, ["source_id", "source_name", "first_date", "source_surface", "sheet_row", "sheet_name", "sheet_surface"]),
         f"### Past editions no source matched (ended before {args.as_of})", "",
         _table(unseen, ["sheet_row", "tour_family", "tournament_name", "city", "start_date", "status"]),
         "### Locations to check", "",
         "Coordinates, altitude and time zone come from Open-Meteo geocoding unless the sheet has them. "
         "Fix a row by correcting City/State/Country or by typing Latitude, Longitude and Time Zone into the sheet.", "",
         _table(pd.DataFrame([i.__dict__ for i in loc_issues]) if loc_issues else pd.DataFrame(),
                ["row", "field", "message"]),
         "### Cancelled in the sheet", "",
         "Check against the OddsPapi list above: a cancelled event with OddsPapi fixtures needs a decision.", "",
         _table(cancelled_seen, ["sheet_row", "tournament_name", "city", "start_date"]),
         ]
    (out / "REPORT.md").write_text("\n".join(r), encoding="utf-8")
    print(f"Wrote {out}/REPORT.md")
    print(f"OddsPapi {om.status.value_counts().to_dict()} · TennisMyLife {tm.status.value_counts().to_dict()} · "
          f"not confirmed {len(flagged)} · unseen past editions {len(unseen)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
