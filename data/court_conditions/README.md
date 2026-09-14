# Court Conditions Snapshot

`courtspeed_snapshot.csv` is the initial persisted external-condition snapshot used by the V5 source adapter.

Current source: CourtSpeed.com, updated 2026-08-27. Fields represented here are factual tournament-year condition observations/labels exposed by that source: surface, indoor/outdoor environment, CPI, adjusted ace rate, rally length, relative air density, altitude, ball type, and overall speed rating.

The runtime does **not** fetch this website. Normal model/UI execution reads this repository snapshot through `v5_court_conditions_source.py` so source replacement can occur later without changing downstream contracts.

Missing cells are intentional and use metric-specific nearest-prior-year fallback. A future year is never used to fill an earlier match. Raw CPI is not the same scale as V5's internal `court_speed_blended` state and is not copied into it.
