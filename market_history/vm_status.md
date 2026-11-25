# Server status, 2026-11-25T08:27:13+00:00

Code: `09aab63 feat: paper tracker for registration 2026-11-21 (order-book wall on Kalshi tennis, scored on CLV)`  
Disk free: 31.0 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active  
Live logger command: `/home/ubuntu/tql/.venv/bin/python scripts/log_kalshi_live.py --minutes 1440 --interval 10`  
Live polling gap (median seconds between a match's rows, latest day): 10

Tests (pass): `526 passed, 7 skipped in 83.31s (0:01:23)`

## Problems

- none

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-11-19 | 23890 | 39 |
| 2026-11-20 | 25736 | 40 |
| 2026-11-21 | 18111 | 33 |
| 2026-11-22 | 47484 | 91 |
| 2026-11-23 | 51065 | 87 |
| 2026-11-24 | 73208 | 91 |
| 2026-11-25 | 21913 | 24 |

## Registered forward tests (paper)

| test | status | settled / needed | cents per contract | 95% range | note |
|---|---|---|---|---|---|
| inplay_breaker_2026-11-18 | running | 0 / 300 |  |  | 0 scored; other tours 46 |
| inplay_fade_2026-11-18 | running | 132 / 300 | -3.376 | [-9.874, 3.688] | 132 scored |
| inplay_maker_2026-11-19 | running | 121 / 300 | -1.357 | [-3.458, 0.58] | 121 scored matches; -1.357c per contract |
| inplay_serve_out_2026-11-18 | running | 0 / 300 |  |  | 0 scored; other tours 104 |
| kalshi_blend_2026-11-04 | running | 11 / 300 | -1.359 | [-2.98, 0.083] | P&L -5.045c on 11 settled; 5 of 11 clear on signals alone |
| longshot_2026-11-03 | running | 267 / 300 | -1.704 | [-5.967, 2.169] | favourite won 0.8652 |
| season_end_2026-11-03 | running | 68 / 300 | 2.695 | [-8.178, 13.296] | favourite won 0.5 |
| wall_2026-11-21 | running | 36 / 300 | -0.887 | [-1.969, 0.369] | beat the close 0.472; P&L 3.042c |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 2456 | 9066 | -43.77 | -43.77 | -215.72 |
| 0.05 | 2456 | 2943 | -98.57 | -98.57 | -195.99 |
| join | 2456 | 297327 | -4070.41 | -4070.41 | -899.99 |

run_failures.log: 1 lines

Settle output:
```
h=0.03: markets 2456, contracts 9066, marked $-215.72, held $-43.77
h=0.05: markets 2456, contracts 2943, marked $-195.99, held $-98.57
h=join: markets 2456, contracts 297327, marked $-899.99, held $-4070.41
```
