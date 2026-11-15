# Server status, 2026-11-15T07:46:27+00:00

Code: `91f9212 feat: live logger records Kalshi tennis order books and spread / total / set quotes every 5 minutes`  
Disk free: 32.6 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active  
Live logger command: `/home/ubuntu/tql/.venv/bin/python scripts/log_kalshi_live.py --minutes 1440 --interval 10`  
Live polling gap (median seconds between a match's rows, latest day): 10

Tests (pass): `508 passed, 7 skipped in 83.27s (0:01:23)`

## Problems

- none

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-11-09 | 72490 | 82 |
| 2026-11-10 | 96136 | 99 |
| 2026-11-11 | 30117 | 44 |
| 2026-11-12 | 23726 | 34 |
| 2026-11-13 | 23936 | 35 |
| 2026-11-14 | 12867 | 22 |
| 2026-11-15 | 14505 | 25 |

## Registered forward tests (paper)

| test | status | settled / needed | cents per contract | 95% range | note |
|---|---|---|---|---|---|
| kalshi_blend_2026-11-04 | running | 9 / 300 | -1.539 | [-3.67, 0.111] | P&L -2.154c on 9 settled; 4 of 9 clear on signals alone |
| longshot_2026-11-03 | running | 82 / 300 | -4.243 | [-12.315, 3.168] | favourite won 0.8171 |
| season_end_2026-11-03 | running | 58 / 300 | -1.222 | [-13.091, 10.181] | favourite won 0.5 |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 1368 | 2490 | 141.95 | 133.68 | 14.28 |
| 0.05 | 1368 | 381 | 72.73 | 71.48 | 13.91 |
| join | 1368 | 142632 | -314.54 | -848.37 | -89.53 |

run_failures.log: 1 lines

Settle output:
```
h=0.03: markets 1368, contracts 2490, marked $14.28, held $141.95
h=0.05: markets 1368, contracts 381, marked $13.91, held $72.73
h=join: markets 1368, contracts 142632, marked $-89.53, held $-314.54
```
