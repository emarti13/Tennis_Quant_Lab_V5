# Compatriot matches: favourites perform as priced

Date: 2026-11-03. Research, 2016-2025 odds. Script: `research_tests/tells/run_compatriots.py`;
output: `research_tests/tells/compatriots_results.json`.

The question, pre-registered: when both players share a nationality (friends, training partners,
Davis Cup team-mates), does the market favourite underperform its price? Nationality comes from
the history file at the match. 84,956 matches; 9.1% are compatriot matches.

| | Favourite won − Betfair close | 95% range | n |
|---|---|---|---|
| **Compatriot matches (primary)** | **+0.46 pts** | −0.58 to +1.53 | 7,717 |
| Other matches | +0.06 pts | −0.29 to +0.38 | 77,239 |
| Compatriot, 2016-2021 / 2022-2025 | −0.33 / +1.21 | | |
| Compatriot, by level: ATP / Challenger / WTA | −0.6 / +1.5 / −2.3 | | |

Checks pass: a planted 3-point shift is recovered (−2.8 found), and the market null includes zero.
Directions differ by level and period: noise. **Closed.**

Other "tells before the match" (doubles withdrawals, coach changes) are not in any free dataset the
project has, so they are untested.
