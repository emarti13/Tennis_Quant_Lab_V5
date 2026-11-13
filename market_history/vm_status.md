# Server status, 2026-11-13T07:43:34+00:00

Code: `91f9212 feat: live logger records Kalshi tennis order books and spread / total / set quotes every 5 minutes`  
Disk free: 32.6 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active  
Live logger command: `/home/ubuntu/tql/.venv/bin/python scripts/log_kalshi_live.py --minutes 1440 --interval 10`  
Live polling gap (median seconds between a match's rows, latest day): 10

Tests (pass): `508 passed, 7 skipped in 79.82s (0:01:19)`

## Problems

- none

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-11-07 | 22773 | 25 |
| 2026-11-08 | 47221 | 44 |
| 2026-11-09 | 72490 | 82 |
| 2026-11-10 | 96136 | 99 |
| 2026-11-11 | 30117 | 44 |
| 2026-11-12 | 23726 | 34 |
| 2026-11-13 | 8126 | 12 |

## Registered forward tests (paper)

| test | status | settled / needed | cents per contract | 95% range | note |
|---|---|---|---|---|---|
| kalshi_blend_2026-11-04 | running | 8 / 300 | -0.709 | [-2.085, 0.413] | P&L -7.214c on 8 settled; 4 of 8 clear on signals alone |
| longshot_2026-11-03 | running | 75 / 300 | -4.674 | [-13.438, 3.0] | favourite won 0.8133 |
| season_end_2026-11-03 | running | 55 / 300 | -1.446 | [-13.19, 10.464] | favourite won 0.4909 |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 1258 | 1847 | 99.47 | 93.35 | 11.76 |
| 0.05 | 1258 | 229 | 75.54 | 74.66 | 8.90 |
| join | 1258 | 121468 | -240.62 | -692.44 | -117.12 |

run_failures.log: 1 lines

Settle output:
```
h=0.03: markets 1258, contracts 1847, marked $11.76, held $99.47
h=0.05: markets 1258, contracts 229, marked $8.90, held $75.54
h=join: markets 1258, contracts 121468, marked $-117.12, held $-240.62
```
