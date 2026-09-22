from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from v5_tournament_authority import load_authority,audit_authority

def run(path="context_registry/tournament_authority.csv",out="experiments/acceptance/tournament_authority_audit.json"):
    df=load_authority(path); report=audit_authority(df)
    report["authority_contract"]="new tournament table is sole court/tournament truth; OddsPapi permitted only for identity linkage; missing remains missing; legacy court fallback prohibited"
    p=Path(out);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2));return report
if __name__=="__main__": run()
