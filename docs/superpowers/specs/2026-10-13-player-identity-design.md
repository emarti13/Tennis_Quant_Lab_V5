# Player identity across sources

Date: 2026-10-13
Status: **Approved by the user in chat, 2026-10-13, in this order:** (1) the safety fix
(question 0, PR #46); (2) build the alias tables and rules (§2.2–2.4, §2.6); (3) decide our
own player id and id-keyed ratings (§2.1, §2.5) after measuring how many same-name players
reach priced fixtures (§2.8). §2.1 and §2.5 are not approved yet.
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
- **Known players are priced as brand-new players.** Name heuristics suggested 9; results
  confirm 4 ("Carle, Maria" is Maria Lourdes Carle; Pietro Fellin; Tai Sach; Rafael De
  Alba). The other 5 have no TennisMyLife results to check against (mostly Challenger
  qualifying, which TennisMyLife does not carry).
- **"New player" means 1500 Elo, and it reaches official bets.** `_cold_start_rating`
  gives a player with no history in our data 1500 Elo. Of 24,547 frozen predictions,
  1,495 had a cold-start player; most were held as REVIEW, but 9 were BET and appear in
  the official ledger (17 rows). Examples: Katarina Kuzmova (no rows in our WTA history:
  her results are ITF, which we do not collect), BET at a 37-point edge; and **"WQF1"**, a
  qualifier slot not yet filled, priced as a player and BET at a 63-point edge. CLAUDE.md
  forbids a quiet 1500 Elo; this is that case.
- `context_registry/player_aliases.csv` is empty: no link has ever been confirmed.

**TennisMyLife player ids are not clean either.** They exist (`winner_id`, `loser_id`) and
mostly hold, but:

- 2026 WTA results carry a second id scheme on 98 rows: Ajla Tomljanovic is `201548` and
  `315232`, Elena Rybakina `214981` and `324166`: 51 players have both an old and a new id.
- Some ids are stored as `211817.0`, some are missing.
- Different people share a name (two "David Warren", two "Quentin Robert", different
  countries and years).

So no single source's ids can be the key on their own. Note: today's ratings are keyed
by name, so TennisMyLife's two id schemes do not split ratings now; the name spellings
do (the 15 players above). The id problems matter for any design that keys by id.

**What results can prove.** With the tournament crosswalks (PR #45), an OddsPapi fixture
and a TennisMyLife match can be placed in the same edition. The match must be the *same*
match: B plays several opponents in one week, so "B played X" alone does not make A = X
(a test of that loose rule returned B's other opponents, e.g. Iga Swiatek for Maria
Carle). It needs B already linked and the round to line up (OddsPapi fixture order vs
TennisMyLife round), or both names compatible. On 2026 data, requiring both names to be
compatible links 1,263 of 2,517 OddsPapi player ids by at least one shared match; 80 of
those point to more than one TennisMyLife id (mostly the second WTA scheme, a few missing
ids), so the count is an upper bound until those are resolved. It also bridges the TennisMyLife id splits: OddsPapi's one id for Tomljanovic
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
  the same country (IOC and ISO spellings equal, e.g. POR/PRT), or when OddsPapi evidence
  ties both to one OddsPapi id (§2.4).
- The same name in different countries, or two ids playing different events in the same
  week (Challenger dates are week starts, so a same-day test is too weak), are different
  players; they are listed for review, never merged automatically.
- Folding: case, accents, hyphens, spacing and name order ignored ("Mccartney" = "McCartney").

### 2.4 Linking an OddsPapi player id

1. **Results (strongest).** The same match in the same edition, as in §1 (opponent
   already linked and round aligned, or both names compatible). Confirmed at two or more
   shared matches that agree and none that disagree; a disagreement goes to review and
   blocks the price.
2. **Names, before results exist.** Exact folded name, unique in that tour: `auto`.
   Otherwise, candidates where one name's words contain the other's ("Maria Carle" in
   "Maria Lourdes Carle"), or suffixes dropped ("Jr", "(2001)"): **review, no price**, with
   the candidates listed. Never a silent cold start.
3. **No history in our data.** Only when no candidate exists at all. Such a player gets
   no BET or LEAN: the price is shown for information, labeled "no history". Placeholders
   ("WQF1", "Qualifier", "TBD") are never priced. A 1500 Elo prior is not a rating.

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

### 2.8 Simpler alternative considered

Keep ratings keyed by a folded name, add a reviewed merge table for the 15 split
spellings, and an OddsPapi `participant_id` → name table. It fixes today's failures at
lower cost. It cannot separate two real people with the same name (they share one
rating today: two "David Warren", two "Quentin Robert", mostly players with a handful of
matches). Recommendation: build §2.4–2.6 (the alias tables and rules) first; they are
needed either way. Decide our-own-id (§2.1, §2.5) after measuring how many same-name
players actually reach priced fixtures.

## 3. Acceptance

- 2026 back-test: every OddsPapi player id in a priced fixture resolves to one
  `player_id` or is on the review list; zero silent cold starts for a player with a
  candidate; no BET or LEAN with a no-history player or a placeholder.
- The 15 split players have one rating each; the 4 confirmed "new" players resolve.
- No OddsPapi id links to two players without being flagged.
- Ratings keyed by `player_id`: out-of-sample log loss no worse than the current engine,
  market benchmark reported.

## 4. Questions for the user

0. Immediate safety fix, separate from this design: block BET/LEAN when either player has
   no history or is a placeholder (enforces the existing no-quiet-1500 rule)?

1. Is it right to give every player our own id (§2.1) and move ratings to it (§2.5),
   with the model check before it goes live?
2. Same name, different country (for example Harshana Godamanna, Sri Lanka and Ecuador):
   OK to keep them as separate players until you decide?
