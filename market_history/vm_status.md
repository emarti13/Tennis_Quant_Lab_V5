# Server status, 2026-11-17T07:51:33+00:00

Code: `91f9212 feat: live logger records Kalshi tennis order books and spread / total / set quotes every 5 minutes`  
Disk free: 32.5 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active  
Live logger command: `/home/ubuntu/tql/.venv/bin/python scripts/log_kalshi_live.py --minutes 1440 --interval 10`  
Live polling gap (median seconds between a match's rows, latest day): 10

Tests (pass): `508 passed, 7 skipped in 85.99s (0:01:25)`

## Problems

- none

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-11-11 | 30117 | 44 |
| 2026-11-12 | 23726 | 34 |
| 2026-11-13 | 23936 | 35 |
| 2026-11-14 | 12867 | 22 |
| 2026-11-15 | 56529 | 91 |
| 2026-11-16 | 47898 | 75 |
| 2026-11-17 | 17205 | 30 |

## Registered forward tests (paper)

| test | status | settled / needed | cents per contract | 95% range | note |
|---|---|---|---|---|---|
| kalshi_blend_2026-11-04 | running | 10 / 300 | -1.6 | [-3.544, -0.054] | P&L 1.696c on 10 settled; 5 of 10 clear on signals alone |
| longshot_2026-11-03 | running | 135 / 300 | -3.481 | [-9.677, 2.289] | favourite won 0.837 |
| season_end_2026-11-03 | running | 61 / 300 | -1.944 | [-12.866, 8.781] | favourite won 0.4754 |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 1662 | 3986 | 97.42 | 85.70 | 26.55 |
| 0.05 | 1662 | 660 | 78.19 | 76.46 | 12.34 |
| join | 1662 | 180864 | -633.38 | -1284.15 | -284.64 |

run_failures.log: 1 lines

Settle output:
```
h=0.03: markets 1662, contracts 3986, marked $26.55, held $97.42
h=0.05: markets 1662, contracts 660, marked $12.34, held $78.19
h=join: markets 1662, contracts 180864, marked $-284.64, held $-633.38
```
