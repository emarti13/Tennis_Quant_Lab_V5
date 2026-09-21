# V5 Preflight Data and Model Readiness Audit

Date: 2026-09-21
Status: BLOCKING PRECHECK BEFORE MARKET-AWARE BUILD CONTINUES

## Purpose
Verify that the independent tennis model has the data, feature contracts, validation evidence, and production parity needed before the market-aware decision layer is built. This audit prevents downstream work from hiding missing tennis inputs or forcing later backtracking.

## Evidence inspected
- Full-context tennis model design.
- Stage-1 context warehouse acceptance evidence.
- Current production winner candidate.
- Current production score candidate.
- Current state builder and live full-context adapter.
- Current 2025/2026 context acceptance report.
- Existing walk-forward/OOF enforcement.

## Readiness matrix

| Area | Status | Evidence / finding | Required action before decision-layer cutover |
|---|---|---|---|
| Overall Elo | READY | State builder maintains chronological Elo; live/batch prediction consumes Elo-derived probability. | Preserve and include in parity tests. |
| Surface Elo | READY | State builder maintains surface Elo; production baseline blends overall and surface Elo. | Preserve and verify current-state freshness. |
| Serve/return strength | READY | Dynamic serve/return state exists; accepted model exposes x_sr_a and serve/return context features. | Preserve and verify source refresh coverage. |
| First/second serve performance | READY | Canonical warehouse preserves serve statistics; production candidate includes ctx_serve_first_won_diff and ctx_serve_second_won_diff. | Coverage QC by tour/year. |
| Ace / double-fault | READY | Production candidate includes ctx_ace_rate_diff and ctx_double_fault_rate_diff. | Coverage QC by tour/year. |
| Return strength | READY | Production candidate includes ctx_return_strength_diff / return dominance. | Coverage QC by tour/year. |
| Ranking | READY | Warehouse preserves ranking; production candidate includes ctx_rank_diff. | Verify current fixture rank population. |
| Recent form / trajectory | READY | State builder emits form/volatility/confidence; production context includes trajectory serve/return and comeback/layoff features. | Verify live parity and missingness. |
| Rest / workload | READY | Production candidate includes rest buckets/log-rest, matches/games windows, consecutive days, prior match workload, minutes where available. | Verify no missing duration is converted to zero. |
| Travel / timezone | PARTIAL | Production candidate includes travel_km, travel/rest, timezone-change and altitude-change interactions. Historical architecture supports registry enrichment. | Verify canonical venue registry coverage and production tournament-ID mapping. |
| Surface | READY WITH QC | Canonical history has surface; current production resolves CourtSpeed/V5 fallback. Historical Stage-1 had 1,076 missing surfaces of 185,005. | Quantify current unresolved rate; never silently default unknown historical surface without flagging. |
| Court speed / environment | PARTIAL | Court-condition adapter and court-speed interactions exist. External CPI/ace/rally/RAD/ball fields exist. | Verify current master tournament coverage and source-year/freshness. |
| Altitude | PARTIAL | Altitude and altitude interactions exist. | Canonical venue mapping/coverage audit required. |
| Weather | DEFERRED | Historical context report shows ~32.9% weather coverage; live weather was intentionally disabled pending authoritative venue coordinates/timezone. | Do not treat weather as required production input until venue authority is complete and revalidated. |
| Tournament tier / round | PRESENT IN RAW CONTRACT, NOT PROVEN ACTIVE | Warehouse/spec includes round/tournament context, but current accepted production winner feature list does not demonstrate tier/round as active features. | Audit whether candidate testing rejected them or they were never fully evaluated. |
| Best-of | READY FOR SCORE PATH | Score candidate explicitly segments Bo3/Bo5; MEN validation contains both. | Keep explicit. |
| Player age / hand / height | PRESENT IN WAREHOUSE, NOT PROVEN ACTIVE | Stage-1 acceptance verifies preservation, but current production candidate feature list does not use them. | Determine whether evaluated/rejected vs simply unused; no blind addition. |
| H2H | NOT PROVEN ACTIVE | Current production candidate feature list does not show H2H. | Determine whether historical H2H was evaluated. Add only through walk-forward challenger test if not. |
| Player state confidence / uncertainty | READY | State confidence and context/state uncertainty are present and used in production diagnostics/candidate. | Preserve as explicit reliability input. |
| Model disagreement | READY | Full-context architecture and production candidate expose multiple component probabilities and component spread/std. | Preserve for reliability layer. |
| Score/margin distribution | READY, NEEDS RECALIBRATION WORK LATER | Accepted score candidate exists; MEN conditioned mechanistic and WTA gaussian contextual paths have chronological validation metrics. | Phase H/I will calibrate exact spread/total lines. |
| Historical breadth | READY FOUNDATION | Stage-1 accepted 185,005 matches / 370,010 player rows from 2010-2025 cached sources: ATP, qualifying, Challenger, WTA. | Verify 2026 append/current refresh is complete before new research dataset build. |
| Walk-forward / OOF protection | READY | Residual model explicitly accepts only OOF/walk-forward origins; acceptance artifacts use chronological validation. | Make this a hard invariant in all new joins. |
| Market independence | READY | Current tennis architecture prohibits sportsbook prices from tennis-state/model fitting; score candidate records market_prices_used=false. | Preserve. |
| Fixture identity / timestamp | PARTIAL | Stage-1 notes exact start time and OddsPapi fixture identity are downstream joins; live fixture IDs exist. | Audit historical fixture join coverage before market dataset join. |
| Tournament venue lat/lon/timezone | NOT YET VERIFIED COMPLETE | Architecture requires them; current repo search did not establish a complete authoritative master mapping. | Blocking for weather; important QC for travel/altitude. |
| 2026 current-source completeness | NOT YET VERIFIED | State builder lists 2026 ATP, qualifying, Challenger, WTA and ongoing files, but presence is not equivalent to complete/current coverage. | Run file/date/row/duplicate/gap audit. |

## Current conclusion
The core independent predictive foundation is present: chronological overall/surface Elo, serve-return state, rank, form/trajectory, workload/rest, player uncertainty, contextual winner model, and score distributions all exist with accepted validation artifacts.

The repository is **not yet certified data-complete** for the next layer. The remaining work is primarily data-contract and coverage verification rather than rebuilding the tennis model.

### Blocking checks before Task 1 market normalization continues
1. Current-source inventory: confirm every expected ATP/WTA/qualifying/Challenger/ongoing source exists, latest match date, row count, duplicate rate, and schema.
2. State freshness: rebuild/inspect MEN and WTA rating states and confirm Elo/surface-Elo/serve-return/current-state coverage for today's fixture population.
3. 2026 warehouse continuity: prove the accepted 2010-2025 warehouse is correctly extended through current 2026 data.
4. Feature coverage: calculate non-missing/finite coverage by year and tour for every feature actually consumed by the accepted winner and score candidates.
5. Venue authority: quantify canonical tournament mapping, surface, environment, altitude, latitude, longitude, and timezone coverage. Weather remains deferred until this passes.
6. Fixture identity: quantify historical match-to-OddsPapi fixture join coverage and ambiguity before market data are joined.
7. Dormant-feature disposition: explicitly classify H2H, age, hand, height, tournament tier, and round as previously tested/rejected, available-but-untested, or unavailable. Do not silently add them.
8. Leakage/parity tests: prove historical replay and live feature generation use the same as-of rules and no post-match fields.
9. Produce a machine-readable preflight report with PASS/PARTIAL/FAIL and block downstream training on unresolved FAIL items.

## Rule
No new market-aware meta-model training begins until this preflight is green for all required inputs. PARTIAL optional context may remain only when it has explicit missingness/quality handling and was validated that way.


## 2026-09-21 court-data reset
Existing/legacy court-characteristics enrichment is retired from the readiness baseline at user direction. It must not be used to satisfy preflight coverage or as fallback data. This includes legacy court altitude, court setting/environment, court speed/CPI, ball characteristics, ace/rally court characteristics, relative-air-density court fields, and reconciled derivatives whose authority depends on the retired court table.

A new user-supplied court table will be audited as a new authoritative source before any court-specific feature is reintroduced. Until that audit passes:
- court-specific inputs are DEFERRED, not FAIL, for the independent-tennis preflight;
- no legacy court value may silently populate historical or live rows;
- no market-aware work may depend on a court-specific field;
- Elo, surface Elo, serve/return, ranking, form/state, workload/rest, schedule surface, and other non-court model inputs remain in scope;
- latitude, longitude, timezone, and authoritative venue/location data supplied independently of the retired court table remain eligible for their own provenance audit.

This reset changes data authority, not the accepted predictive model coefficients. Any eventual reintroduction of new court features requires chronological challenger validation rather than automatic substitution into the existing model.


## Preflight execution update — source/state/warehouse audit
Repository evidence was checked against the current production artifacts on 2026-09-21.

### Current-source refresh — PASS
The latest recorded refresh completed successfully at 2026-09-21T12:16:48Z. Every 2026/current source reports 50 columns, no missing required columns, no warnings, and hard_fail=false:
- 2026 ATP main: 2,132 rows.
- 2026 ATP qualifying: 1,105 rows.
- 2026 Challenger: 5,790 rows.
- 2026 WTA: 2,095 rows.
- ongoing ATP/main: 58 rows.
- ongoing Challenger: 0 rows (valid schema, not treated as missing).
- ongoing WTA: 11 rows.
The resulting combined results cache is READY with 11,189 rows.

### Chronological state build — PASS
The same successful refresh rebuilt states after source refresh:
- MEN source rows before deduplication: 151,696; after deduplication: 151,693; chronological matches processed: 151,569; current players: 4,344; persisted rating rows: 13,032.
- WTA source rows: 44,500; chronological matches processed: 44,500; current players: 1,686; persisted rating rows: 5,058.
This proves the current state artifacts were regenerated from the refreshed source set; fixture-player coverage still requires a fixture-level audit rather than being inferred from successful state generation.

### Canonical context warehouse continuity — PARTIAL / STALE
The persisted warehouse does contain 2026 and all four expected 2026 source families with no missing/failed source files in its manifest. It contains 10,935 canonical 2026 matches and reports broad stat coverage. However, its persisted date_max is 2026-09-07 while the current source/state refresh is 2026-09-21. Therefore the warehouse is not certified current and must be refreshed/audited before downstream historical/live parity or new decision-model training.

The current warehouse schema contains match identity, tour/date/tournament/round/surface/best-of/result, score outcomes, rank, match duration, serve stats, return-derived stats, player/opponent identity and role. Its feature namespace explicitly reserves feature_* for pre-first-serve information.

### Dormant player/tournament features — classification tightened
The persisted canonical warehouse schema does not contain player age, hand, height, or H2H fields. The accepted winner/score candidate feature lists inspected for this preflight also do not establish those fields as active inputs. They are therefore NOT ACTIVE IN THE CURRENT ACCEPTED CONTRACT; repository evidence inspected so far does not support calling them previously rejected. Tournament round is stored in the canonical warehouse but is not established as an active accepted-model feature. Tournament tier/level is not part of the persisted canonical schema shown here. Any of these fields can only enter later as separately sourced chronological challenger features; none is a blocker for reproducing the accepted non-court model.

### Court reset interaction
No legacy court field is allowed to turn the above PASS/PARTIAL findings green. Court-specific enrichment remains deferred until the new authoritative court table is supplied and audited.
