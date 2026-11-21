# Do courts at the same event play at different speeds? (2026-11-21)

**Status:** exploratory. Historical data, all before 2026-11-01.

**Idea (user, 2026-11-06):** Fritz said the Paris Masters main court "plays a lot quicker than Court 2". This was parked for lack of court data. The Match Charting Project names the court for each match.

**Test:** `research_tests/courts/run_court_speed.py`, design pushed (`5506b96`) before the run. After that commit, an empty-group guard was added; it is mechanical.

**Data:**

| tour | matches with a court | with player baselines | event-years with a main and another court |
|---|---|---|---|
| WTA | 4,249 | 4,054 | 405 |
| ATP | 7,522 | 7,341 | 720 |

**Method:**
- **Main court:** named Centre, Stadium, Ashe, Chatrier, Laver and so on, or else the most-charted court at that event and year.
- **Measures:** rally length (shots per point after the serve), share of serve points won, and aces.
- **Residuals:** each measure minus the two players' own averages on that surface in their other charted matches.
- **Comparison:** main court minus other courts within the same event and year, averaged over event-years, with ranges resampling event-years.

## Results (main court minus other courts)

| | WTA | ATP |
|---|---|---|
| **PRIMARY rally length (shots per point)** | +0.07 (−0.00, +0.14) | **+0.09 (+0.04, +0.14)** |
| **PRIMARY serve points won (pts)** | +0.31 (−0.17, +0.78) | −0.12 (−0.47, +0.22) |
| aces per 100 serve points | +0.27 (−0.16, +0.69) | −0.03 (−0.37, +0.30) |
| rally length, hard courts | +0.09 (+0.00, +0.18) | +0.11 (+0.05, +0.18) |
| rally length, clay | −0.03 | +0.10 |
| rally length, grass | +0.10 | −0.07 |

**Named courts:** rally length against the other courts at the same events, for courts with 30+ charted matches. The ranges are wide and most include zero. Notable ones:
- Philippe Chatrier (WTA): −0.27 (−0.49, −0.04): shorter rallies.
- Arthur Ashe: +0.33 to +0.40 (n = 13–17): longer rallies.
- Most others are within ±0.15 shots.

## Label

**Main courts are not faster on average.** If anything, main-court rallies are slightly *longer*: +0.09 shots per point on the ATP, about 2–3% of a 3–4 shot rally. Serve dominance is the same: serve points won within ±0.5 points.

Individual courts may differ (Chatrier shorter, Ashe longer), but the samples per court are small.

**Not usable as a betting input from this data.** The differences are a fraction of a shot per point, and court assignments are not known ahead of a match from a free source.

Fritz's Paris comment may be true for that court that week (conditions, balls and ends of the week change too), but it does not generalise to "main courts play faster".
