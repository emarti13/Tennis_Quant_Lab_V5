# Server status, 2026-11-14T07:43:53+00:00

Code: `91f9212 feat: live logger records Kalshi tennis order books and spread / total / set quotes every 5 minutes`  
Disk free: 32.6 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active  
Live logger command: `/home/ubuntu/tql/.venv/bin/python scripts/log_kalshi_live.py --minutes 1440 --interval 10`  
Live polling gap (median seconds between a match's rows, latest day): 10

Tests (pass): `508 passed, 7 skipped in 83.00s (0:01:23)`

## Problems

- none

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-11-08 | 47221 | 44 |
| 2026-11-09 | 72490 | 82 |
| 2026-11-10 | 96136 | 99 |
| 2026-11-11 | 30117 | 44 |
| 2026-11-12 | 23726 | 34 |
| 2026-11-13 | 23936 | 35 |
| 2026-11-14 | 3630 | 7 |

## Registered forward tests (paper)

| test | status | settled / needed | cents per contract | 95% range | note |
|---|---|---|---|---|---|
| kalshi_blend_2026-11-04 | running | 9 / 300 | -1.539 | [-3.67, 0.111] | P&L -2.154c on 9 settled; 4 of 9 clear on signals alone |
| longshot_2026-11-03 | running | 76 / 300 | -5.755 | [-14.703, 2.535] | favourite won 0.8026 |
| season_end_2026-11-03 | running | 56 / 300 | -2.201 | [-14.071, 9.22] | favourite won 0.4821 |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 1308 | 1847 | 99.47 | 93.35 | 11.76 |
| 0.05 | 1308 | 229 | 75.54 | 74.66 | 8.90 |
| join | 1308 | 131356 | -396.86 | -888.25 | -88.54 |

run_failures.log: 1 lines

Settle output:
```
h=0.03: markets 1308, contracts 1847, marked $11.76, held $99.47
h=0.05: markets 1308, contracts 229, marked $8.90, held $75.54
h=join: markets 1308, contracts 131356, marked $-88.54, held $-396.86
```
