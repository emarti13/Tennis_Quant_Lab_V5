# Registered forward tests

Rule: `docs/superpowers/specs/2026-11-01-rolling-forward-test-amendment.md` (approved 2026-11-01).
Each idea is written down here before it is tested. Only fixtures that start after the
registration commit count. A registration is never edited (a changed rule is a new row with
its own date). Every result is listed, failures included, so that a pass is read against how
many ideas were tried.

| Registered | Idea | File | Window ends | Result |
|---|---|---|---|---|
| 2026-10-19 | Near-even favourites (Pinnacle −167 to −125) win less often than priced | `docs/experiments/2026-10-19-preregistered-near-even-favourites.md` (branch `research/favourite-band-preregistration`) | as stated in the file | open |
| 2026-10-20 | In-play calibration | `docs/experiments/2026-10-20-inplay-calibration.md` (branch `research/kalshi-making-sim`) | as stated in the file | open |
| 2026-11-03 | Back the favourite when a Kalshi tennis long shot's YES bid is 20¢ or less (6 h to 60 min before the start), after the taker fee | `docs/registrations/2026-11-03-kalshi-longshot-favourite.md` (tracked daily by the server: `market_history/kalshi/registrations/` on `data/vm-logs`) | 300 settled matches or 2027-01-31 | running |

New registrations: `docs/registrations/YYYY-MM-DD-<name>.md` (hypothesis and the decision it
would change; segment, prices, venue, timing, fees; metric, pass rule, minimum sample; planned
end; the code commit that will score it). The result goes in `YYYY-MM-DD-<name>-result.md`.
