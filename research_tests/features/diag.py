import pandas as pd, numpy as np, lightgbm as lgb
from sklearn.linear_model import LogisticRegression
from run_features import LGB_BASE, ll
D=pd.read_pickle('features.pkl'); D=D[np.isfinite(D.elo_logit)].reset_index(drop=True)
fc=[c for c in D.columns if c not in ("key","tour","tid","level","date","year","a_key","b_key","y","n_min","retired","group")]
tr=D.year.between(2012,2021).values; y=D.y.values
b=LogisticRegression(C=1e6).fit(D.loc[tr,['elo_logit']],y[tr]); bl=b.decision_function(D[['elo_logit']])
m=lgb.train({**LGB_BASE,'num_leaves':63,'min_data_in_leaf':500,'num_threads':2},lgb.Dataset(D.loc[tr,fc].astype(float),y[tr],init_score=bl[tr]),454)
p=1/(1+np.exp(-(m.predict(D[fc].astype(float),raw_score=True)+bl))); pb=1/(1+np.exp(-bl))
D['d']=ll(y,p)-ll(y,pb); D['p']=p; D['pb']=pb
D.to_pickle('diag_pred.pkl')
s=D[(D.n_min>=18)&(D.year>=2012)]
print(s.groupby(['group','year']).d.mean().unstack(0).round(4))
s=s[s.year.between(2023,2025)]
print(s.groupby(['group','level','stage']).d.agg(['mean','size']).round(4))
print(s.groupby(['group','retired']).d.agg(['mean','size']).round(4))
s=D[(D.n_min>=18)]
print(s.groupby(['group','stage',s.year.clip(2021,2026)]).d.mean().unstack([0,1]).round(4))
