#!/usr/bin/env python3
from __future__ import annotations
import json, urllib.request
from datetime import datetime, timezone
from pathlib import Path

API='https://api.taskmarket.dev'
TASKS={
 'bubble_brawl':'0xc0654d7b1a1dc86ad4d9bb00187b1e32f929094f614c3fe4ca0305c0bffcedf9',
 'signal_panic':'0xff2d1349413ba161506a724b74b2755c479c5b70ed57faaf90fc69643becf8d6',
}
KNOWN={
 'bubble_brawl': {'submission_id':'c5a4db0b-45e2-4ae3-8be5-4265bbe3931a','worker':'0xd9d5932c03B2164832079AAD511143D3dc18F2BA'},
}

def get(path):
    req=urllib.request.Request(API+path,headers={'Accept':'application/json','User-Agent':'final-income-status-probe/1.0'})
    try:
        with urllib.request.urlopen(req,timeout=30) as r:
            raw=r.read(4_000_000)
            return {'http':r.status,'json':json.loads(raw.decode())}
    except Exception as e:
        return {'error':f'{type(e).__name__}: {str(e)[:300]}'}

def safe_submission(x):
    if not isinstance(x,dict): return None
    return {k:x.get(k) for k in ('id','submissionId','status','state','selected','winner','accepted','awarded','paid','paymentStatus','settlementStatus','createdAt','updatedAt','workerAddress','worker') if k in x}

out={'generated_at':datetime.now(timezone.utc).replace(microsecond=0).isoformat(),'tasks':{},'expenses_usdc':0}
for name,tid in TASKS.items():
    task=get(f'/api/tasks/{tid}')
    subs=get(f'/api/tasks/{tid}/submissions')
    taskj=task.get('json') if isinstance(task.get('json'),dict) else {}
    rows=subs.get('json')
    if isinstance(rows,dict): rows=rows.get('submissions') or rows.get('data') or rows.get('items') or []
    if not isinstance(rows,list): rows=[]
    known=KNOWN.get(name,{})
    matches=[]
    for x in rows:
        if not isinstance(x,dict): continue
        sid=str(x.get('id') or x.get('submissionId') or '')
        worker=str(x.get('workerAddress') or x.get('worker') or '')
        if (known.get('submission_id') and sid==known['submission_id']) or (known.get('worker') and worker.lower()==known['worker'].lower()):
            matches.append(safe_submission(x))
    out['tasks'][name]={
      'task_id':tid,
      'task_http':task.get('http'),'submissions_http':subs.get('http'),
      'task_status':taskj.get('status'),'task_phase':taskj.get('phase'),
      'winner':taskj.get('winner') or taskj.get('winnerAddress') or taskj.get('workerAgentId'),
      'selected_submission_id':taskj.get('selectedSubmissionId') or taskj.get('winningSubmissionId'),
      'payment_status':taskj.get('paymentStatus') or taskj.get('settlementStatus'),
      'reward':taskj.get('reward'),'net_reward':taskj.get('netReward'),
      'submission_count':taskj.get('submissionCount'),'known_matches':matches,
      'errors':[v['error'] for v in (task,subs) if 'error' in v],
    }
Path('taskmarket-output/final-status.json').write_text(json.dumps(out,indent=2,ensure_ascii=False)+'\n')
print(json.dumps(out))
