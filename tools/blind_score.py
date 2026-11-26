#!/usr/bin/env python3
"""Score an output folder against a truth.json {"pii":[{file,kind,value}],"medical":[...]} (per-file, decodes base64/percent).
Usage: blind_score.py INPUT_DIR OUTPUT_DIR TRUTH_JSON. Used for the blind layout test (set written by a separate agent)."""
import json,os,base64,urllib.parse,collections,re,hashlib,sys
inp,out,truthp=sys.argv[1:4]
t=json.load(open(truthp)); r=json.load(open(out+'/report.json'))
sha={}
for d,_,fs in os.walk(inp):
    for f in fs:
        p=os.path.join(d,f); sha[os.path.relpath(p,inp)]=hashlib.sha256(open(p,'rb').read()).hexdigest()
omap={e['input_sha256']:e.get('output') for e in r['files'] if e['status']=='sanitized'}
def view(rel):
    o=omap.get(sha.get(rel))
    if not o: return None
    s=open(os.path.join(out,o),encoding='utf-8',errors='replace').read()+"\n"+o
    d=s
    for m in re.finditer(r'[A-Za-z0-9+/]{16,}={0,2}',s):
        try: d+="\n"+base64.b64decode(m.group()+'='*(-len(m.group())%4)).decode()
        except Exception: pass
    return (d+"\n"+urllib.parse.unquote(s)).casefold()
cache={}
norm=lambda s: re.sub(r'\s+','',s).casefold()
leak=collections.Counter(); tot=collections.Counter(); ex=[]; q=0
for e in t['pii']:
    k=e['kind']; tot[k]+=1
    v=cache.setdefault(e['file'],view(e['file']))
    if v is None: q+=1; continue
    val=e['value']; cands=[val]
    for fn in (lambda x: base64.b64decode(x+'='*(-len(x)%4)).decode(), urllib.parse.unquote):
        try: cands.append(fn(val))
        except Exception: pass
    if any(c.casefold() in v or (len(norm(c))>=6 and norm(c) in norm(v)) for c in cands if len(c)>=3):
        leak[k]+=1; ex.append((e['file'],k,val))
print({k:f"{leak[k]}/{tot[k]}" for k in tot}); print("LEAKED",sum(leak.values()),"of",sum(tot.values()),"(in quarantined files:",q,")")
mk=0
for e in t['medical']:
    v=cache.setdefault(e['file'],view(e['file']))
    if v and e['value'].casefold() in v: mk+=1
print("medical kept",mk,"/",len(t['medical']))
json.dump(ex,open('/tmp/blind_leaks.json','w'),ensure_ascii=False)
for x in ex: print(x)
