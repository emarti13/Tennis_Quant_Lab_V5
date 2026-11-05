# Server status, 2026-11-05T07:34:10+00:00

Code: `a6469af feat: Kalshi blend tracker reports where each bet's edge came from (price stretch vs signals)`  
Disk free: 33.2 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active  
Live logger command: `/home/ubuntu/tql/.venv/bin/python scripts/log_kalshi_live.py --minutes 1440 --interval 10`  
Live polling gap (median seconds between a match's rows, latest day): 10

Tests (pass): `506 passed, 7 skipped in 81.71s (0:01:21)`

## Problems

- none

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-10-31 | 10237 | 47 |
| 2026-11-01 | 18593 | 92 |
| 2026-11-02 | 13928 | 67 |
| 2026-11-03 | 57880 | 112 |
| 2026-11-04 | 46609 | 67 |
| 2026-11-05 | 4905 | 7 |

## Registered forward tests (paper)

| test | status | settled / needed | cents per contract | 95% range | note |
|---|---|---|---|---|---|
| kalshi_blend_2026-11-04 | running | 0 / 300 |  |  |  |
| longshot_2026-11-03 | running | 17 / 300 | 1.851 | [-15.009, 13.89] | favourite won 0.8824 |
| season_end_2026-11-03 | running | 15 / 300 | -29.111 | [-48.491, -6.852] | favourite won 0.3333 |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 662 | 1219 | -8.08 | -12.07 | 5.61 |
| 0.05 | 662 | 115 | 32.65 | 32.21 | 2.72 |
| join | 662 | 45460 | 806.72 | 644.51 | -36.01 |

run_failures.log: 1 lines

Settle output:
```
h=0.03: markets 662, contracts 1219, marked $5.61, held $-8.08
h=0.05: markets 662, contracts 115, marked $2.72, held $32.65
h=join: markets 662, contracts 45460, marked $-36.01, held $806.72
```
