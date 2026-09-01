
from __future__ import annotations
import math
from dataclasses import dataclass
from collections import defaultdict, Counter
import numpy as np
import pandas as pd

SURFACES=("Hard","Clay","Grass")

def logistic(x):
    if x>=0:
        z=math.exp(-x); return 1/(1+z)
    z=math.exp(x); return z/(1+z)

def logit(p):
    p=min(max(float(p),1e-6),1-1e-6)
    return math.log(p/(1-p))

def american_from_prob(p):
    p=min(max(float(p),1e-6),1-1e-6)
    return round(-100*p/(1-p)) if p>=.5 else round(100*(1-p)/p)

@dataclass
class Skill:
    serve:float=0.0
    ret:float=0.0
    n_points:float=0.0
    last_ord:int=0

@dataclass
class FormState:
    form:float=0.0
    var:float=0.010
    matches:int=0
    last_ord:int=0

@dataclass
class EloSkill:
    overall:float=1500.0
    hard:float=1500.0
    clay:float=1500.0
    grass:float=1500.0
    matches:int=0

class DynamicServeReturn:
    def __init__(self,baseline,global_lr=.12,surface_lr=.16,surface_weight=.55,
                 shrink_points=350.0,half_life_matches=1600,
                 form_alpha=.20,var_alpha=.12,form_cap=.22):
        self.baseline={k:logit(v) for k,v in baseline.items()}
        self.global_lr=global_lr; self.surface_lr=surface_lr
        self.surface_weight=surface_weight; self.shrink_points=shrink_points
        self.half_life_matches=half_life_matches
        self.form_alpha=form_alpha; self.var_alpha=var_alpha; self.form_cap=form_cap
        self.g=defaultdict(Skill); self.s=defaultdict(Skill)
        self.form=defaultdict(FormState); self.form_surf=defaultdict(FormState)

    def _decay(self,skill,ord_):
        gap=max(0,ord_-skill.last_ord)
        if gap and self.half_life_matches:
            d=.5**(gap/self.half_life_matches)
            skill.serve*=d; skill.ret*=d
        skill.last_ord=ord_

    def point_prob(self,server,returner,surface,ord_=0,include_form=False):
        surface=surface if surface in SURFACES else "Hard"
        gs=self.g[server]; gr=self.g[returner]
        ss=self.s[(server,surface)]; sr=self.s[(returner,surface)]
        for x in (gs,gr,ss,sr): self._decay(x,ord_)
        ws=min(1.0,(ss.n_points+sr.n_points)/(2*self.shrink_points))
        eta=self.baseline[surface]+gs.serve-gr.ret+self.surface_weight*ws*(ss.serve-sr.ret)
        if include_form:
            eta += .55*(self.form[server].form-self.form[returner].form)
            eta += .25*(self.form_surf[(server,surface)].form-self.form_surf[(returner,surface)].form)
        return logistic(eta)

    def update_server(self,server,returner,surface,won,total,ord_):
        if pd.isna(total) or pd.isna(won) or float(total)<10: return None
        total=float(total); won=float(won)
        obs=min(max(won/total,.02),.98)
        p=self.point_prob(server,returner,surface,ord_,False)
        err=obs-p; q=min(1.5,math.sqrt(total/60))
        self.g[server].serve += self.global_lr*q*err
        self.g[returner].ret -= self.global_lr*q*err
        self.s[(server,surface)].serve += self.surface_lr*q*err
        self.s[(returner,surface)].ret -= self.surface_lr*q*err
        for skill in (self.g[server],self.g[returner],self.s[(server,surface)],self.s[(returner,surface)]):
            skill.n_points += total; skill.last_ord=ord_
        return logit(obs)-logit(p)

    def _update_form(self,fs,resid,ord_):
        resid=max(-self.form_cap,min(self.form_cap,float(resid)))
        prior=fs.form
        fs.form=(1-self.form_alpha)*fs.form+self.form_alpha*resid
        innovation=resid-prior
        fs.var=(1-self.var_alpha)*fs.var+self.var_alpha*(innovation*innovation)
        fs.matches+=1; fs.last_ord=ord_

    def update_match(self,row,ord_):
        surf=str(row.get("surface","Hard")).title()
        if surf not in SURFACES: surf="Hard"
        w=row.get("winner_name"); l=row.get("loser_name")
        wsv=pd.to_numeric(row.get("w_svpt"),errors="coerce")
        lsv=pd.to_numeric(row.get("l_svpt"),errors="coerce")
        ww=pd.to_numeric(row.get("w_1stWon"),errors="coerce")+pd.to_numeric(row.get("w_2ndWon"),errors="coerce")
        lw=pd.to_numeric(row.get("l_1stWon"),errors="coerce")+pd.to_numeric(row.get("l_2ndWon"),errors="coerce")
        wr=self.update_server(w,l,surf,ww,wsv,ord_)
        lr=self.update_server(l,w,surf,lw,lsv,ord_)
        if wr is not None and lr is not None:
            perf=.5*(wr-lr)
            self._update_form(self.form[w],perf,ord_); self._update_form(self.form[l],-perf,ord_)
            self._update_form(self.form_surf[(w,surf)],perf,ord_); self._update_form(self.form_surf[(l,surf)],-perf,ord_)

    def current_state(self,p,surf):
        fg=self.form[p]; fs=self.form_surf[(p,surf)]
        sw=min(1.0,fs.matches/8.0)
        form_logit=.70*fg.form+.30*sw*fs.form
        raw_var=.70*max(.0005,fg.var)+.30*sw*max(.0005,fs.var)
        raw_vol=math.sqrt(max(.0005,raw_var))
        return {"form_logit":form_logit,"raw_day_vol_logit":raw_vol,
                "form_matches":fg.matches,"surface_form_matches":fs.matches}

class SurfaceElo:
    def __init__(self,k=28.0,surface_blend=.65):
        self.k=k; self.surface_blend=surface_blend; self.players=defaultdict(EloSkill)
    def _attr(self,s): return {"Hard":"hard","Clay":"clay","Grass":"grass"}.get(s,"hard")
    def probability(self,a,b,s):
        pa=self.players[a]; pb=self.players[b]; at=self._attr(s)
        ra=(1-self.surface_blend)*pa.overall+self.surface_blend*getattr(pa,at)
        rb=(1-self.surface_blend)*pb.overall+self.surface_blend*getattr(pb,at)
        return 1/(1+10**((rb-ra)/400))
    def update(self,w,l,s):
        p=self.probability(w,l,s); ew=self.players[w]; el=self.players[l]
        delta=self.k*(1-p)
        ew.overall+=delta; el.overall-=delta; at=self._attr(s)
        setattr(ew,at,getattr(ew,at)+delta); setattr(el,at,getattr(el,at)-delta)
        ew.matches+=1; el.matches+=1
    def snapshot(self,n,s):
        p=self.players[n]; at=self._attr(s)
        return {"elo":p.overall,"surface_elo":getattr(p,at),"elo_matches":p.matches}

def _sim_game(rng,p):
    a=b=0
    while True:
        if rng.random()<p:a+=1
        else:b+=1
        if (a>=4 or b>=4) and abs(a-b)>=2:return a>b

def _sim_tb(rng,pa,pb,firstA):
    a=b=0;pt=0
    while True:
        if pt==0: serverA=firstA
        else:
            block=(pt-1)//2
            serverA=(not firstA) if block%2==0 else firstA
        awin=(rng.random()<pa) if serverA else (rng.random()<(1-pb))
        if awin:a+=1
        else:b+=1
        pt+=1
        if (a>=7 or b>=7) and abs(a-b)>=2:return a>b

def _sim_set(rng,pa,pb,firstA=True):
    ga=gb=0; serverA=firstA
    while True:
        if ga==6 and gb==6:
            if _sim_tb(rng,pa,pb,serverA):ga+=1
            else:gb+=1
            return ga,gb,not firstA
        awin=_sim_game(rng,pa) if serverA else (not _sim_game(rng,pb))
        if awin:ga+=1
        else:gb+=1
        serverA=not serverA
        if (ga>=6 or gb>=6) and abs(ga-gb)>=2:return ga,gb,serverA

def _clean_market_lines(lines, default):
    source=default if lines is None else lines
    out=[]
    for value in source:
        try:v=float(value)
        except Exception:continue
        if math.isfinite(v) and v not in out:out.append(v)
    return sorted(out)

def _spread_key(line):
    return f"{float(line):+.1f}"

def _total_key(line):
    return f"{float(line):.1f}"

def simulate_match(pAserve,pBserve,best_of=3,n=20000,seed=42,
                   formA=0.0,formB=0.0,volA=0.0,volB=0.0,state_variation=True,
                   spread_lines=None,total_lines=None):
    rng=np.random.default_rng(seed); need=best_of//2+1
    wins=0;marg=[];tot=[];score=Counter();tbs=0; sas=[];sbs=[]
    ea=logit(pAserve); eb=logit(pBserve)
    for _ in range(int(n)):
        if state_variation:
            shA=rng.normal(formA,volA); shB=rng.normal(formB,volB)
        else:
            shA=formA; shB=formB
        diff=shA-shB
        pa=min(.88,max(.42,logistic(ea+.50*diff)))
        pb=min(.88,max(.42,logistic(eb-.50*diff)))
        sas.append(pa); sbs.append(pb)
        sa=sb=ga=gb=0; first=bool(rng.integers(0,2)); tb=False
        while sa<need and sb<need:
            xa,xb,first=_sim_set(rng,pa,pb,first)
            ga+=xa;gb+=xb
            if (xa==7 and xb==6) or (xb==7 and xa==6):tb=True
            if xa>xb:sa+=1
            else:sb+=1
        wins+=sa>sb;marg.append(ga-gb);tot.append(ga+gb);score[f"{sa}-{sb}"]+=1;tbs+=tb
    m=np.asarray(marg);t=np.asarray(tot);sas=np.asarray(sas);sbs=np.asarray(sbs)
    default_spreads=[-6.5,-5.5,-4.5,-3.5,-2.5,-1.5,1.5,2.5,3.5,4.5,5.5,6.5]
    default_totals=[18.5,19.5,20.5,21.5,22.5,23.5,24.5,25.5,26.5]
    spread_lines=_clean_market_lines(spread_lines,default_spreads)
    total_lines=_clean_market_lines(total_lines,default_totals)
    spread={_spread_key(line):float(np.mean(m+line>0)) for line in spread_lines}
    spread_push={_spread_key(line):float(np.mean(np.isclose(m+line,0.0))) for line in spread_lines}
    over={_total_key(line):float(np.mean(t>line)) for line in total_lines}
    total_push={_total_key(line):float(np.mean(np.isclose(t-line,0.0))) for line in total_lines}
    return {
        "pA_win":wins/n,"fair_A":american_from_prob(wins/n),"fair_B":american_from_prob(1-wins/n),
        "expected_margin":float(m.mean()),"expected_total":float(t.mean()),
        "score_probs":{k:v/n for k,v in score.items()},"tiebreak_prob":tbs/n,
        "spread":spread,"spread_push":spread_push,
        "over":over,"total_push":total_push,
        "margin_sd":float(m.std()),"total_sd":float(t.std()),
        "sampled_serve_A_mean":float(sas.mean()),"sampled_serve_B_mean":float(sbs.mean()),
        "sampled_serve_A_sd":float(sas.std()),"sampled_serve_B_sd":float(sbs.std()),
        "sampled_serve_A_p10":float(np.quantile(sas,.10)),"sampled_serve_A_p90":float(np.quantile(sas,.90)),
        "sampled_serve_B_p10":float(np.quantile(sbs,.10)),"sampled_serve_B_p90":float(np.quantile(sbs,.90))
    }
