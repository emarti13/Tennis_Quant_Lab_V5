# Server status, 2026-11-04T07:26:55+00:00

Code: `0435ea2 feat: paper tracker for registration 2026-11-04 (Kalshi blend at the opening quote, scored on CLV)`  
Disk free: 33.3 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active  
Live logger command: `/home/ubuntu/tql/.venv/bin/python scripts/log_kalshi_live.py --minutes 1440 --interval 10`  
Live polling gap (median seconds between a match's rows, latest day): 10

Tests (pass): `505 passed, 7 skipped in 82.01s (0:01:22)`

## Problems

- none

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-10-31 | 10237 | 47 |
| 2026-11-01 | 18593 | 92 |
| 2026-11-02 | 13928 | 67 |
| 2026-11-03 | 57880 | 112 |
| 2026-11-04 | 9416 | 16 |

## Registered forward tests (paper)

| test | status | settled / needed | cents per contract | 95% range | note |
|---|---|---|---|---|---|
| longshot_2026-11-03 | running | 5 / 300 | -9.102 | [-46.056, 11.646] | favourite won 0.8 |
| season_end_2026-11-03 | running | 4 / 300 | -29.348 | [-57.905, 9.768] | favourite won 0.25 |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 598 | 1206 | -10.74 | -14.69 | 5.14 |
| 0.05 | 598 | 115 | 32.65 | 32.21 | 2.72 |
| join | 598 | 38234 | 669.39 | 535.59 | -41.79 |

run_failures.log: 1 lines

Settle output:
```
h=0.03: markets 598, contracts 1206, marked $5.14, held $-10.74
h=0.05: markets 598, contracts 115, marked $2.72, held $32.65
h=join: markets 598, contracts 38234, marked $-41.79, held $669.39
```
