#!/usr/bin/env python3
from __future__ import annotations
import json, urllib.request
from datetime import datetime, timezone
from pathlib import Path

BOT='https://botbounty-production.up.railway.app/api'
WALLET='0x130C29B253B3079FB9ec0D141a4603579Fe5B4d8'
BASE_RPCS=['https://mainnet.base.org','https://base-rpc.publicnode.com']
USDC='0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913'

def get_json(url):
    req=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'final-revenue-probe/1.0'})
    try:
        with urllib.request.urlopen(req,timeout=20) as r: return {'http':r.status,'json':json.loads(r.read().decode())}
    except Exception as e: return {'error':f'{type(e).__name__}: {str(e)[:250]}'}

def rpc(method,params):
    body=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params}).encode()
    for url in BASE_RPCS:
        try:
            req=urllib.request.Request(url,data=body,headers={'Content-Type':'application/json'},method='POST')
            with urllib.request.urlopen(req,timeout=20) as r:
                x=json.loads(r.read().decode())
                if x.get('result') is not None:return x['result']
        except Exception: pass
    return None

def balances():
    eth=rpc('eth_getBalance',[WALLET,'latest'])
    padded=WALLET[2:].lower().rjust(64,'0')
    usdc=rpc('eth_call',[{'to':USDC,'data':'0x70a08231'+padded},'latest'])
    return {
      'eth':int(eth,16)/1e18 if isinstance(eth,str) and eth.startswith('0x') else None,
      'usdc':int(usdc,16)/1e6 if isinstance(usdc,str) and usdc.startswith('0x') else None,
    }
inv=get_json(BOT+'/agent/bounties')
j=inv.get('json')
rows=j if isinstance(j,list) else (j.get('bounties') or j.get('data') or j.get('items') or []) if isinstance(j,dict) else []
preview=[]
for b in rows[:50] if isinstance(rows,list) else []:
    if isinstance(b,dict): preview.append({k:b.get(k) for k in ('id','title','status','amount','reward','currency','category','solver','claimedBy')})
out={'generated_at':datetime.now(timezone.utc).replace(microsecond=0).isoformat(),'wallet':WALLET,'base_balance':balances(),'botbounty_http':inv.get('http'),'botbounty_error':inv.get('error'),'visible_bounty_count':len(rows) if isinstance(rows,list) else 0,'bounties':preview,'expenses_usd':0}
Path('ops-output/final-revenue-probe.json').write_text(json.dumps(out,indent=2,ensure_ascii=False)+'\n')
print(json.dumps(out))
