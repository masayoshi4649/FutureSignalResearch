"""201実取得の原行識別子だけを投影し、量の観測尺度を診断する。"""
from collections import Counter,defaultdict
from pathlib import Path
import gzip
import hashlib
import json
import math

ROOT=Path(__file__).resolve().parents[2]
BOARD=ROOT/'inputs/00201_両指数の板数量純特徴'
DEST=BOARD/'取得q0の観測尺度'
FINANCE=ROOT/'work/201板数量比較/金融正本'
FIELDS=('OFI16','OFI64','BLOCK4_OFI')
LEGS={'旧73':'inputs/00148_全1分入口母集団/当時特徴.json.gz',
      '追加7':'inputs/00167_追加七場の入口と共用価格索引/入口母集団/当時特徴.json.gz',
      '本日1':'inputs/00180_20261116デイの固定適用入力/入口母集団/当時特徴.json.gz',
      '追加2':'inputs/00194_20261116夜と1117昼の固定適用入力/NK225/入口母集団/当時特徴.json.gz'}
BANDS=('DAY','PRE','POST')


# ----------------------------------------
def read(path):
    """
    機能: 保存資源を読む。
    引数: path(Path)。
    返り値: objectはJSON値。
    """
    with gzip.open(path,'rt',encoding='utf-8') if path.suffix=='.gz' else path.open(encoding='utf-8') as f:return json.load(f)


# ----------------------------------------
def ref(path):
    """
    機能: 読取資源を相対パスと指紋で記録する。
    引数: path(Path)。
    返り値: dictはpath/bytes/sha256。
    """
    raw=path.read_bytes()
    return dict(path=path.relative_to(ROOT).as_posix(),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())


# ----------------------------------------
def save(path,value):
    """
    機能: 決定的診断資源を新規保存する。
    引数: path(Path)、value(object)。
    返り値: None。既存の異なる内容は上書きしない。
    """
    raw=(json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode()
    body=gzip.compress(raw,mtime=0) if path.suffix=='.gz' else raw
    if path.exists():assert path.read_bytes()==body,path
    else:path.write_bytes(body)


# ----------------------------------------
def project():
    """
    機能: 実取得台帳からq0原行・側・帯だけを投影し損益列を使わない。
    引数: なし。
    返り値: dictは全25候補の取得識別子。決済既知/未知でも取得を残す。
    """
    path=DEST/'取得識別子.json.gz'
    if path.exists():return read(path)
    nk={leg:read(ROOT/name)['rows'] for leg,name in LEGS.items()}
    inputs=[ref(ROOT/name) for name in LEGS.values()];rows=[]
    sources=sorted(FINANCE.glob('*.json.gz'));assert len(sources)==25
    for source in sources:
        pack=read(source);identity=pack['id'];symbol='NK225' if identity.startswith('NK225') else 'TOPIX'
        ledger=pack['ledger'];inputs.append(ref(source))
        for i,scene in enumerate(ledger['scene']):
            if symbol=='NK225':
                target=nk[ledger['leg'][i]][ledger['event'][i]]
                assert target['session']==scene
                q=target['metadata']['q0'];line=q['source_line'];at=q['time']
                assert ledger['side'][i] in (0,1)
                side=1 if ledger['side'][i]==0 else -1
            else:
                line=ledger['request_line'][i];at=ledger['request_time'][i];side=ledger['side'][i]
                assert side in (-1,1)
            assert line<=ledger['entry_line'][i] and at<=ledger['entry_time'][i]
            rows.append(dict(candidate=identity,symbol=symbol,session=scene,line=line,time=at,side=side,
                             band=BANDS[ledger['phase'][i]],origin=str(ledger['origin'][i]),
                             entry_line=ledger['entry_line'][i],entry_time=ledger['entry_time'][i]))
    value=dict(用途='実取得の原行識別子だけの事後診断',金融台帳を読取=True,損益列を使用=False,採否と閾値選択=False,
               Source=ref(Path(__file__)),inputs=inputs,rows=rows)
    save(path,value);return value


# ----------------------------------------
def distribution(values):
    """
    機能: 既定の時間尺度について経験分布をまとめる。
    引数: values(list[float])は既知のLast時計差。
    返り値: dictは分位・零件数・固定参考軸以内の件数。
    """
    if not values:return dict(count=0)
    x=sorted(values);assert all(math.isfinite(v) and v>=0 for v in x)
    n=len(x)
    return dict(count=n,zero=sum(v==0 for v in x),min=x[0],p25=x[int((n-1)*.25)],median=x[int((n-1)*.5)],
                p75=x[int((n-1)*.75)],p90=x[int((n-1)*.9)],p99=x[int((n-1)*.99)],max=x[-1],
                at_most={str(t):sum(v<=t for v in x) for t in (60,300,900,1800,3600,7200)},
                median_fraction_of={str(t):x[int((n-1)*.5)]/t for t in (300,900,1800,3600,7200)})


# ----------------------------------------
def summarize(rows,boards):
    """
    機能: 候補又は重複除去集合の尺度と実側に対する符号を集計する。
    引数: rows(list[dict])は識別子、boards(dict)は原行別純板値。
    返り値: dictは分布・既知/未知・実側反対件数。損益は引数にない。
    """
    answer=dict(q0=len(rows),scenes=len({r['session'] for r in rows}),features={},direction={},origin=dict(Counter(r['origin'] for r in rows)))
    for name in FIELDS:
        known=[];unknown=Counter();positive=negative=zero=ambiguous=0
        for row in rows:
            v=boards[(row['symbol'],row['session'],row['line'])]['features'][name]
            if not v['known']:unknown[v['reason']]+=1;continue
            known.append(v)
            if row['side']==0:ambiguous+=1;continue
            value=row['side']*v['value']
            positive+=value>0;negative+=value<0;zero+=value==0
        answer['features'][name]=dict(known=len(known),unknown=dict(unknown),
             clock_span=distribution([v['clock_span'] for v in known]),max_clock_gap=distribution([v['max_clock_gap'] for v in known]))
        answer['direction'][name]=dict(実側同方向=positive,実側反対=negative,零=zero,複数母体の実側不一致=ambiguous)
    return answer


# ----------------------------------------
def main():
    """
    機能: 実取得q0の観測尺度を候補別とBASE母体重複除去で保存する。
    引数: なし。
    返り値: None。新入口や損益最適化を行わない。
    """
    projected=project();rows=projected['rows']
    wanted={(r['symbol'],r['session'],r['line']) for r in rows};boards={};refs=[]
    for symbol in ('NK225','TOPIX'):
        for path in sorted((BOARD/symbol).glob('*.json.gz')):
            refs.append(ref(path))
            for q in read(path)['rows']:
                key=(symbol,q['session'],q['line'])
                if key in wanted:boards[key]=q
    assert set(boards)==wanted
    for r in rows:assert boards[(r['symbol'],r['session'],r['line'])]['time']==r['time']
    by_candidate={}
    for candidate in sorted({r['candidate'] for r in rows}):
        by_candidate[candidate]={band:summarize([r for r in rows if r['candidate']==candidate and r['band']==band],boards) for band in BANDS}
    base={};rawbase=[r for r in rows if r['candidate'].endswith('_BASE')]
    for r in rawbase:
        key=(r['symbol'],r['session'],r['line'])
        if key not in base:base[key]=dict(r,sides={r['side']},origins={r['origin']})
        else:
            assert base[key]['band']==r['band']
            base[key]['sides'].add(r['side']);base[key]['origins'].add(r['origin'])
    unique=[]
    for value in base.values():
        r=dict(value);sides=r.pop('sides');origins=r.pop('origins')
        r['side']=next(iter(sides)) if len(sides)==1 else 0;r['origin']='|'.join(sorted(origins));unique.append(r)
    aggregate={s:{b:summarize([r for r in unique if r['symbol']==s and r['band']==b],boards) for b in BANDS} for s in ('NK225','TOPIX')}
    result=dict(確認日='2026-11-18',事後診断=True,損益使用=False,新条件採用=False,尺度='Last時計差。実受信時間ではない',
                Source=ref(Path(__file__)),取得識別子=ref(DEST/'取得識別子.json.gz'),純板資源=refs,
                全25取得行=len(rows),BASE5取得行=len(rawbase),BASE重複除去q0=len(unique),BASE商品帯=aggregate,候補別=by_candidate)
    save(DEST/'観測尺度.json',result)
    print(json.dumps(dict(BASE商品帯=aggregate,全25取得行=len(rows),BASE5取得行=len(rawbase),BASE重複除去q0=len(unique)),ensure_ascii=False))


# ----------------------------------------
if __name__=='__main__':
    main()
