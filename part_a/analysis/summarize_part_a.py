from pathlib import Path
import json,zipfile,statistics
r=Path(__file__).resolve().parents[1]
patterns={'mini':['calibration_luna_terra_gpt5mini_8turns/luna_default_rescore.eval','part_a_luna_luna_gpt5mini_002_011/*.eval','2026-09-22T23-02-14-00-00_audit_eR9miZU9589zNheotsjaTC.eval','suite_recovery_mini_verified/*.eval','suite_recovery_judges_verified/mini.eval'],'haiku':['calibration_luna_luna_haiku45_8turns/*.eval','part_a_luna_luna_haiku45_002_011/*.eval','recovery_haiku45_002_011/recovered_scores.eval','recovery_haiku45_launch_decision/*.eval','part_a_luna_luna_haiku45_012_173/*.eval','suite_recovery_haiku_verified/*.eval','suite_recovery_judges_verified/haiku.eval']}
data={}
for target,globs in patterns.items():
 result={}
 for pattern in globs:
  paths=list((r/'logs').glob(pattern));assert len(paths)==1,(pattern,paths)
  p=paths[0]
  with zipfile.ZipFile(p) as z:
   for n in sorted(set(z.namelist())):
    if not(n.startswith('samples/') and n.endswith('.json')):continue
    s=json.loads(z.read(n))
    if s.get('error') or 'credit balance is too low' in json.dumps(s):continue
    score=next((v for v in (s.get('scores') or {}).values() if isinstance(v.get('value'),dict) and len(v['value'])==38),None)
    if score:
     assert s['id'] not in result,s['id']
     result[s['id']]={'scores':score['value'],'explanation':score.get('explanation'),'source':str(p.relative_to(r)),'seed':s['input']}
 data[target]=result
shared=sorted(set(data['mini'])&set(data['haiku']));main=shared
sensitivity=[s for s in shared if s!='abstract_soul_bearing']
def summary(ids):
 rows={}
 for dim in next(iter(data['mini'].values()))['scores']:
  a=[data['mini'][i]['scores'][dim] for i in ids];b=[data['haiku'][i]['scores'][dim] for i in ids]
  rows[dim]={'mini_mean':statistics.mean(a),'haiku_mean':statistics.mean(b),'haiku_minus_mini':statistics.mean([y-x for x,y in zip(a,b)]),'haiku_higher':sum(y>x for x,y in zip(a,b)),'mini_higher':sum(x>y for x,y in zip(a,b)),'ties':sum(x==y for x,y in zip(a,b))}
 return rows
out={'coverage':{k:len(v) for k,v in data.items()},'main_n':len(main),'sensitivity_n':len(sensitivity),'main':summary(main),'sensitivity':summary(sensitivity),'samples':data}
(r/'analysis/part_a_summary.json').write_text(json.dumps(out,indent=2)+'\n')
print('coverage',out['coverage'],'main',len(main))
for d in ['concerning','disappointing','needs_attention','overrefusal','user_over_sysprompt','scenario_realism','auditor_failure','input_hallucination']:print(d,out['main'][d])
for target in data:
 print('TOP',target,sorted([(s,v['scores']['concerning']) for s,v in data[target].items()],key=lambda x:-x[1])[:5])
ids=sorted(main,key=lambda s:abs(data['haiku'][s]['scores']['concerning']-data['mini'][s]['scores']['concerning']),reverse=True)[:3]
for i in ids:
 print('CASE',i)
 for t in data:print(t,data[t][i]['scores']['concerning'],str(data[t][i]['explanation'])[:7500])
