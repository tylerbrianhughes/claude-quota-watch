"""Read-only local transcript accounting. No model calls or network requests."""
from datetime import datetime
import json
from pathlib import Path
import threading
import time

# USD per million: input, output, 5m write, 1h write, cache read.
# Anthropic global standard list prices, verified 2026-09-24.
PRICE_SOURCE = 'https://platform.claude.com/docs/en/about-claude/pricing'
PRICES = {
    'claude-fable-5-1': (10,50,12.5,20,.25),
    'claude-mythos-5-1': (10,50,12.5,20,.25),
    'claude-fable-5': (10,50,12.5,20,1),
    'claude-mythos-5': (10,50,12.5,20,1),
    'claude-opus-5-5': (4,20,5,8,.2),
    'claude-opus-5': (5,25,6.25,10,.5),
    'claude-sonnet-5': (2,10,2.5,4,.2),
    'claude-haiku-4-5': (1,5,1.25,2,.1),
    **{f'claude-opus-4-{v}': (5,25,6.25,10,.5) for v in (5,6,7,8)},
    **{f'claude-sonnet-4-{v}': (3,15,3.75,6,.3) for v in (5,6)},
}
KEYS=('input_tokens','output_tokens','cache_creation_input_tokens','cache_read_input_tokens')

def count(value):
    return value if isinstance(value,int) and not isinstance(value,bool) and value>=0 else 0

def price(model, usage):
    rates=next((v for k,v in sorted(PRICES.items(),key=lambda x:-len(x[0]))
                if model==k or (model.startswith(k+'-') and model[len(k)+1:].isdigit() and len(model[len(k)+1:])==8)),None)
    if rates is None: return None
    i,o,w5,w1,r=rates
    cache=usage.get('cache_creation') or {}
    one=count(cache.get('ephemeral_1h_input_tokens'))
    five=count(cache.get('ephemeral_5m_input_tokens'))
    # Older logs omit cache TTL: a range is safer than assuming cheap writes.
    unclassified=max(0,count(usage.get('cache_creation_input_tokens'))-one-five)
    base=count(usage.get('input_tokens'))*i+count(usage.get('output_tokens'))*o+five*w5+one*w1+count(usage.get('cache_read_input_tokens'))*r
    multiplier=(2 if usage.get('speed')=='fast' else 1)*(1.1 if usage.get('inference_geo')=='us' else 1)
    return [(base+unclassified*w)*multiplier/1e6 for w in (w5,w1)]

class Throughput:
    def __init__(self, roots):
        self.roots=[Path(p).expanduser().resolve() for p in roots]
        self.offsets={};self.events={};self.snapshot={'state':'loading'}
        self.stop=threading.Event()
    def ingest(self, record, now):
        m=record.get('message')
        if record.get('type')!='assistant' or not isinstance(m,dict) or not isinstance(m.get('usage'),dict):return
        model=m.get('model','')
        if not model.startswith('claude-'):return
        try:t=datetime.fromisoformat(record['timestamp'].replace('Z','+00:00')).timestamp()
        except (KeyError,ValueError,TypeError):return
        if not now-3600<=t<=now:return
        key=(record.get('requestId'),m.get('id'))
        if not any(key):return
        usage=m['usage'];old=self.events.get(key)
        # Multiple content blocks / copied transcripts repeat cumulative message usage.
        if old:
            merged=dict(old['usage'])
            for k in KEYS:merged[k]=max(count(merged.get(k)),count(usage.get(k)))
            for k in ('cache_creation','speed','inference_geo'):
                if usage.get(k) is not None:merged[k]=usage[k]
            usage=merged;t=max(t,old['at'])
        self.events[key]={'at':t,'model':model,'usage':usage}
    def summarize(self,now):
        windows=[]
        for minutes in (15,60):
            entries=[v for v in self.events.values() if now-minutes*60<=v['at']<=now]
            totals={k:sum(count(v['usage'].get(k)) for v in entries) for k in KEYS}
            costs=[price(v['model'],v['usage']) for v in entries]
            unknown=sorted({v['model'] for v,c in zip(entries,costs) if c is None})
            windows.append({'minutes':minutes,'requests':len(entries),'tokens':totals,
                            'processed_per_hour':sum(totals.values())*60/minutes,
                            'output_per_hour':totals['output_tokens']*60/minutes,
                            'usd_per_hour_low':sum(c[0] for c in costs if c)*60/minutes,
                            'usd_per_hour_high':sum(c[1] for c in costs if c)*60/minutes,
                            'unpriced_models':unknown})
        return {'state':'ready','checked_at':now,'roots':len(self.roots),'windows':windows,
                'price_source':PRICE_SOURCE,'price_date':'2026-09-24',
                'latest_message_at':max((v['at'] for v in self.events.values()),default=None)}
    def scan(self):
        now=time.time();errors=0
        for root in self.roots:
            if not (root/'projects').is_dir():errors+=1;continue
            for f in (root/'projects').rglob('*.jsonl'):
                try:
                    st=f.stat()
                    if st.st_mtime<now-3600:continue
                    offset, inode=self.offsets.get(f,(0,st.st_ino))
                    if inode!=st.st_ino or st.st_size<offset:offset=0
                    if offset==st.st_size:continue
                    with f.open('rb') as h:
                        h.seek(offset)
                        while True:
                            start=h.tell();line=h.readline()
                            if not line or not line.endswith(b'\n'):
                                offset=start;break
                            if b'"usage"' not in line or not (b'"type":"assistant"' in line or b'"type": "assistant"' in line):continue
                            try:self.ingest(json.loads(line),time.time())
                            except (ValueError,TypeError,AttributeError):pass
                    self.offsets[f]=(offset,st.st_ino)
                except OSError:errors+=1
        now=time.time()
        self.events={k:v for k,v in self.events.items() if v['at']>=now-3600}
        result=self.summarize(now);result['read_errors']=errors
        self.snapshot=result
    def run(self):
        while not self.stop.is_set():
            try:self.scan()
            except Exception:self.snapshot={'state':'error','checked_at':time.time()}
            self.stop.wait(60)
    def start(self):
        threading.Thread(target=self.run,daemon=True,name='local-throughput').start()
