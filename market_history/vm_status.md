# Server status, 2026-11-20T07:58:50+00:00

Code: `c749b65 feat: market-following in-play maker for registration 2026-11-19, run daily`  
Disk free: 31.1 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active  
Live logger command: `/home/ubuntu/tql/.venv/bin/python scripts/log_kalshi_live.py --minutes 1440 --interval 10`  
Live polling gap (median seconds between a match's rows, latest day): 10

Tests (pass): `524 passed, 7 skipped in 84.23s (0:01:24)`

## Problems

- none

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-11-14 | 12867 | 22 |
| 2026-11-15 | 56529 | 91 |
| 2026-11-16 | 47898 | 75 |
| 2026-11-17 | 48520 | 80 |
| 2026-11-18 | 31211 | 48 |
| 2026-11-19 | 23890 | 39 |
| 2026-11-20 | 7599 | 11 |

## Registered forward tests (paper)

| test | status | settled / needed | cents per contract | 95% range | note |
|---|---|---|---|---|---|
| inplay_breaker_2026-11-18 | running | 0 / 300 |  |  | 0 scored; other tours 8 |
| inplay_fade_2026-11-18 | running | 20 / 300 | -12.671 | [-23.454, 2.743] | 20 scored |
| inplay_serve_out_2026-11-18 | running | 0 / 300 |  |  | 0 scored; other tours 16 |
| kalshi_blend_2026-11-04 | running | 10 / 300 | -1.6 | [-3.544, -0.054] | P&L 1.696c on 10 settled; 5 of 10 clear on signals alone |
| longshot_2026-11-03 | running | 164 / 300 | -1.809 | [-6.994, 3.154] | favourite won 0.8537 |
| season_end_2026-11-03 | running | 67 / 300 | 1.835 | [-8.963, 12.076] | favourite won 0.4925 |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 1926 | 4534 | 140.48 | 140.48 | 41.13 |
| 0.05 | 1926 | 840 | 52.99 | 52.99 | 22.48 |
| join | 1926 | 217442 | -706.24 | -706.24 | -360.90 |

run_failures.log: 1 lines

Settle output:
```
h=0.03: markets 1926, contracts 4534, marked $41.13, held $140.48
h=0.05: markets 1926, contracts 840, marked $22.48, held $52.99
h=join: markets 1926, contracts 217442, marked $-360.90, held $-706.24
```
