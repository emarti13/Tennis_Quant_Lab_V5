# Amendment: replace the fixed sealed period with a forward test per idea

Status: **Approved by the user in chat, 2026-11-01** ("Allow everything"), including the in-play
research question below. Applied to the roadmap and CLAUDE.md in the same change.

Amends: `docs/superpowers/specs/2026-10-12-fair-price-to-market-making-roadmap-design.md`
(§4 Phase 0 "Seal a forward period", Gates 2, 3 and 4) and `CLAUDE.md` ("Sealed period").

## Why

The sealed period (matches on or after 2026-10-13) was meant to be the honest final exam for
the engine. We have no candidate for that exam yet, and the seal locks away the newest and most
relevant data: the server's Kalshi point-by-point and 5-minute price logs, and every match since
2026-10-13. An honest exam does not have to be set aside in advance. New matches arrive every
day, so an idea can be examined on matches played after the date its rules are written down.
That data could not have shaped the idea.

What must not change is the protection the seal gave. After thousands of comparisons on past
data, some results look like edges by luck; the old live record (backtest strong, live ROI
−0.40% over 1,007 picks) is what that looks like. Each idea still needs one test on data it has
never seen, with rules fixed in advance.

## The rule

1. **Exploration data.** On approval, every match before the approval date may be used to
   explore, build and tune, including the 2026-10-13 onward period and the server's logs.
2. **Registration.** Before an idea is tested forward, write a registration file in
   `docs/registrations/YYYY-MM-DD-<name>.md` and commit it. It states:
   - the hypothesis and the decision it would change;
   - the exact segment, prices, venue, timing and fees;
   - the metric, the pass rule (for example: interval excludes zero), and the minimum sample;
   - the planned end of the window (date or sample size, whichever comes first);
   - the code commit that will score it.

   The commit time is the registration time. A registration is never edited. A changed rule is
   a new registration with its own date and its own window.
3. **Forward window.** Only fixtures that start after the registration commit count. Nothing
   in the registered rule may be changed during the window. The data inside a running window
   may still be used to explore other ideas, but not to change this one.
4. **Scoring.** At the planned end, score the registration once with the registered code. The
   result is recorded in the registration file's companion
   `docs/registrations/YYYY-MM-DD-<name>-result.md`, pass or fail.
5. **After a fail.** The idea is dropped, or rebuilt and registered again. It is never
   re-scored on the same window, and the window's data then becomes ordinary exploration data.
6. **Many ideas at once.** Several registrations may run at the same time. Every registration
   and its result is listed in `docs/registrations/README.md`, failures included, so that a
   pass is read against how many ideas were tried. A pass on one of many registrations needs
   the research_kit checks (`research_kit/README.md`) and a second forward window before any
   real money.
7. **Minimum samples** (guidance; each registration sets its own): pre-match winner tests at
   least 300 fixtures in the segment (roughly 2 to 4 weeks for ATP, Challenger and WTA
   together); in-play rules enough matches for the interval the pass rule needs (the server
   logs about 40 to 50 matches a day).

## Changes made to the roadmap

- §4 Phase 0: replace "Seal a forward period starting on the approval date …" with: "Every
  idea is examined on a forward window that starts after its registration (see
  `docs/superpowers/specs/2026-11-01-rolling-forward-test-amendment.md`)."
- Gate 2: "on the sealed forward period" becomes "on a registered forward window"; the 300
  matches, the pre-declared segment and the interval that excludes zero stay. "Do not tune on
  the sealed period" becomes "Do not change a registered rule during its window."
- Gate 3: the selection policy and thresholds are fixed in a registration before the shadow
  window opens (as now).
- Gate 4: "on the sealed collection window" becomes "on a registered forward window of
  collected data".
- §4 Phase 4: "In-play is out of scope until the pre-match simulation is positive" becomes
  "In-play is in scope for research; real money on it needs a passed registered forward test."
- CLAUDE.md "Sealed period" becomes: "**Forward tests.** An idea is accepted only on a forward
  window that starts after its registration (`docs/registrations/`). Do not change a
  registered rule during its window, and never re-score a failed idea on the same window."

## Registrations that already exist

Two hypotheses were locked for the sealed period before this amendment. They keep their dates
and become the first entries in `docs/registrations/README.md`, with their windows starting at
their lock dates:

- near-even favourites (Pinnacle −167 to −125) win less often than priced, locked 2026-10-19
  (`docs/experiments/2026-10-19-preregistered-near-even-favourites.md`, branch
  `research/favourite-band-preregistration`);
- the in-play calibration hypothesis, locked 2026-10-20
  (`docs/experiments/2026-10-20-inplay-calibration.md`, branch `research/kalshi-making-sim`).

## In-play (approved with this amendment)

The roadmap said in-play is out of scope until the pre-match simulation is positive (§4,
Phase 4). The server now collects in-play data (point score, running statistics and prices
every 10 seconds). In-play is now in scope for research. Real money on any in-play idea follows
the same rule as everything else: a passed registered forward test, the research_kit checks and
a second forward window first.

## Trade-off

Each idea waits for its own window (about 3 weeks for a pre-match test) between "promising" and
"proven". In exchange, the newest data opens for exploration now, and the exam is still
on data the idea has never seen.
