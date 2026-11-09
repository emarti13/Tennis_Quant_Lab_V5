# Server status, 2026-11-09T07:38:13+00:00

Code: `91f9212 feat: live logger records Kalshi tennis order books and spread / total / set quotes every 5 minutes`  
Disk free: 33.1 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active  
Live logger command: `/home/ubuntu/tql/.venv/bin/python scripts/log_kalshi_live.py --minutes 1440 --interval 10`  
Live polling gap (median seconds between a match's rows, latest day): 10

Tests (pass): `508 passed, 7 skipped in 85.78s (0:01:25)`

## Problems

- none

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-11-03 | 57880 | 112 |
| 2026-11-04 | 46609 | 67 |
| 2026-11-05 | 35098 | 48 |
| 2026-11-06 | 34350 | 38 |
| 2026-11-07 | 22773 | 25 |
| 2026-11-08 | 47221 | 44 |
| 2026-11-09 | 12505 | 12 |

## Registered forward tests (paper)

| test | status | settled / needed | cents per contract | 95% range | note |
|---|---|---|---|---|---|
| kalshi_blend_2026-11-04 | running | 4 / 300 | -0.11 | [-1.06, 1.255] | P&L 8.453c on 4 settled; 3 of 4 clear on signals alone |
| longshot_2026-11-03 | running | 31 / 300 | 0.509 | [-11.903, 10.184] | favourite won 0.871 |
| season_end_2026-11-03 | running | 36 / 300 | -8.76 | [-23.392, 5.496] | favourite won 0.4444 |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 858 | 1272 | -11.06 | -15.27 | 5.78 |
| 0.05 | 858 | 116 | 32.08 | 31.64 | 2.69 |
| join | 858 | 72970 | -128.92 | -399.45 | -27.30 |

run_failures.log: 1 lines

Settle output:
```
h=0.03: markets 858, contracts 1272, marked $5.78, held $-11.06
h=0.05: markets 858, contracts 116, marked $2.69, held $32.08
h=join: markets 858, contracts 72970, marked $-27.30, held $-128.92
```
