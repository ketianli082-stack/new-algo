"""Extract audit records from platform console responses; missing rows are explicit."""
import json
import csv

def extract(payload, out):
    records = {}
    decoder = json.JSONDecoder()
    def walk(x):
        if isinstance(x,dict):
            for v in x.values(): walk(v)
        elif isinstance(x,list):
            for v in x: walk(v)
        elif isinstance(x,str):
            for line in x.splitlines():
                marker='TRADE_STATS_V1 '
                if marker not in line: continue
                try:
                    d,_=decoder.raw_decode(line.split(marker,1)[1].lstrip())
                    records[(d['asof'],d['part'],d['key'])]=d['data']
                except (ValueError,KeyError,TypeError): pass
    walk(payload)
    dates=sorted(k[0] for k in records if k[1:] == ('summary','total'))
    result={'status':'MISSING','snapshots':[]}
    for date in dates:
        summary=dict(records[(date,'summary','total')])
        missing=[]
        for part in ('groups','months','reasons','worst'):
            rows={k[2]:v for k,v in records.items() if k[:2]==(date,part)}
            summary[part]=rows
            if len(rows)!=summary.get(part+'_records'): missing.append(part)
        summary['missing_parts']=missing
        result['snapshots'].append(summary)
    if dates:
        latest=result['snapshots'][-1]
        result['status']='PARTIAL' if latest['missing_parts'] else 'SNAPSHOT_COMPLETE'
        for part in ('groups','months','reasons','worst'):
            rows=[dict(key=k,**v) for k,v in latest[part].items()]
            if rows:
                with (out/('trade_stats_'+part+'.csv')).open('w',newline='',encoding='utf-8') as f:
                    writer=csv.DictWriter(f,fieldnames=list(rows[0]))
                    writer.writeheader()
                    writer.writerows(rows)
    (out/'trade_statistics.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result['status']
