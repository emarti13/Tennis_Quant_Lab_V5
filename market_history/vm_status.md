# Server status, 2026-10-31T03:30:48+00:00

Code: `a0883ef feat: daily log files gzipped by the server; status page; README setup steps`  
Disk free: 33.5 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active

Tests (FAIL): `1 failed, 251 passed, 7 skipped in 56.11s`

## Problems

- settle failed: TypeError: Can only string multiply by an integer.

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-10-31 | 26 | 4 |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 142 | 282 | -27.32 | -28.38 | 4.39 |
| 0.05 | 142 | 54 | 30.15 | 29.92 | 0.44 |
| join | 142 | 2981 | 144.05 | 133.86 | 3.79 |

run_failures.log: 1 lines

Settle output:
```
hod(self, other, op)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/ubuntu/tql/.venv/lib/python3.12/site-packages/pandas/core/base.py", line 1717, in _arith_method
    result = ops.arithmetic_op(lvalues, rvalues, op)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/ubuntu/tql/.venv/lib/python3.12/site-packages/pandas/core/ops/array_ops.py", line 282, in arithmetic_op
    res_values = op(left, right)
                 ^^^^^^^^^^^^^^^
  File "/home/ubuntu/tql/.venv/lib/python3.12/site-packages/pandas/core/arrays/arrow/array.py", line 1228, in __array_ufunc__
    result = super().__array_ufunc__(ufunc, method, *inputs, **kwargs)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/ubuntu/tql/.venv/lib/python3.12/site-packages/pandas/core/arrays/base.py", line 2966, in __array_ufunc__
    result = arraylike.maybe_dispatch_ufunc_to_dunder_op(
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "pandas/_libs/ops_dispatch.pyx", line 113, in pandas._libs.ops_dispatch.maybe_dispatch_ufunc_to_dunder_op
  File "/home/ubuntu/tql/.venv/lib/python3.12/site-packages/pandas/core/ops/common.py", line 140, in new_method
    return method(self, other)
           ^^^^^^^^^^^^^^^^^^^
  File "/home/ubuntu/tql/.venv/lib/python3.12/site-packages/pandas/core/arraylike.py", line 231, in __rmul__
    return self._arith_method(other, roperator.rmul)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/ubuntu/tql/.venv/lib/python3.12/site-packages/pandas/core/arrays/arrow/array.py", line 1536, in _arith_method
    result = self._evaluate_op_method(other, op, ARROW_ARITHMETIC_FUNCS)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/ubuntu/tql/.venv/lib/python3.12/site-packages/pandas/core/arrays/arrow/array.py", line 1423, in _evaluate_op_method
    raise TypeError("Can only string multiply by an integer.")
TypeError: Can only string multiply by an integer.
```
