# Server status, 2026-11-10T07:40:54+00:00

Code: `91f9212 feat: live logger records Kalshi tennis order books and spread / total / set quotes every 5 minutes`  
Disk free: 33.0 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active  
Live logger command: `/home/ubuntu/tql/.venv/bin/python scripts/log_kalshi_live.py --minutes 1440 --interval 10`  
Live polling gap (median seconds between a match's rows, latest day): 23

Tests (pass): `508 passed, 7 skipped in 82.44s (0:01:22)`

## Problems

- none

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-11-04 | 46609 | 67 |
| 2026-11-05 | 35098 | 48 |
| 2026-11-06 | 34350 | 38 |
| 2026-11-07 | 22773 | 25 |
| 2026-11-08 | 47221 | 44 |
| 2026-11-09 | 72490 | 82 |
| 2026-11-10 | 31995 | 45 |

## Registered forward tests (paper)

| test | status | settled / needed | cents per contract | 95% range | note |
|---|---|---|---|---|---|
| kalshi_blend_2026-11-04 | running | 4 / 300 | -0.11 | [-1.06, 1.255] | P&L 8.453c on 4 settled; 3 of 4 clear on signals alone |
| longshot_2026-11-03 | running | 52 / 300 | 1.866 | [-7.326, 9.614] | favourite won 0.8846 |
| season_end_2026-11-03 | running | 38 / 300 | -7.051 | [-20.763, 7.489] | favourite won 0.4474 |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 998 | 1434 | -1.99 | -6.48 | 5.12 |
| 0.05 | 998 | 126 | 33.89 | 33.43 | 3.25 |
| join | 998 | 89616 | 910.41 | 577.96 | -71.29 |

run_failures.log: 1 lines

Settle output:
```
h=0.03: markets 998, contracts 1434, marked $5.12, held $-1.99
h=0.05: markets 998, contracts 126, marked $3.25, held $33.89
h=join: markets 998, contracts 89616, marked $-71.29, held $910.41
```
