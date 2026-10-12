# Tournament identity across sources

Date: 2026-10-12
Status: **DRAFT — pending user approval**
First implementation: `v5_tournament_identity.py` + `scripts/reconcile_master_schedule.py`
(read-only reconciliation; report in `context_registry/master_schedule/reconciliation/2026/REPORT.md`).
Category: Production Reliability (data layer). Serves roadmap Phase 0; prerequisite for
every price, because surface, time zone and court information all hang off the tournament.
Plan: `docs/superpowers/plans/2026-10-12-ground-up-rebuild-plan.md`, Step 2.

## 1. The problem

Three sources describe the same tournaments, and none of them can be the key:

| Source | What it gives | Why it can't be the key |
|---|---|---|
| OddsPapi | Live fixtures and prices: `tournament_id`, `season_id`, a long display name, player IDs and names, start times | Long display names in its own format; repeat events in one city are numbered ("Istanbul 3", "Shymkent II") or not numbered at all; `season_id` is often empty. (Correction: the three IDs first thought to cover two weeks were one week each, split by a gap in our own fixture collection on 2026-09-09/10. No reuse of one ID across weeks has been found in 2026.) |
| TennisMyLife | Results and history: `tourney_id`, short name, `tourney_date`, surface, players | Same short name for different events in a year (2026: six cases, such as two Istanbul and two Munich events). Its IDs have no relation to OddsPapi's. |
| Master schedule | Court information (surface, setting, time zone, altitude, ball, CPI) | Hand-built; names follow the official calendars, not either feed. |

Matching by name, or by city alone, breaks whenever a city hosts more than one event in a
year, an event is renamed or moves, or men's and women's events share a city and week.
Past fixes patched individual names, and the next year produced new mismatches.

## 2. Design

### 2.0 Source of truth (user decision, 2026-10-12)

The **official ATP and WTA calendars** are the source of truth for which editions exist,
their dates, category, city and country. The user is building the master schedule from
them (sheet started 2026-10-12: ATP tour, WTA tour, WTA 125; ATP Challengers to be added). TennisMyLife and OddsPapi
never create or change an edition. They are reconciled against it through the crosswalks
below, and anything that does not reconcile is listed for review.

### 2.1 Two canonical levels, owned by the master schedule

- **Event:** a tournament that recurs across years (for example "the Brisbane men's
  tournament"). `event_id` never changes. When an event is renamed, sponsored, or
  relocated, it keeps its `event_id`; the schedule records the new name and city.
- **Edition:** one event in one specific week. `edition_id = event_id + start date`. Two
  Istanbul Challengers in 2026 are two editions (or two events); the date always tells
  them apart.

Every court attribute lives on the edition row of the master schedule. Carry-forward to a
new year copies from the same `event_id`'s latest edition.

### 2.2 Crosswalk tables: one per source, stored, never re-guessed

| Table | Key | Maps to |
|---|---|---|
| `crosswalk_oddspapi.csv` | (`tournament_id`, date block) | `edition_id` |
| `crosswalk_tennismylife.csv` | `tourney_id` | `edition_id` |

Each row records: how it was matched, the evidence score, `status`
(`auto` / `confirmed` / `user` / `rejected`), and the date it was set. A mapping is
decided **once** and then looked up. Nothing re-matches names each day. The OddsPapi key
includes the date block as a safeguard in case an ID is ever reused across weeks.

### 2.3 Matching a new source ID (resolver)

A new OddsPapi tournament block or TennisMyLife `tourney_id` is scored against editions
using several independent signals. No single signal decides:

1. **Hard filters** (must agree): tour/gender (men vs women), singles, and the date window
   (fixture dates inside the edition's dates, plus or minus 2 days).
2. **Location:** city/country after normalization (accents, "Turkiye/Turkey", numbering
   like "Istanbul 3" stripped).
3. **Level:** category (Grand Slam, 1000, 500, 250, Challenger 50–175, WTA 125) where the
   source gives it.
4. **Players (the strongest evidence):** the players in the source's fixtures for that
   block versus the players in the edition's draw (from TennisMyLife results once
   matches finish). Two events in the same city and season never share most of a draw.
5. **Name similarity:** a weak tiebreaker only.

**Outcomes:**
- **Auto-accept:** exactly one candidate passes the hard filters and the location agrees.
- **Review:** zero candidates, or more than one.
- **Never guess.** An unmatched or ambiguous block produces no price (fail closed) and
  appears in the app's review list with its candidates.

### 2.4 Confirmation loop

After matches finish, TennisMyLife results for the edition are compared with the
fixtures mapped from OddsPapi. Mostly the same player pairs means the mapping is
`confirmed`. A mismatch means it is flagged, and further prices from that block are
blocked until it is reviewed. This catches a wrong `auto` mapping within days.

### 2.5 New years

- An edition row for the new year is created from the calendar (user's sheet). Or, if
  missing, it is **carried forward**: same `event_id`, dates projected from last year's
  week, attributes copied, and labeled "from <year>" in the app.
- Surface history per event comes from results. An event whose surface changed in the
  past is flagged for review instead of carried forward silently.
- OddsPapi `tournament_id` → `event_id` links from the previous year become **candidates**
  for the new year. They still pass the date-window and player checks before being
  accepted, because a reused ID is not proof of the same edition.

### 2.6 User overrides in the app

- The review list shows unmatched and ambiguous blocks with their candidates. The user
  picks the edition, creates a new event, or marks the block "ignore" (for example
  exhibitions). That writes a `user` row to the crosswalk.
- Overriding a court attribute (surface, setting, time zone…) writes to an overrides
  file keyed by `edition_id`, only for the fields changed. The user can promote it into
  the master schedule so next year inherits it.
- Every price shows its resolution method: matched / carried forward / user override.

### 2.7 One module

One module (`v5_tournament_identity.py`) owns resolution, the crosswalks, and reading the
master schedule. The daily forecast, the app, settlement and research all call it. The
four current lookups are removed in the same change (`v5_tournament_authority`,
`v5_master_schedule_context`, `v5_tournament_registry`, `v5_tournament_context_registry`).

## 3. Acceptance (before it replaces the current lookups)

- **2026 back-test:** every OddsPapi 2026 fixture block and every TennisMyLife 2026
  `tourney_id` either maps to exactly one edition or is listed for review. Zero blocks
  map to two editions.
- **Same-city cases resolve correctly:** each multi-edition city in 2026 (Istanbul,
  Shanghai, Tulln, Munich, Oeiras, Antalya and any others found) is checked by player
  overlap.
- **Confirmation agreement:** for settled 2026 editions, mapped OddsPapi fixtures agree
  with TennisMyLife player pairs at ≥ 98%; disagreements are listed.
- **Year-rollover simulation:** using only 2025 data, the 2026 season resolves through
  carry-forward and candidates, and the number needing review is reported.
- **Parity:** the forecast and the app resolve every fixture to the same edition and
  attributes.

## 4. Open questions for the user

1. ~~Calendar source~~ Answered: official ATP/WTA calendars (§2.0). ~~Challengers~~
   Answered: the user has the official ATP Challenger calendar and will add it to the
   master schedule.
2. Should exhibitions and team events (United Cup, Laver Cup, Davis Cup) get editions,
   or be ignored by default?
3. WTA 125 is in your sheet. The roadmap lists it as undecided for pricing. Should it be
   included in identity now (cheap) and priced later?
