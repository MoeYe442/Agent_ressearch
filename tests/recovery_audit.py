import json
import os
from pathlib import Path
from datetime import datetime,timezone


def write_case(name,values):
    directory=os.getenv('REPOLENS_RECOVERY_AUDIT_DIR')
    run_id=os.getenv('REPOLENS_RECOVERY_AUDIT_RUN')
    if not directory or not run_id:return
    target=Path(directory);target.mkdir(parents=True,exist_ok=True)
    payload={'case':name,'run_id':run_id,'recorded_at':datetime.now(timezone.utc).isoformat(),'synthetic':True,'quality_pass':None,'passed':True,**values}
    (target/(name+'.json')).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
