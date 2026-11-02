# Server status, 2026-11-02T07:20:04+00:00

Code: `c2adc29 fix: paper settle crashed on pandas 3.1 for markets with no fills in a setting`  
Disk free: 33.3 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active

Tests (pass): `493 passed, 7 skipped in 92.27s (0:01:32)`

## Problems

- settle failed: TypeError: Can only string multiply by an integer.

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-10-31 | 10237 | 47 |
| 2026-11-01 | 18593 | 92 |
| 2026-11-02 | 2600 | 11 |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 142 | 282 | -27.32 | -28.38 | 4.39 |
| 0.05 | 142 | 54 | 30.15 | 29.92 | 0.44 |
| join | 142 | 2981 | 144.05 | 133.86 | 3.79 |

run_failures.log: 1 lines

Settle output:
```
  File "/home/ubuntu/tql/scripts/paper_trade_kalshi.py", line 397, in <module>
    raise SystemExit(main())
  File "/home/ubuntu/tql/scripts/paper_trade_kalshi.py", line 374, in main
    out = settle(api)
  File "/home/ubuntu/tql/scripts/paper_trade_kalshi.py", line 352, in settle
    "end_position": float((f["contracts"] * f["side"].map({"buy": 1, "sell": -1})).sum())}
TypeError: Can only string multiply by an integer.
```
