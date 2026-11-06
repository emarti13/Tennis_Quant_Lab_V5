# Server status, 2026-11-06T07:34:14+00:00

Code: `91f9212 feat: live logger records Kalshi tennis order books and spread / total / set quotes every 5 minutes`  
Disk free: 33.2 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active  
Live logger command: `/home/ubuntu/tql/.venv/bin/python scripts/log_kalshi_live.py --minutes 1440 --interval 10`  
Live polling gap (median seconds between a match's rows, latest day): 10

Tests (pass): `508 passed, 7 skipped in 80.92s (0:01:20)`

## Problems

- none

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-10-31 | 10237 | 47 |
| 2026-11-01 | 18593 | 92 |
| 2026-11-02 | 13928 | 67 |
| 2026-11-03 | 57880 | 112 |
| 2026-11-04 | 46609 | 67 |
| 2026-11-05 | 35098 | 48 |
| 2026-11-06 | 3690 | 6 |

## Registered forward tests (paper)

| test | status | settled / needed | cents per contract | 95% range | note |
|---|---|---|---|---|---|
| kalshi_blend_2026-11-04 | running | 1 / 300 | -0.49 | [-0.49, -0.49] | P&L 25.62c on 1 settled; 0 of 1 clear on signals alone |
| longshot_2026-11-03 | running | 22 / 300 | 4.163 | [-8.954, 13.51] | favourite won 0.9091 |
| season_end_2026-11-03 | running | 21 / 300 | -22.348 | [-39.216, -5.604] | favourite won 0.381 |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 720 | 1219 | -8.08 | -12.07 | 5.61 |
| 0.05 | 720 | 115 | 32.65 | 32.21 | 2.72 |
| join | 720 | 53069 | 218.71 | 26.47 | -22.90 |

run_failures.log: 1 lines

Settle output:
```
h=0.03: markets 720, contracts 1219, marked $5.61, held $-8.08
h=0.05: markets 720, contracts 115, marked $2.72, held $32.65
h=join: markets 720, contracts 53069, marked $-22.90, held $218.71
```
