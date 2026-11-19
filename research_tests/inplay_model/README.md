# Score-based fair price (in play)

`research_kit/inplay.py`: the chance a player wins the match from any score. This is a point-level
Markov chain: games with deuce, 7- or 10-point tie-breaks, sets, and best of 3 or 5. Each player has
one serve-point win probability, solved from the **pre-match price** so that the model reproduces it
at 0-0. That price already carries surface, altitude, indoor/outdoor, court speed and form, so no
player profiles are needed. The tests are in `tests/test_research_inplay.py`: known game values,
symmetry, point-to-point consistency, and the solver reproducing the pre-match price.

**Serve level** (average share of serve points won, TennisMyLife 2022-2025):

| tour | clay | grass | hard indoor | hard outdoor |
|---|---|---|---|---|
| ATP | 0.6188 (3,300 matches) | 0.6597 (1,259) | 0.6553 (1,703) | 0.6409 (4,672) |
| Challenger | 0.5980 (3,091) | 0.6419 (184) | 0.6325 (883) | 0.6165 (2,070) |

The WTA stats are not in the files, so a published average of 0.56 is used; it is not measured here.
The level mainly sets how far one break moves the price. The gap between the players comes from the market.

**Replay:** `replay_match.py` prints the fair price next to Kalshi's at every game of a logged match.
It is a mechanics check only. On one ATP match (event KXATPMATCH-26NOV10MUSSAM, 2026-11-10), the two agreed within
0-2 points at every game, and Kalshi was slightly above the fair price for the favourite.

**Not done yet:** the registered forward tests (overreaction taker, in-play maker); surface and
indoor taken from the master schedule through `v5_fixture_resolution.py`.
