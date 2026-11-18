# Server status, 2026-11-18T08:01:14+00:00

Code: `6a8d7b6 feat: paper tracker for registration 2026-11-18 (in-play rules: fade the favourite, WTA serve-out, WTA breaker)`  
Disk free: 31.2 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active  
Live logger command: `/home/ubuntu/tql/.venv/bin/python scripts/log_kalshi_live.py --minutes 1440 --interval 10`  
Live polling gap (median seconds between a match's rows, latest day): 10

Tests (pass): `520 passed, 7 skipped in 82.48s (0:01:22)`

## Problems

- none

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-11-12 | 23726 | 34 |
| 2026-11-13 | 23936 | 35 |
| 2026-11-14 | 12867 | 22 |
| 2026-11-15 | 56529 | 91 |
| 2026-11-16 | 47898 | 75 |
| 2026-11-17 | 48520 | 80 |
| 2026-11-18 | 11977 | 19 |

## Registered forward tests (paper)

| test | status | settled / needed | cents per contract | 95% range | note |
|---|---|---|---|---|---|
| kalshi_blend_2026-11-04 | running | 10 / 300 | -1.6 | [-3.544, -0.054] | P&L 1.696c on 10 settled; 5 of 10 clear on signals alone |
| longshot_2026-11-03 | running | 151 / 300 | -2.486 | [-8.127, 2.676] | favourite won 0.8477 |
| season_end_2026-11-03 | running | 62 / 300 | -2.32 | [-13.342, 8.723] | favourite won 0.4677 |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 1790 | 4354 | 188.77 | 175.50 | 35.83 |
| 0.05 | 1790 | 697 | 87.55 | 85.67 | 13.47 |
| join | 1790 | 197011 | -897.53 | -1603.13 | -376.11 |

run_failures.log: 1 lines

Settle output:
```
h=0.03: markets 1790, contracts 4354, marked $35.83, held $188.77
h=0.05: markets 1790, contracts 697, marked $13.47, held $87.55
h=join: markets 1790, contracts 197011, marked $-376.11, held $-897.53
```
