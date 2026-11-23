"""恒久の純q0を原板へ結合し、201の金融なし板特徴を保存する。"""
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import re
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'work/pythonlibs'))
import numpy as np
import orjson
from 特徴核 import State, NAMES

HERE=Path(__file__).parent
DEST=ROOT/'inputs/00201_両指数の板数量純特徴'
DATA=ROOT.parent/'JP_OSE_Data/future'
ADD=ROOT/'inputs/00194_20261116夜と1117昼の固定適用入力'
PLAN=DEST/'抽出前固定.json.gz'
JST=timezone(timedelta(hours=9))
QINPUTS=[('NK225','181旧73','inputs/00148_全1分入口母集団/当時特徴.json.gz'),
 ('NK225','181追加7','inputs/00167_追加七場の入口と共用価格索引/入口母集団/当時特徴.json.gz'),
 ('NK225','181本日1','inputs/00180_20261116デイの固定適用入力/入口母集団/当時特徴.json.gz'),
 ('NK225','194追加2','inputs/00194_20261116夜と1117昼の固定適用入力/NK225/入口母集団/当時特徴.json.gz'),
 ('TOPIX','183旧','inputs/TOPIX原順8列_20260921_20261116/純特徴183.json.gz'),
 ('TOPIX','184直接','inputs/TOPIX原順8列_20260921_20261116/純特徴184直接.json.gz'),
 ('TOPIX','194旧','inputs/00194_20261116夜と1117昼の固定適用入力/TOPIX/純特徴183.json.gz'),
 ('TOPIX','194直接','inputs/00194_20261116夜と1117昼の固定適用入力/TOPIX/純特徴184直接.json.gz')]


# ----------------------------------------
def read(path):
    """
    機能: JSON又はgzip JSONを読む。
    引数: path(Path)は対象。
    返り値: objectは解析結果。
    """
    with gzip.open(path,'rb') if path.suffix=='.gz' else path.open('rb') as f:
        return orjson.loads(f.read())


# ----------------------------------------
def ref(path):
    """
    機能: 入力を変更せず物理ファイルのSHAとstatを採取する。
    引数: path(Path)は対象。
    返り値: dictは絶対path・byte・SHA・mtime。
    """
    before=path.stat()
    with path.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    after=path.stat()
    assert (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns)
    return dict(path=str(path.resolve()),bytes=after.st_size,sha256=digest,mtime_ns=after.st_mtime_ns)


# ----------------------------------------
def save(path,value):
    """
    機能: 新規成果物を保存し、既存なら同一内容だけを許す。
    引数: path(Path)、value(object)は出力先とJSON値。
    返り値: dictはファイル指紋。
    """
    raw=(json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode()
    body=gzip.compress(raw,compresslevel=6,mtime=0) if path.suffix=='.gz' else raw
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():assert path.read_bytes()==body,('既存内容相違',path)
    else:path.write_bytes(body)
    return ref(path)


# ----------------------------------------
def clock(value):
    """
    機能: 既存Goと同じRFC3339NanoのUNIX秒表現へ変換する。
    引数: value(any)は現値時刻。
    返り値: float|Noneは時計又は欠測。
    """
    if not isinstance(value,str):return None
    m=re.fullmatch(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:[.,](\d+))?(Z|[+-]\d{2}:\d{2})',value)
    if not m:return None
    try:
        d=datetime.fromisoformat(m[1]+m[3].replace('Z','+00:00'))
        return float(int(d.timestamp())*1_000_000_000+int(((m[2] or '')+'000000000')[:9]))/1e9
    except ValueError:return None


# ----------------------------------------
def edges(session):
    """
    機能: 場の原板時計範囲を作る。金融終了条件は変更しない。
    引数: session(str)は場名。
    返り値: tuple[float,float]は開始終了。
    """
    day=datetime.fromisoformat(session[:10]).replace(tzinfo=JST)
    a,b=((day+timedelta(hours=8,minutes=45),day+timedelta(hours=15,minutes=45))
         if session.endswith('Day') else (day+timedelta(hours=17),day+timedelta(days=1,hours=6)))
    return a.timestamp(),b.timestamp()


# ----------------------------------------
def prepare():
    """
    機能: 全83場の純q0、原板SHA、Source、仕様、人工検査を抽出前に固定する。
    引数: なし。
    返り値: dictは固定入力。金融入力を一切使用しない。
    """
    refs=[];groups={}
    for symbol,identity,name in QINPUTS:
        path=ROOT/name;refs.append(ref(path));value=read(path)
        if symbol=='NK225':assert value.get('financial_labels_used') is False
        rows=value['rows'] if symbol=='NK225' else value
        for row in rows:
            q=row['metadata']['q0'] if symbol=='NK225' else row
            line=int(q['source_line'] if symbol=='NK225' else q['line'])
            target=groups.setdefault((symbol,row['session']),{}).setdefault(line,dict(line=line,time=q['time'],members=[]))
            assert target['time']==q['time']
            target['members'].append(identity)
            if symbol=='NK225':target.update(last=q['last'],bid=q['bid'],ask=q['ask'])
    n=ROOT/'inputs/NK225原順8列_20260921_20261116/入力台帳.json.gz'
    t=ROOT/'inputs/TOPIX原順8列_20260921_20261116/台帳.json'
    z=ADD/'原順8列/入力台帳.json'
    refs.extend(ref(p) for p in (n,t,z))
    original={('NK225',r['session']):r['sha256_uncompressed'] for r in read(n)['entries']}
    original.update({('TOPIX',r['session']):r['原板']['sha256'] for r in read(t)['entries']})
    extra=read(z)['entries']
    original.update({(r['symbol'],r['session']):r['sha256_uncompressed'] for r in extra})
    artificial=read(HERE/'人工確認.json');assert artificial['成功'] and not artificial['金融参照']
    for item in artificial['Source']:assert ref(HERE/item['path'])['sha256']==item['sha256']
    scenes=[]
    for (symbol,session),target in sorted(groups.items()):
        folder=DATA/symbol/session
        raw=folder/('book.jsonl.gz' if (folder/'book.jsonl.gz').exists() else 'book.jsonl')
        cache=None
        if symbol=='TOPIX':
            cache=ROOT/'inputs/TOPIX原順8列_20260921_20261116'/(session+'.npz')
            if not cache.exists():cache=ADD/'原順8列/TOPIX'/(session+'.npz')
            cache_ref=ref(cache);refs.append(cache_ref)
            with np.load(cache,allow_pickle=False) as packed:
                values={name:packed[name] for name in ('line','now','last','bid','ask')}
            for line,q in target.items():
                pos=int(np.searchsorted(values['line'],line))
                assert pos<len(values['line']) and int(values['line'][pos])==line
                assert float(values['now'][pos])==q['time']
                q.update(last=float(values['last'][pos]),bid=float(values['bid'][pos]),ask=float(values['ask'][pos]))
        scenes.append(dict(symbol=symbol,session=session,raw=ref(raw),uncompressed_sha256=original[(symbol,session)],
                           q0=[target[k] for k in sorted(target)]))
    counts={s:sum(len(x['q0']) for x in scenes if x['symbol']==s) for s in ('NK225','TOPIX')}
    assert counts=={'NK225':40314,'TOPIX':35361}
    assert all(sum(x['symbol']==s for x in scenes)==83 for s in counts)
    sources=[ref(HERE/name) for name in ('特徴核.py','抽出201.py','人工確認.py','人工確認.json','仕様.md')]
    result=dict(trial=201,schema='純板201_v1',financial_labels_used=False,inputs=refs,Source=sources,
                columns=list(NAMES),q0_counts=counts,scenes=scenes,
                dependencies=dict(Python=sys.version,numpy=np.__version__,orjson=orjson.__version__))
    save(PLAN,result)
    print(json.dumps(dict(段階='抽出前固定',場商品=len(scenes),q0=counts,計byte=sum(r['raw']['bytes'] for r in scenes)),ensure_ascii=False),flush=True)
    return result


# ----------------------------------------
def extract(entry):
    """
    機能: 一原板を全行読み、当該q0以前の原行だけで純特徴を保存する。
    引数: entry(dict)は固定した原板とq0識別子。
    返り値: dictは特徴・品質の指紋。損益と先着を計算しない。
    """
    symbol,session=entry['symbol'],entry['session']
    path=Path(entry['raw']['path']);before=path.stat()
    assert (before.st_size,before.st_mtime_ns)==(entry['raw']['bytes'],entry['raw']['mtime_ns'])
    target={q['line']:q for q in entry['q0']}
    state=State(*edges(session));h=hashlib.sha256();counts=Counter();rows=[];cached={}
    started=time.perf_counter()
    with gzip.open(path,'rb') if path.suffix=='.gz' else path.open('rb') as stream:
        for line,raw in enumerate(stream,1):
            h.update(raw);r=orjson.loads(raw)
            text=r.get('CurrentPriceTime')
            if text not in cached:cached[text]=clock(text)
            buy=r.get('Buy1') or {};sell=r.get('Sell1') or {}
            q=dict(line=line,time=cached[text],contract=r.get('Symbol'),last=r.get('CurrentPrice'),
                   b=buy.get('Price'),a=sell.get('Price'),bq=buy.get('Qty'),aq=sell.get('Qty'))
            state.add(q);counts['原板物理行']+=1
            if state.reason:counts['入力状態:'+state.reason]+=1
            if line not in target:continue
            source=target[line]
            assert q['time']==source['time'] and q['last']==source['last'] and q['b']==source['bid'] and q['a']==source['ask'],(symbol,session,line,q,source)
            levels=tuple([( (r.get(side+str(i)) or {}).get('Price'),(r.get(side+str(i)) or {}).get('Qty')) for i in range(1,11)] for side in ('Buy','Sell'))
            features=state.snapshot(q,levels)
            for key,value in features.items():
                counts[key+(':既知' if value['known'] else ':未知:'+value['reason'])]+=1
            rows.append(dict(symbol=symbol,session=session,line=line,time=q['time'],last=q['last'],bid=q['b'],ask=q['a'],
                             contract=q['contract'],members=source['members'],features=features))
    assert h.hexdigest()==entry['uncompressed_sha256'],('展開原板SHA相違',symbol,session)
    after=path.stat();assert (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns)
    physical=ref(path);assert physical==entry['raw']
    assert len(rows)==len(target)
    dest=DEST/symbol/(session+'.json.gz')
    value=dict(schema='純板201_v1',symbol=symbol,session=session,financial_labels_used=False,rows=rows)
    output=save(dest,value)
    proof=dict(symbol=symbol,session=session,q0=len(rows),counts=dict(counts),raw=physical,
               uncompressed_sha256=h.hexdigest(),output=output,source_bound=True)
    save(DEST/symbol/(session+'.検査.json'),proof)
    print(json.dumps(dict(完了=symbol+'/'+session,q0=len(rows),原行=counts['原板物理行'],秒=round(time.perf_counter()-started,2)),ensure_ascii=False),flush=True)
    return proof


# ----------------------------------------
def run(workers,subset):
    """
    機能: 固定Sourceを確認して独立場を並列抽出する。
    引数: workers(int)は並列数、subset(str)は追加2又は全83。
    返り値: None。全83完了後だけ最終台帳を作る。
    """
    plan=read(PLAN)
    for item in plan['Source']:
        assert ref(Path(item['path']))['sha256']==item['sha256'],item['path']
    entries=[e for e in plan['scenes'] if subset=='全83' or e['session'] in ('2026-11-16_Night','2026-11-17_Day')]
    results=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(extract,e) for e in entries]
        for future in as_completed(futures):results.append(future.result())
    results.sort(key=lambda r:(r['symbol'],r['session']))
    result=dict(trial=201,schema='純板201_v1',success=True,financial_labels_used=False,input_plan=ref(PLAN),
                Source=plan['Source'],scope=subset,scenes=results)
    save(DEST/('完了.json' if subset=='全83' else '追加2の確認.json'),result)


# ----------------------------------------
if __name__=='__main__':
    parser=argparse.ArgumentParser(description='201の純板特徴専用。金融計算はしない。')
    parser.add_argument('--stage',choices=('prepare','extract'),required=True)
    parser.add_argument('--scope',choices=('追加2','全83'),default='追加2')
    parser.add_argument('--workers',type=int,default=2)
    args=parser.parse_args()
    if args.stage=='prepare':prepare()
    else:run(args.workers,args.scope)
