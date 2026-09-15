# Tennis Quant Lab V5 — Superpowers Supersession Map

Use this file when reading older dated documents. It identifies subjects whose historical plans/specs must be interpreted through the current architecture.

| Subject | Current rule | Older-document trap to avoid |
|---|---|---|
| Product pipeline | One canonical refresh → forecast → repricing → official ledger → settlement → performance → UI chain | Treating scripts/pages as independent production paths |
| Daily UI | Full Daily Forecast Board **plus** separate Decision Feed | Replacing full board with card-only experience |
| Recommendation count | Multiple official markets per match allowed when independently qualified | Imposing one top bet per match |
| Recommendation history | Frozen/immutable official recommendation-time state | Repricing or later board state rewriting official history |
| Ancillary selections | Remain auditable/tracked outside official performance | Dropping them when day changes |
| Court conditions | Nonblocking enrichment; fresh source → canonical schedule/file → optional manual → fallback → unknown | CourtSpeed/manual entry as hard dependency |
| Missing court state | Explicit unknown/no condition adjustment when unresolved | Inventing a condition merely to keep pipeline alive |
| Court source health | Separate from overall production readiness | Treating no live coverage as total production failure |
| Indian Wells identity | Indian Wells / Indian Wells Open alias to canonical BNP Paribas Open | Creating duplicate same-tour tournaments |
| Context warehouse publish | Sync/rebase before generation, then build/verify/publish | Pull/rebase after generated tracked files dirty worktree |
| Model evolution | Chronological OOS evidence required | Reactive tuning to recent outcomes or newly available fields |
| Streamlit | Consumer of canonical artifacts | Heavy upstream rebuilds on page load |
| Completion | CI + relevant end-to-end production verification | Declaring production fixed from code/tests alone |

## Reading order

1. `PROJECT_MANDATE.md`
2. `docs/superpowers/CURRENT_ARCHITECTURE.md`
3. this supersession map
4. relevant dated spec(s)
5. relevant dated plan(s)
6. current production implementation/artifacts

If a dated document conflicts with the current rule above, do not implement the older behavior. Investigate the later merged architecture and update the current docs if necessary.