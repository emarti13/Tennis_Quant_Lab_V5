# Server status, 2026-11-21T08:08:42+00:00

Code: `c749b65 feat: market-following in-play maker for registration 2026-11-19, run daily`  
Disk free: 31.1 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active  
Live logger command: `/home/ubuntu/tql/.venv/bin/python scripts/log_kalshi_live.py --minutes 1440 --interval 10`  
Live polling gap (median seconds between a match's rows, latest day): 10

Tests (pass): `524 passed, 7 skipped in 81.77s (0:01:21)`

## Problems

- none

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-11-15 | 56529 | 91 |
| 2026-11-16 | 47898 | 75 |
| 2026-11-17 | 48520 | 80 |
| 2026-11-18 | 31211 | 48 |
| 2026-11-19 | 23890 | 39 |
| 2026-11-20 | 25736 | 40 |
| 2026-11-21 | 6063 | 11 |

## Registered forward tests (paper)

| test | status | settled / needed | cents per contract | 95% range | note |
|---|---|---|---|---|---|
| inplay_breaker_2026-11-18 | running | 0 / 300 |  |  | 0 scored; other tours 15 |
| inplay_fade_2026-11-18 | running | 32 / 300 | -11.759 | [-21.916, 0.709] | 32 scored |
| inplay_maker_2026-11-19 | running | 24 / 300 | -0.062 | [-5.143, 4.556] | 24 scored matches; -0.062c per contract |
| inplay_serve_out_2026-11-18 | running | 0 / 300 |  |  | 0 scored; other tours 27 |
| kalshi_blend_2026-11-04 | running | 10 / 300 | -1.6 | [-3.544, -0.054] | P&L 1.696c on 10 settled; 5 of 10 clear on signals alone |
| longshot_2026-11-03 | running | 174 / 300 | -1.176 | [-6.25, 3.656] | favourite won 0.8621 |
| season_end_2026-11-03 | running | 68 / 300 | 2.695 | [-8.178, 13.296] | favourite won 0.5 |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 1974 | 4534 | 140.48 | 140.48 | 41.13 |
| 0.05 | 1974 | 840 | 52.99 | 52.99 | 22.48 |
| join | 1974 | 227000 | -1153.04 | -1153.04 | -339.76 |

run_failures.log: 1 lines

Settle output:
```
h=0.03: markets 1974, contracts 4534, marked $41.13, held $140.48
h=0.05: markets 1974, contracts 840, marked $22.48, held $52.99
h=join: markets 1974, contracts 227000, marked $-339.76, held $-1153.04
```
