# Server status, 2026-11-16T07:49:53+00:00

Code: `91f9212 feat: live logger records Kalshi tennis order books and spread / total / set quotes every 5 minutes`  
Disk free: 32.6 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active  
Live logger command: `/home/ubuntu/tql/.venv/bin/python scripts/log_kalshi_live.py --minutes 1440 --interval 10`  
Live polling gap (median seconds between a match's rows, latest day): 10

Tests (pass): `508 passed, 7 skipped in 95.68s (0:01:35)`

## Problems

- none

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-11-10 | 96136 | 99 |
| 2026-11-11 | 30117 | 44 |
| 2026-11-12 | 23726 | 34 |
| 2026-11-13 | 23936 | 35 |
| 2026-11-14 | 12867 | 22 |
| 2026-11-15 | 56529 | 91 |
| 2026-11-16 | 16969 | 24 |

## Registered forward tests (paper)

| test | status | settled / needed | cents per contract | 95% range | note |
|---|---|---|---|---|---|
| kalshi_blend_2026-11-04 | running | 10 / 300 | -1.6 | [-3.544, -0.054] | P&L 1.696c on 10 settled; 5 of 10 clear on signals alone |
| longshot_2026-11-03 | running | 114 / 300 | -3.056 | [-9.825, 3.15] | favourite won 0.8421 |
| season_end_2026-11-03 | running | 58 / 300 | -1.222 | [-13.091, 10.181] | favourite won 0.5 |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 1526 | 3822 | 53.21 | 42.14 | 34.51 |
| 0.05 | 1526 | 600 | 57.21 | 55.70 | 14.63 |
| join | 1526 | 161872 | -426.68 | -1012.48 | -164.92 |

run_failures.log: 1 lines

Settle output:
```
h=0.03: markets 1526, contracts 3822, marked $34.51, held $53.21
h=0.05: markets 1526, contracts 600, marked $14.63, held $57.21
h=join: markets 1526, contracts 161872, marked $-164.92, held $-426.68
```
