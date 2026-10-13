# Tournament crosswalks and confirmation by shared matches (2026)

Date: 2026-10-12 · Rebuild plan Step 2 · Spec: tournament identity, amendment A (§2.8, approved 2026-10-13).
Data: OddsPapi `oddspapi_registry/fixtures.csv`, TennisMyLife `v5_results_ready/tennismylife_results.csv`,
master schedule `master_schedule_2026.csv` (441 editions). No model or pricing change; no market benchmark applies.

## Question

The user's concern: the sources name events differently ("Genoa 2" vs "Genoa (Nuova
Valletta)"), so same-city events are easy to mix up. Can mappings be stored safely, and
how do we know a stored mapping is right?

## Findings

1. **Names do not decide matches** (tour, then start date inside the edition's week, then
   city; names only break a remaining tie). 38 cities host more than one event on the
   same tour in 2026 (98 editions). All 77 OddsPapi blocks and all TennisMyLife
   tournaments for them matched one edition each.
2. **TennisMyLife reuses tourney ids.** `2026-2971` covers both San Diego Challengers
   (January and September); `2026-416` covers one Munich match and the whole Rome
   Masters. Before this change, San Diego 2 and Rome had no TennisMyLife match and the
   January San Diego player check was polluted. Fixed by splitting ids into date blocks
   (gap over 6 days), as OddsPapi ids already were.
3. **Shared players were a poor check.** 18 mappings fell below 80% player share; 16 were correct (the other two were the reused ids above).
   Causes: our OddsPapi collection gap (Sept 1–13: only part of each draw was collected),
   the week of Mar 30 (same pattern), events still running, and Grand Slam qualifying
   that contains most of the previous week's players (a wrong Slam↔Eastbourne pairing
   scored 100%).
4. **Shared matches are a strong check.** Same two players meeting in both sources:
   across 2,998 wrong same-tour pairings within ±8 days, 2,855 share no match and the
   maximum is 5 (Abidjan 1/2, Asuncion/Tucumán: players meeting again a week later).
   Correct mappings share a median of 31. The rule is therefore relative (§2.8): at least
   3 shared and at least twice any neighbour.

## Result (2026)

| | confirmed | conflict | unconfirmed | no results yet |
|---|---|---|---|---|
| OddsPapi blocks (359 matched) | 284 | 0 | 4 | 71 |
| TennisMyLife blocks (293 matched) | 283 | 0 | 2 | 8 |

Unconfirmed are 1–2 match fragments (Sept 12 tails of Tulln, Istanbul 3, Shanghai; the
running Catania; the stray Munich match in `2026-416`). Crosswalks: OddsPapi 284
confirmed, 75 auto, 5 review; TennisMyLife 283 confirmed, 10 auto, 12 review (the
existing review list: Queen's Club, Canada Masters, Crete, Moldova, Morelos, Heilbronn,
Open de Vendée, Ferrero, Copa Internacional, United Cup).

Reproduce: `python scripts/reconcile_master_schedule.py --sheet context_registry/master_schedule/master_schedule_2026.csv --year 2026 --as-of 2026-10-12`.
