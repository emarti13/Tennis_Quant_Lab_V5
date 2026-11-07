# Parked ideas (not yet tested)

Each entry says why it might be an edge, what data it needs, and how to get that data later.

## Court speed within the same event (parked 2026-11-07)

**Why:** courts at one event can play at very different speeds. For example, Fritz said after beating Fils at the 2026 Paris Masters that the main court "plays a lot quicker than Court 2" and "it would have been a different match" there. Prices treat the event as one surface, so which court a match is on may be missed. This matters most for:
- big servers against grinders;
- the total-games and game-spread markets (a quicker court means more holds and tiebreaks, so more games).

**Data needed:** the court each match is (or was) played on, before the start; and, for history, past matches with their courts.

**What we checked (2026-11-07):**
- **Kalshi** has no court field (milestone details: tournament, round, best-of, players; live data: score and stats). Its `source_id` is Sportradar, which has courts but is paid, so it is not used.
- **TennisMyLife and the Kaggle odds data** have no court.
- **The ATP order of play** (atptour.com daily schedule, with the court for every match) is blocked by this environment's network rules.

**Ways to get it later:**
1. **Allow the ATP and WTA order-of-play hosts in the cloud environment's network settings.** This is the user's decision: ask Claude to propose the exact hosts with the environment tool; nothing is added without approval. Then a daily collector, inside the Actions budget or on the Oracle server, saves the court for each scheduled match. History builds up from that day only.
2. **Tournament websites** publish order-of-play PDFs. The hosts differ by event, so the same allowlist step is needed for each.
3. **Manual:** the user notes the court for the matches at events we follow, about a minute a day, in a decision file (`context_registry/DECISIONS.md` lists where user decisions live).
4. **No court labels: infer the speed in play.** The live logger (`scripts/log_kalshi_live.py`) records aces, serve points won and holds every 10 seconds. Compare the first set's serve rates with the two players' usual rates (TennisMyLife history). A court playing quicker than expected shows up there. The test is whether Kalshi's total-games / game-spread price (logged since 2026-11-06 in `live_scores/props/` and `orderbook/`) has caught up by the end of the first set. This needs no new data source, only a few weeks of the new logs.

**Rules:** no paid sources, no routing around blocked hosts (CLAUDE.md). Court-condition modules in production are retired, so a court feature would go through `v5_fixture_resolution.py` and the master schedule if it ever reaches production.
