"""One-off: rebuild walkforward_cache.pkl after the first full run crashed in evaluation
(test_predictions.pkl was saved). Point params and first-server priors are refit (cheap,
deterministic: same seed and sample); per-fold validation log losses are parsed from the log."""
import ast, os, pickle, re, sys
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "run_totals.py")).read()
src = src[:src.index("# ====================================================================== walk-forward")]
g = {"__file__": os.path.join(HERE, "run_totals.py"), "__name__": "rt"}
exec(compile(src, "run_totals_head", "exec"), g)
FOLD, PI = {}, {}
for Y in g["TEST_YEARS"]:
    trm = g["D"][(g["D"]["year"] <= Y - 2) & ~g["D"]["void"] & g["D"]["q_close"].notna() & g["D"]["s_hat"].notna()]
    par = g["fit_point"](trm)
    pif, cond = g["fit_pi"](par, Y - 2)
    PI[Y] = pif; FOLD[Y] = {"point_params": par, "first_server_prior": pif}
    print(Y, par, pif["conditional"], flush=True)
cur = None
for line in open(os.path.join(HERE, "run_walkforward.log")):
    m = re.search(r"fold (\d{4})", line)
    if m: cur = int(m.group(1))
    m = re.search(r"  (tot|hcp)\|(close|open) val (\{.*\}) chosen (\w+) rounds (\d+)", line)
    if m and cur:
        FOLD[cur][f"{m.group(1)}|{m.group(2)}"] = {"val_logloss": ast.literal_eval(m.group(3)), "chosen": m.group(4), "lgb_rounds": int(m.group(5))}
PR = pd.read_pickle(os.path.join(HERE, "test_predictions.pkl"))
with open(os.path.join(HERE, "walkforward_cache.pkl"), "wb") as fh:
    pickle.dump((PR, FOLD, PI), fh)
print("ok", len(PR))
