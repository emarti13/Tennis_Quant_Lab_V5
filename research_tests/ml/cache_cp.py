"""Compute leak-free serve/return skills and court pace per match key (cached)."""
import sys, importlib.util, time
from pathlib import Path
REPO = Path("/home/user/Tennis_Quant_Lab_V5"); HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
import pandas as pd
spec = importlib.util.spec_from_file_location("cp", HERE / "court_pace_src.py"); cp = importlib.util.module_from_spec(spec); spec.loader.exec_module(cp)
t = time.time()
m = pd.read_pickle(HERE.parents[1] / "matches_serve.pkl")
m = m[m["date"] < pd.Timestamp("2026-10-13")]   # nothing from the sealed period
f = cp.run(m)
f.to_pickle(HERE / "cp_feats.pkl"); print(f.shape, time.time() - t)
