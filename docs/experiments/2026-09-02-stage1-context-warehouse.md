# Stage 1 Context Warehouse Acceptance Evidence

Date: 2026-09-02
Branch: `feature/full-context-stage1-warehouse`
Schema version: `1.1.0`
Status: **ACCEPTED ON BRANCH — production merge pending current-main integration check**

## Scope validated

Stage 1 establishes the canonical historical data foundation required by the approved full-context tennis architecture. It converts the four existing TennisMyLife aggregate source families into deterministic canonical match rows and exactly two player-match rows per match while preserving auditable source provenance and available player/match statistics.

No sportsbook price, no-vig probability, spread line, total line, or recommendation field enters the Stage 1 canonical tennis warehouse.

## TDD evidence

The implementation was developed through explicit RED/GREEN cycles in GitHub Actions:

- Initial contract RED: run `33612933786` failed with the expected missing `context_warehouse` import.
- Initial normalization GREEN: run `33613060755` passed.
- Durable-writer RED: run `33613156775` failed before `context_warehouse.io` existed.
- Durable-writer GREEN: run `33613227636` passed.
- CLI RED: run `33613322923` failed before `build_context_warehouse.py` existed.
- CLI GREEN: run `33613403802` passed.
- Player metadata/stat preservation RED: run `33613501531` failed before the expanded schema was implemented.
- Expanded schema/stat preservation GREEN: run `33613663110` passed.
- Canonical source-player-ID RED: run `33614054532` failed because numeric source IDs had not yet been normalized to strings.
- Canonical source-player-ID GREEN: run `33614150736` passed after normalization was moved to the ingestion boundary.

The unit/integration contract verifies deterministic match identity, date/surface normalization, preservation of missing ranks, exactly two player rows per match, source player IDs, hand/height/age/ranking metadata, detailed serve statistics, durable audit files, mixed MEN/WTA CLI ingestion, and absence of market fields.

## Real-history smoke evidence

Workflow: `Context Warehouse History Smoke`

First run `33613751901` intentionally exposed a real cross-file schema defect: PyArrow rejected mixed object types in `winner_source_player_id`. The workflow also exposed that its audit `tee` target could be opened before the output directory existed. The root cause was addressed by canonicalizing external player IDs as nullable strings at ingestion and explicitly creating the audit directory before the pipeline.

Verification run `33614185488` completed successfully end-to-end against the cached 2010–2025 TennisMyLife aggregates with `pandas`, `requests`, and `pyarrow` installed.

Validated output:

- Canonical matches: **185,005**
- Player-match rows: **370,010**
- MEN matches: **142,611**
- WTA matches: **42,394**
- ATP: **45,616**
- MEN qualifying: **23,459**
- Challenger: **73,536**
- WTA: **42,394**
- Hard: **101,014**
- Clay: **68,571**
- Grass: **13,362**
- Carpet: **982**
- Missing surface: **1,076**
- Parquet matches output: **success**
- Parquet player-match output: **success**
- Match IDs unique: **verified**
- Exactly two player rows per match: **verified**
- Market fields absent: **verified**

## Canonical outputs

The writer emits:

- `matches.csv`
- `player_match_rows.csv`
- `source_manifest.json`
- `schema.json`
- `matches.parquet` when a Parquet engine is available
- `player_match_rows.parquet` when a Parquet engine is available

Parquet is the preferred analytical representation; CSV/JSON remain the audit/debug fallback.

## Known Stage 1 limitations

These are deliberate downstream or source-availability items, not Stage 1 acceptance failures:

- Exact scheduled/actual first-serve timestamp is not supplied by the historical aggregate files and will require later fixture/context adapters where available.
- Venue coordinates, timezone, altitude, indoor/outdoor quality, weather and travel are Stage 2 metadata/enrichment responsibilities.
- Seed, qualifier/wildcard/lucky-loser labels are not yet normalized unless consistently present in a future source adapter.
- Provider/OddsPapi fixture identity belongs in the later fixture-registry join; sportsbook prices remain outside the tennis-state warehouse.
- Court speed is intentionally not computed in Stage 1. The accepted historical-prior/current-update amendment is downstream and depends on this historical warehouse plus strict as-of logic.

## Acceptance decision

**Stage 1 passes its branch acceptance gate.** The warehouse can reproducibly ingest the real historical source set, preserve the information required for later rolling serve/return and workload features, serialize to Parquet without mixed-type ambiguity, and maintain the independent-tennis/no-market boundary.

Before merging, compare against the then-current `main` because production workflows make autonomous settlement/refresh commits. Do not overwrite those commits; integrate Stage 1 forward from the live head.