# Server status, 2026-11-07T07:34:47+00:00

Code: `91f9212 feat: live logger records Kalshi tennis order books and spread / total / set quotes every 5 minutes`  
Disk free: 33.1 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active  
Live logger command: `/home/ubuntu/tql/.venv/bin/python scripts/log_kalshi_live.py --minutes 1440 --interval 10`  
Live polling gap (median seconds between a match's rows, latest day): 10

Tests (pass): `508 passed, 7 skipped in 82.99s (0:01:22)`

## Problems

- none

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-11-01 | 18593 | 92 |
| 2026-11-02 | 13928 | 67 |
| 2026-11-03 | 57880 | 112 |
| 2026-11-04 | 46609 | 67 |
| 2026-11-05 | 35098 | 48 |
| 2026-11-06 | 34350 | 38 |
| 2026-11-07 | 2861 | 6 |

## Registered forward tests (paper)

| test | status | settled / needed | cents per contract | 95% range | note |
|---|---|---|---|---|---|
| kalshi_blend_2026-11-04 | running | 4 / 300 | -0.11 | [-1.06, 1.255] | P&L 29.187c on 3 settled; 3 of 4 clear on signals alone |
| longshot_2026-11-03 | running | 24 / 300 | 5.11 | [-7.228, 13.674] | favourite won 0.9167 |
| season_end_2026-11-03 | running | 26 / 300 | -18.829 | [-34.041, -3.373] | favourite won 0.3846 |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 766 | 1219 | -8.08 | -12.07 | 5.61 |
| 0.05 | 766 | 115 | 32.65 | 32.21 | 2.72 |
| join | 766 | 60246 | 82.87 | -139.21 | 3.21 |

run_failures.log: 1 lines

Settle output:
```
h=0.03: markets 766, contracts 1219, marked $5.61, held $-8.08
h=0.05: markets 766, contracts 115, marked $2.72, held $32.65
h=join: markets 766, contracts 60246, marked $3.21, held $82.87
```
