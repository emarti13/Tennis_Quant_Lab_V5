# Server status, 2026-11-22T08:14:05+00:00

Code: `09aab63 feat: paper tracker for registration 2026-11-21 (order-book wall on Kalshi tennis, scored on CLV)`  
Disk free: 31.1 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active  
Live logger command: `/home/ubuntu/tql/.venv/bin/python scripts/log_kalshi_live.py --minutes 1440 --interval 10`  
Live polling gap (median seconds between a match's rows, latest day): 10

Tests (pass): `526 passed, 7 skipped in 90.90s (0:01:30)`

## Problems

- none

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-11-16 | 47898 | 75 |
| 2026-11-17 | 48520 | 80 |
| 2026-11-18 | 31211 | 48 |
| 2026-11-19 | 23890 | 39 |
| 2026-11-20 | 25736 | 40 |
| 2026-11-21 | 18111 | 33 |
| 2026-11-22 | 17544 | 34 |

## Registered forward tests (paper)

| test | status | settled / needed | cents per contract | 95% range | note |
|---|---|---|---|---|---|
| inplay_breaker_2026-11-18 | running | 0 / 300 |  |  | 0 scored; other tours 19 |
| inplay_fade_2026-11-18 | running | 51 / 300 | -8.418 | [-17.571, 3.04] | 51 scored |
| inplay_maker_2026-11-19 | running | 39 / 300 | -0.27 | [-4.039, 3.51] | 39 scored matches; -0.27c per contract |
| inplay_serve_out_2026-11-18 | running | 0 / 300 |  |  | 0 scored; other tours 38 |
| kalshi_blend_2026-11-04 | running | 10 / 300 | -1.6 | [-3.544, -0.054] | P&L 1.696c on 10 settled; 5 of 10 clear on signals alone |
| longshot_2026-11-03 | running | 184 / 300 | -2.135 | [-7.344, 2.48] | favourite won 0.8533 |
| season_end_2026-11-03 | running | 68 / 300 | 2.695 | [-8.178, 13.296] | favourite won 0.5 |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 2034 | 5248 | 181.56 | 181.56 | 37.62 |
| 0.05 | 2034 | 1107 | 15.06 | 15.06 | 24.77 |
| join | 2034 | 237576 | -1650.53 | -1650.53 | -364.58 |

run_failures.log: 1 lines

Settle output:
```
h=0.03: markets 2034, contracts 5248, marked $37.62, held $181.56
h=0.05: markets 2034, contracts 1107, marked $24.77, held $15.06
h=join: markets 2034, contracts 237576, marked $-364.58, held $-1650.53
```
