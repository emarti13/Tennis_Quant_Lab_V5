# Server status, 2026-11-26T08:29:48+00:00

Code: `09aab63 feat: paper tracker for registration 2026-11-21 (order-book wall on Kalshi tennis, scored on CLV)`  
Disk free: 31.0 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active  
Live logger command: `/home/ubuntu/tql/.venv/bin/python scripts/log_kalshi_live.py --minutes 1440 --interval 10`  
Live polling gap (median seconds between a match's rows, latest day): 10

Tests (pass): `526 passed, 7 skipped in 81.66s (0:01:21)`

## Problems

- none

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-11-20 | 25736 | 40 |
| 2026-11-21 | 18111 | 33 |
| 2026-11-22 | 47484 | 91 |
| 2026-11-23 | 51065 | 87 |
| 2026-11-24 | 73208 | 91 |
| 2026-11-25 | 50848 | 48 |
| 2026-11-26 | 5547 | 15 |

## Registered forward tests (paper)

| test | status | settled / needed | cents per contract | 95% range | note |
|---|---|---|---|---|---|
| inplay_breaker_2026-11-18 | running | 0 / 300 |  |  | 0 scored; other tours 54 |
| inplay_fade_2026-11-18 | running | 152 / 300 | -5.16 | [-11.056, 1.128] | 152 scored |
| inplay_maker_2026-11-19 | running | 143 / 300 | -1.126 | [-3.051, 0.695] | 143 scored matches; -1.126c per contract |
| inplay_serve_out_2026-11-18 | running | 0 / 300 |  |  | 0 scored; other tours 120 |
| kalshi_blend_2026-11-04 | running | 11 / 300 | -1.359 | [-2.98, 0.083] | P&L -5.045c on 11 settled; 5 of 11 clear on signals alone |
| longshot_2026-11-03 | running | 278 / 300 | -1.427 | [-5.562, 2.345] | favourite won 0.8669 |
| season_end_2026-11-03 | running | 68 / 300 | 2.695 | [-8.178, 13.296] | favourite won 0.5 |
| wall_2026-11-21 | running | 42 / 300 | -1.098 | [-2.009, 0.05] | beat the close 0.429; P&L 3.129c |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 2524 | 9196 | -37.49 | -37.49 | -216.08 |
| 0.05 | 2524 | 3018 | -104.85 | -104.85 | -195.04 |
| join | 2524 | 306799 | -4167.84 | -4167.84 | -951.61 |

run_failures.log: 1 lines

Settle output:
```
h=0.03: markets 2524, contracts 9196, marked $-216.08, held $-37.49
h=0.05: markets 2524, contracts 3018, marked $-195.04, held $-104.85
h=join: markets 2524, contracts 306799, marked $-951.61, held $-4167.84
```
