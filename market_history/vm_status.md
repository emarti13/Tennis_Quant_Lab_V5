# Server status, 2026-11-12T07:43:11+00:00

Code: `91f9212 feat: live logger records Kalshi tennis order books and spread / total / set quotes every 5 minutes`  
Disk free: 32.6 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active  
Live logger command: `/home/ubuntu/tql/.venv/bin/python scripts/log_kalshi_live.py --minutes 1440 --interval 10`  
Live polling gap (median seconds between a match's rows, latest day): 10

Tests (pass): `508 passed, 7 skipped in 83.76s (0:01:23)`

## Problems

- none

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-11-06 | 34350 | 38 |
| 2026-11-07 | 22773 | 25 |
| 2026-11-08 | 47221 | 44 |
| 2026-11-09 | 72490 | 82 |
| 2026-11-10 | 96136 | 99 |
| 2026-11-11 | 30117 | 44 |
| 2026-11-12 | 5292 | 10 |

## Registered forward tests (paper)

| test | status | settled / needed | cents per contract | 95% range | note |
|---|---|---|---|---|---|
| kalshi_blend_2026-11-04 | running | 5 / 300 | -0.036 | [-0.822, 1.056] | P&L -8.886c on 5 settled; 3 of 5 clear on signals alone |
| longshot_2026-11-03 | running | 74 / 300 | -4.928 | [-13.563, 3.254] | favourite won 0.8108 |
| season_end_2026-11-03 | running | 50 / 300 | -2.328 | [-14.382, 10.129] | favourite won 0.48 |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 1202 | 1843 | 98.06 | 91.95 | 11.82 |
| 0.05 | 1202 | 229 | 75.54 | 74.66 | 8.90 |
| join | 1202 | 111847 | -225.61 | -639.12 | -139.92 |

run_failures.log: 1 lines

Settle output:
```
h=0.03: markets 1202, contracts 1843, marked $11.82, held $98.06
h=0.05: markets 1202, contracts 229, marked $8.90, held $75.54
h=join: markets 1202, contracts 111847, marked $-139.92, held $-225.61
```
