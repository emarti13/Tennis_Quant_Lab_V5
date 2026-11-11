# Server status, 2026-11-11T07:42:12+00:00

Code: `91f9212 feat: live logger records Kalshi tennis order books and spread / total / set quotes every 5 minutes`  
Disk free: 33.0 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active  
Live logger command: `/home/ubuntu/tql/.venv/bin/python scripts/log_kalshi_live.py --minutes 1440 --interval 10`  
Live polling gap (median seconds between a match's rows, latest day): 10

Tests (pass): `508 passed, 7 skipped in 82.49s (0:01:22)`

## Problems

- none

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-11-05 | 35098 | 48 |
| 2026-11-06 | 34350 | 38 |
| 2026-11-07 | 22773 | 25 |
| 2026-11-08 | 47221 | 44 |
| 2026-11-09 | 72490 | 82 |
| 2026-11-10 | 96136 | 99 |
| 2026-11-11 | 9435 | 16 |

## Registered forward tests (paper)

| test | status | settled / needed | cents per contract | 95% range | note |
|---|---|---|---|---|---|
| kalshi_blend_2026-11-04 | running | 5 / 300 | -0.036 | [-0.822, 1.056] | P&L -8.886c on 5 settled; 3 of 5 clear on signals alone |
| longshot_2026-11-03 | running | 68 / 300 | -3.736 | [-12.716, 4.61] | favourite won 0.8235 |
| season_end_2026-11-03 | running | 44 / 300 | -5.358 | [-18.675, 8.523] | favourite won 0.4545 |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 1138 | 1783 | 113.42 | 107.51 | 9.04 |
| 0.05 | 1138 | 225 | 75.82 | 74.94 | 8.81 |
| join | 1138 | 101409 | 318.06 | -57.72 | -161.95 |

run_failures.log: 1 lines

Settle output:
```
h=0.03: markets 1138, contracts 1783, marked $9.04, held $113.42
h=0.05: markets 1138, contracts 225, marked $8.81, held $75.82
h=join: markets 1138, contracts 101409, marked $-161.95, held $318.06
```
