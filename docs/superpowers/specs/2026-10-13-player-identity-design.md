# Player identity across sources

Date: 2026-10-13
Status: **DRAFT — pending user approval.**
Category: Production Reliability (data layer). Serves roadmap Phase 0; rebuild plan Step 2
(user decision 2026-10-13: player identity is the next Step 2 item).
Companion: `docs/superpowers/specs/2026-10-12-tournament-identity-design.md` (same approach,
and this design relies on its edition crosswalks, PR #45).

## 1. The problem (measured 2026-10-13)

A price needs both players' ratings, so every OddsPapi player must be tied to the right
player in our history. Nothing does this reliably today.

**Live resolver (`v5_player_identity.resolve_identity`, used by `v5_daily_batch.py`).** It
matches names only. Against the 2,519 player names OddsPapi used in 2026:

- About 1,600 resolve.
- **15 players are refused because our own history spells them two ways** ("Alex de
  Minaur" / "Alex De Minaur", "Elena-Gabriela Ruse" / "Elena Gabriela Ruse", "Mccartney
  Kessler" / "McCartney Kessler", Jesper de Jong, Botic van de Zandschulp...). Their ratings
  are also split across two rows, because the ratings are keyed by name.
- **97 spelling variants are refused** ("Damm Jr, Martin", "Cretu, Cezar (2001)", "Pyotr" vs
  "Petr" Nesterov). Safe, but no price.
- **At least 9 known players are priced as brand-new players** ("Carle, Maria" is Maria
  Lourdes Carle; Pietro Fellin; Tai Sach; Daniel Salazar). This is a silent default, which
  CLAUDE.md forbids.
- `context_registry/player_aliases.csv` is empty: no link has ever been confirmed.

**TennisMyLife player ids are not clean either.** They exist (`winner_id`, `loser_id`) and
mostly hold, but:

- 2026 WTA results carry a second id scheme on 98 rows: Ajla Tomljanovic is `201548` and
  `315232`, Elena Rybakina `214981` and `324166`: 51 players have both an old and a new id.
- Some ids are stored as `211817.0`, some are missing.
- Different people share a name (two "David Warren", two "Quentin Robert", different
  countries and years).

So neither names nor any one source's ids can be the key.

**What results can prove.** With the tournament crosswalks (PR #45), an OddsPapi fixture
and a TennisMyLife match can be placed in the same edition. If OddsPapi has A vs B and
TennisMyLife has the same edition's match between B and X, then A is X, whatever the
spelling. On 2026 data this links 1,263 of 2,517 OddsPapi player ids by at least one
shared match. It also bridges the TennisMyLife id splits: OddsPapi's one id for Tomljanovic
lines up with both `201548` and `315232`. The unlinked ids are mostly players seen only in
qualifying or in the weeks our OddsPapi collection missed; they fall back to the name rules
in §2.4.

## 2. Design

### 2.1 Our own player id

- `context_registry/players/players.csv`: one row per real player. `player_id` is ours
  (`M-000123`, `W-000456`), never reused, never derived from a name. Columns: tour, display
  name, country, first and last match date, and status (`active`, `merged_into:<id>`).
- Every source id and spelling is an alias of exactly one `player_id`.

### 2.2 Alias tables, one per source, stored and never re-guessed

| Table | Key | Maps to |
|---|---|---|
| `alias_tennismylife.csv` | TennisMyLife id (normalized: `211817.0` → `211817`) | `player_id` |
| `alias_oddspapi.csv` | OddsPapi `participant_id` | `player_id` |
| `alias_names.csv` | (tour, folded name) | `player_id`, only where the name is unique |

Each row records method, evidence count, status (`confirmed` / `auto` / `review` /
`user` / `rejected`) and the date set. As with tournaments, rows marked `confirmed`,
`user` or `rejected` are never changed by a later run; disagreements are reported.

### 2.3 Building players from TennisMyLife history

- Two TennisMyLife ids are the same player when they share a tour and a folded name and
  the same country, or when OddsPapi evidence ties both to one OddsPapi id (§2.4).
- The same name in different countries, or two ids playing different events on the same
  day, are different players; they are listed for review, never merged automatically.
- Folding: case, accents, hyphens, spacing and name order ignored ("Mccartney" = "McCartney").

### 2.4 Linking an OddsPapi player id

1. **Results (strongest).** Shared matches in the same edition, as in §1. Confirmed at
   two or more shared matches that agree and none that disagree; a disagreement goes to
   review and blocks the price.
2. **Names, before results exist.** Exact folded name, unique in that tour: `auto`.
   Otherwise, candidates where one name's words contain the other's ("Maria Carle" in
   "Maria Lourdes Carle"), or suffixes dropped ("Jr", "(2001)"): **review, no price**, with
   the candidates listed. Never a silent cold start.
3. **Cold start** only when no candidate exists at all, and it is labeled as a new player.

### 2.5 Ratings keyed by player id

Ratings move from names to `player_id`, so a player's history is no longer split by
spelling or by TennisMyLife's id schemes. That changes ratings, so it is a model change:
it is accepted only if chronological out-of-sample log loss does not get worse against the
current engine (CLAUDE.md), with the market benchmark reported, and never tuned on the
sealed period.

### 2.6 Review and overrides

The app's review list (Step 2) shows unlinked and conflicting players with candidates.
The user picks a player, creates a new one, or rejects a link. That writes a `user` row.

### 2.7 One module

One module owns players and aliases; `v5_player_identity.resolve_identity` and the empty
`player_aliases.csv` are removed in the PR that switches the daily batch over.

## 3. Acceptance

- 2026 back-test: every OddsPapi player id in a priced fixture resolves to one
  `player_id` or is on the review list; zero silent cold starts for a player with a
  candidate.
- The 15 split players have one rating each; the 9 known "new" players resolve.
- No OddsPapi id links to two players without being flagged.
- Ratings keyed by `player_id`: out-of-sample log loss no worse than the current engine,
  market benchmark reported.

## 4. Questions for the user

1. Is it right to give every player our own id (§2.1) and move ratings to it (§2.5),
   with the model check before it goes live?
2. Same name, different country (for example Harshana Godamanna, Sri Lanka and Ecuador):
   OK to keep them as separate players until you decide?
