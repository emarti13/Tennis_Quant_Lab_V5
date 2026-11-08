# Server status, 2026-11-08T07:35:04+00:00

Code: `91f9212 feat: live logger records Kalshi tennis order books and spread / total / set quotes every 5 minutes`  
Disk free: 33.1 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active  
Live logger command: `/home/ubuntu/tql/.venv/bin/python scripts/log_kalshi_live.py --minutes 1440 --interval 10`  
Live polling gap (median seconds between a match's rows, latest day): 10

Tests (pass): `508 passed, 7 skipped in 80.08s (0:01:20)`

## Problems

- none

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-11-02 | 13928 | 67 |
| 2026-11-03 | 57880 | 112 |
| 2026-11-04 | 46609 | 67 |
| 2026-11-05 | 35098 | 48 |
| 2026-11-06 | 34350 | 38 |
| 2026-11-07 | 22773 | 25 |
| 2026-11-08 | 4571 | 6 |

## Registered forward tests (paper)

| test | status | settled / needed | cents per contract | 95% range | note |
|---|---|---|---|---|---|
| kalshi_blend_2026-11-04 | running | 4 / 300 | -0.11 | [-1.06, 1.255] | P&L 8.453c on 4 settled; 3 of 4 clear on signals alone |
| longshot_2026-11-03 | running | 28 / 300 | 2.791 | [-10.177, 12.891] | favourite won 0.8929 |
| season_end_2026-11-03 | running | 32 / 300 | -10.938 | [-25.699, 3.524] | favourite won 0.4375 |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 798 | 1243 | 3.20 | -0.89 | 5.97 |
| 0.05 | 798 | 115 | 32.65 | 32.21 | 2.72 |
| join | 798 | 66070 | -68.45 | -313.60 | -3.64 |

run_failures.log: 1 lines

Settle output:
```
h=0.03: markets 798, contracts 1243, marked $5.97, held $3.20
h=0.05: markets 798, contracts 115, marked $2.72, held $32.65
h=join: markets 798, contracts 66070, marked $-3.64, held $-68.45
```
