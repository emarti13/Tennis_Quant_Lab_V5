#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime, timezone
import csv, hashlib, json, shutil, urllib.request

ROOT=Path("model_input_inventory")
ROOT.mkdir(exist_ok=True)
for d in [
    "01_direct_runtime_inputs","02_upstream_daily_sources","03_model_configuration",
    "04_operational_audit","05_missing_expected_inputs","06_adjacent_not_direct"
]:
    (ROOT/d).mkdir(parents=True,exist_ok=True)

def copy_if_present(src,dest):
    s=Path(src); d=ROOT/dest
    if s.exists():
        d.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(s,d)
        return True
    return False

direct=[
("v5_market_ready/market_board_input.csv","v5_market_ready/market_board_input.csv"),
("v5_build_summary.json","v5_build_summary.json"),
("v5_men_ratings.csv","v5_men_ratings.csv"),
("v5_wta_ratings.csv","v5_wta_ratings.csv"),
("context_warehouse/player_match_rows.parquet","context_warehouse/player_match_rows.parquet"),
("context_registry/tournament_authority.csv","context_registry/tournament_authority.csv"),
("context_registry/player_aliases.csv","context_registry/player_aliases.csv"),
("experiments/acceptance/production_candidate.json","experiments/acceptance/production_candidate.json"),
("experiments/acceptance/score_production_candidate.json","experiments/acceptance/score_production_candidate.json"),
("context_registry/tournaments.csv","context_registry/tournaments.csv"),
("context_weather/weather_by_event_date.parquet","context_weather/weather_by_event_date.parquet"),
]
for src,dst in direct: copy_if_present(src,Path("01_direct_runtime_inputs")/dst)

upstream=[
("v5_results_ready/tennismylife_results.csv","v5_results_ready/tennismylife_results.csv"),
("v5_results_ready/results_status.json","v5_results_ready/results_status.json"),
("context_warehouse/matches.parquet","context_warehouse/matches.parquet"),
("context_warehouse/source_manifest.json","context_warehouse/source_manifest.json"),
("context_warehouse/schema.json","context_warehouse/schema.json"),
("v5_market_ready/all_book_prices.csv","v5_market_ready/all_book_prices.csv"),
("v5_market_ready/market_feed_qc.json","v5_market_ready/market_feed_qc.json"),
("oddspapi_registry/fixtures.csv","oddspapi_registry/fixtures.csv"),
("context_registry/tennis_master_schedule.csv","context_registry/tennis_master_schedule.csv"),
("v5_men_walkforward.csv","v5_men_walkforward.csv"),
("v5_wta_walkforward.csv","v5_wta_walkforward.csv"),
]
for src,dst in upstream: copy_if_present(src,Path("02_upstream_daily_sources")/dst)

config_files=[
"v5_model_calibration.py","v5_daily_batch.py","v5_full_context_live.py",
"build_v5_context_matchups.py","v5_rolling_stats.py","v5_workload_features.py",
"v5_travel_features.py","v5_player_state.py","v5_matchup_features.py",
"v5_advanced_model.py","v5_context_model.py","v5_score_distribution.py",
"v5_tournament_authority.py","v5_player_identity.py","build_v5_states.py",
"build_v5_context_warehouse.py","build_v5_market_board_input.py","normalize_oddspapi_snapshot.py"
]
for f in config_files: copy_if_present(f,Path("03_model_configuration")/f)

audit_files=[
("v5_refresh_last.json","v5_refresh_last.json"),
("context_warehouse/source_manifest.json","context_warehouse_source_manifest.json"),
("v5_market_ready/market_feed_qc.json","market_feed_qc.json"),
("v5_daily_ready/latest_summary.json","latest_summary.json"),
("v5_daily_ready/forecast_status.json","forecast_status.json"),
]
for src,dst in audit_files: copy_if_present(src,Path("04_operational_audit")/dst)

copy_if_present("v5_daily_ready/frozen_predictions.csv","06_adjacent_not_direct/frozen_predictions.csv")
copy_if_present("context_registry/tournament_authority.csv.csv","06_adjacent_not_direct/tournament_authority.csv.csv")

# Historical aggregate inputs restored by the player-rating workflow cache (2010-2025).
hist_cache=Path(".v5_history_cache")
for name in ("ATP.csv","ATPQualifiers.csv","Challenger.csv","WTA.csv"):
    src=hist_cache/name
    if src.exists():
        dst=ROOT/"02_upstream_daily_sources"/"historical_rating_aggregates"/name
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,dst)

expected=[
("v5_market_ready/market_board_input.csv","DIRECT","Fixture/player/tournament/start-time/market-line slate read by v5_daily_batch.py"),
("v5_build_summary.json","DIRECT","Surface serve baselines used by the base serve/return calculation"),
("v5_men_ratings.csv","DIRECT","Current MEN serve/return, Elo, surface Elo, form/state values"),
("v5_wta_ratings.csv","DIRECT","Current WTA serve/return, Elo, surface Elo, form/state values"),
("context_warehouse/player_match_rows.parquet","DIRECT","Historical player-match rows used to rebuild rolling/workload/context features live"),
("context_registry/tournament_authority.csv","DIRECT","Tournament identity and current surface/environment authority"),
("context_registry/player_aliases.csv","DIRECT","Verified player identity aliases"),
("experiments/acceptance/production_candidate.json","DIRECT","Winner context-model coefficients, scales and ensemble weights"),
("experiments/acceptance/score_production_candidate.json","DIRECT","Spread/total score-model candidate and coefficients"),
("context_registry/tournaments.csv","EXPECTED_DIRECT","Tournament registry passed to travel feature builder"),
("context_weather/weather_by_event_date.parquet","EXPECTED_DIRECT","Weather cache loaded by daily prediction"),
("v5_results_ready/tennismylife_results.csv","UPSTREAM","Canonical current TennisMyLife results snapshot feeding context warehouse"),
("context_warehouse/matches.parquet","UPSTREAM","Canonical match-level warehouse feeding player-match rows"),
("v5_market_ready/all_book_prices.csv","UPSTREAM","Normalized current book prices from OddsPapi; market_board_input is derived from this"),
("oddspapi_registry/fixtures.csv","UPSTREAM","Persisted OddsPapi fixture registry"),
("context_registry/tennis_master_schedule.csv","UPSTREAM","Canonical schedule source/supporting authority data"),
("v5_men_walkforward.csv","REFERENCE","Daily-refreshed MEN walk-forward output; not read by v5_daily_batch"),
("v5_wta_walkforward.csv","REFERENCE","Daily-refreshed WTA walk-forward output; not read by v5_daily_batch"),
(".v5_history_cache/ATP.csv","UPSTREAM_CACHE","Historical ATP main-tour aggregate (2010-2025) feeding daily ratings"),
(".v5_history_cache/ATPQualifiers.csv","UPSTREAM_CACHE","Historical ATP qualifying aggregate (2010-2025) feeding daily ratings"),
(".v5_history_cache/Challenger.csv","UPSTREAM_CACHE","Historical Challenger aggregate (2010-2025) feeding daily ratings"),
(".v5_history_cache/WTA.csv","UPSTREAM_CACHE","Historical WTA aggregate (2010-2025) feeding daily ratings"),
("v5_daily_ready/frozen_predictions.csv","OPERATIONAL","Read only to preserve prior frozen rows; does not set a new match probability"),
]

# Download current raw TennisMyLife feeds used by refresh_tennismylife_cloud.py.
target_aliases={}
for year in (2023,2024,2025,2026):
    for suffix in ("","_atp_quali","_challenger","_wta"):
        name=f"{year}{suffix}.csv"
        target_aliases[name]=[name]
target_aliases.update({
"ongoing_tourneys.csv":["ongoing_tourneys.csv"],
"challenger_ongoing_tourneys.csv":["challenger_ongoing_tourneys.csv","ch_ongoing_tourney.csv","challenger_ongoing_tourney.csv"],
"wta_ongoing_tourneys.csv":["wta_ongoing_tourneys.csv","wta_ongoing_tourney.csv"],
})
raw_dir=ROOT/"02_upstream_daily_sources"/"tennismylife_raw_current"
raw_dir.mkdir(parents=True,exist_ok=True)
raw_report={"manifest_url":"https://stats.tennismylife.org/api/data-files","downloaded":[],"missing":[]}
try:
    with urllib.request.urlopen(raw_report["manifest_url"],timeout=30) as resp:
        payload=json.loads(resp.read().decode("utf-8"))
    lookup={}
    for item in payload.get("files") or []:
        if not isinstance(item,dict): continue
        name=str(item.get("name") or "").replace("\\","/").lower()
        url=str(item.get("url") or "")
        if name and url:
            lookup[name]=item; lookup[name.split("/")[-1]]=item
    for local,aliases in target_aliases.items():
        hit=None
        for alias in aliases:
            hit=lookup.get(alias.lower())
            if hit: break
        if not hit:
            raw_report["missing"].append(local); continue
        out=raw_dir/local
        urllib.request.urlretrieve(hit["url"],out)
        raw_report["downloaded"].append({"file":local,"source_name":hit.get("name"),"source_url":hit.get("url"),"bytes":out.stat().st_size})
except Exception as exc:
    raw_report["error"]=f"{type(exc).__name__}: {exc}"
(raw_dir/"download_report.json").write_text(json.dumps(raw_report,indent=2),encoding="utf-8")

for path,kind,role in expected:
    if kind=="EXPECTED_DIRECT" and not Path(path).exists():
        marker=ROOT/"05_missing_expected_inputs"/(path.replace("/","__")+".MISSING.txt")
        marker.write_text(
            "Expected by current production code but absent from repository at inventory time.\n"
            f"Path: {path}\nRole: {role}\n",encoding="utf-8"
        )

rows=[]
for path,kind,role in expected:
    p=Path(path)
    rows.append({
        "repo_path":path,"classification":kind,"role":role,
        "present_on_main":p.exists(),"size_bytes":p.stat().st_size if p.exists() else ""
    })
with (ROOT/"inventory.csv").open("w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f,fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)

readme="# Tennis Quant Lab V5 — model input inventory\n\n"
readme+=f"Generated UTC: {datetime.now(timezone.utc).isoformat()}\n\n"
readme+="This bundle is an audit snapshot only. No production prediction logic was changed.\n\n"
readme+="## Directory meaning\n"
readme+="- 01_direct_runtime_inputs: persisted files the current daily prediction path reads directly.\n"
readme+="- 02_upstream_daily_sources: persisted/upstream snapshots that build the direct inputs, plus current raw TennisMyLife daily feeds.\n"
readme+="- 03_model_configuration: coefficients/config plus transformation code that gives the data its model meaning.\n"
readme+="- 04_operational_audit: freshness/QC/status files that can allow or block a daily run.\n"
readme+="- 05_missing_expected_inputs: explicit markers for paths current production code expects but that were absent at inventory time.\n"
readme+="- 06_adjacent_not_direct: operational/nearby files that do not set a new winner probability.\n\n"
readme+="## Lineage\n"
readme+="OddsPapi -> normalized/all-book prices -> market_board_input.csv -> fixture identity / requested lines -> daily forecast.\n"
readme+="TennisMyLife current feeds + historical cache -> ratings + canonical results -> context warehouse -> rolling/workload/context features.\n"
readme+="Tournament authority -> tournament identity + surface/environment.\n"
readme+="production_candidate.json -> final winner-context layer.\n"
readme+="score_production_candidate.json -> spread/total layer.\n\n"
readme+="Raw OddsPapi daily batch JSON is ephemeral in the workflow and is not retained on main. The promoted snapshot is represented here by all_book_prices.csv and market_board_input.csv.\n"
(ROOT/"README.md").write_text(readme,encoding="utf-8")

hashes=[]
for p in sorted(ROOT.rglob("*")):
    if p.is_file():
        h=hashlib.sha256()
        with p.open("rb") as fh:
            for chunk in iter(lambda:fh.read(1024*1024),b""): h.update(chunk)
        hashes.append({"bundle_path":str(p.relative_to(ROOT)),"size_bytes":p.stat().st_size,"sha256":h.hexdigest()})
with (ROOT/"file_hashes.csv").open("w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f,fieldnames=["bundle_path","size_bytes","sha256"]); w.writeheader(); w.writerows(hashes)

print(json.dumps({
    "bundle_files":len(hashes),
    "missing_expected":[x[0] for x in expected if x[1]=="EXPECTED_DIRECT" and not Path(x[0]).exists()],
    "tennismylife_raw":raw_report,
},indent=2))
