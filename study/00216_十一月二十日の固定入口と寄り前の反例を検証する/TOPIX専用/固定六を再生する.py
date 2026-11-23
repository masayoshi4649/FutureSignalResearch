"""212の06だけを継承し、旧対照8場と11月17日夜以降の7場を純入口から再生する。"""
from concurrent.futures import ProcessPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path
import sys
from 履歴を形成する import HERE, ROOT, WORK, DATES, NAMES, old, raw_path

sys.path[:0] = list(map(str,(ROOT/'work/192TOPIX',ROOT/'work/209固定参照',ROOT/'work/210TOPIX',
                            ROOT/'work/212帯別固定入口',ROOT/'scripts/VWAP純入力204',ROOT/'scripts/TOPIX入口研究')))
import 入口192 as rule
import 入口209 as reversal
import 入口210 as day_rule
import 入口212 as combined
import 抽出204 as native
import 共通金融 as account
sys.path.insert(0,str(ROOT / 'work/212独立確認'))
import 線形核を読む as verifier

ID = 'TOPIX212_'+combined.NAMES[6]
# 旧83場で独立した価格試行が採用された全6場と、最終の2場。
OLD_F = tuple('2026-'+d+'_Night' for d in ('10-08','10-09','10-20','10-30','11-05','11-06'))
CHECK = (*OLD_F,'2026-11-16_Night','2026-11-17_Day')


# ----------------------------------------
def snapshots(task: tuple) -> dict:
    """
    機能：原板の全行で204の累積状態を更新し、q0の正確な物理行で配信VWAPを記録する。
    引数：task（tuple）はセッションとその直接形成のq0行。
    返り値：dictはq0時刻・行番号をキーとするnative参照値。
    """
    scene, rows = task
    path = raw_path(scene)
    state = native.State(scene,'TOPIX')
    keys = {r['line']:r for r in rows}
    times, result = {}, {}
    digest = hashlib.sha256()
    with (gzip.open(path,'rb') if path.suffix=='.gz' else path.open('rb')) as stream:
        for line, data in enumerate(stream,1):
            digest.update(data)
            raw = native.orjson.loads(data)
            event = native.parse(raw,line,times)
            state.add(event)
            if line in keys:
                row = keys[line]
                assert row['time']==event['time'] and event['last'] is not None
                result[reversal.E.key(row)] = state.snapshot()
    assert len(result)==len(keys)
    if scene in DATES:
        assert digest.hexdigest()==old.I.read(WORK/'原順8列'/(scene+'.json'))['sha256_uncompressed']
    return result


# ----------------------------------------
def create() -> tuple:
    """
    機能：旧190の当時条件、デイ長期矛盾見送り、ナイトのnative戻り失敗を既存関数で接続する。
    引数：なし。固定済みの純特徴と新規7場の形成結果を読む。
    返り値：tupleは一候補の純入口と、固定旧対照における照合件数。
    """
    features=[]
    for name in NAMES:
        old_features=old.I.read(ROOT/'inputs/TOPIX原順8列_20260921_20261116'/name)
        part=[r for r in old_features if r['session'] in OLD_F]
        features.append(part+old.I.read(WORK/name))
    formation=[old.per_form(part,rule) for part in features]
    available=sorted(set(formation[0])|set(formation[1]))
    calendar = (*CHECK,*DATES)
    tasks=[(name,[r for r in features[1] if r['session']==name]) for name in calendar]
    natives={}
    with ProcessPoolExecutor(max_workers=4) as workers:
        for result in workers.map(snapshots,tasks):
            natives.update(result)
    births,_=reversal.generate(features[1],natives)
    pure=[]
    for key in available:
        initial=formation[0].get(key)
        direct=formation[1].get(key)
        row=(direct or initial)['row']
        side,width,_=old.control(initial,direct)
        if row['band']=='DAY':
            if side and day_rule.roles(direct['row'],side)['A']:
                side=0
            origin,parent='旧190D4固定','D1'
        else:
            born=births.get(key,[None]*4)
            f,_,_=reversal.E.choose(born[:3],0,2)
            side,parent=combined.night(side,side,f,2)
            origin='旧共通1分量_源で即時_品質制限なし' if parent=='旧' else reversal.NAMES[28]
            width=15.
        pure.append({'session':key[0],'time':key[1],'line':key[2],'band':row['band'],
                     'signals':[side],'widths':[width],'origins':[origin],'parent_branch':[parent]})
    # ----------------------------------------
    frozen=combined.read(combined.PURE/'純入口.json.gz')
    expected=[{**{k:r[k] for k in ('session','time','line','band')},**{k:[r[k][6]] for k in
                ('signals','widths','origins','parent_branch')}} for r in frozen if r['session'] in CHECK]
    observed=[r for r in pure if r['session'] in CHECK]
    assert len(observed)==len(expected)
    for a,b in zip(observed,expected,strict=True):
        assert a==b,(a,b)
    supported=sum(r['signals'][0]!=0 and r['parent_branch'][0]=='F' for r in observed)
    assert supported==6
    return pure,{'旧照合場':CHECK,'旧全判断一致':len(observed),'旧新枝出生一致':supported}


# ----------------------------------------
def main() -> None:
    """
    機能：純入口の一致後に、旧8場の全金融列および予約・監査を比較し、追加7場を保存する。
    引数：なし。
    返り値：None。恒久的な固定金融パックと入力・照合の記録を作る。
    """
    pure,checks=create()
    old_resources=[e for e in old.entries() if e['session'] in CHECK]
    resources=[old.I.read(WORK/'原順8列'/(day+'.json')) for day in DATES]
    previous=next((ROOT/'study').glob('00212_*/金融正本/'+ID+'.json.gz'))
    historic=account.read(previous)
    clean,=account.replay([r for r in pure if r['session'] in CHECK],[ID],old_resources)
    for key, field in [('positions','scene'),('sessions','scene'),('diagnostics','scene')]:
        assert clean[key]==[row for row in historic[key] if row[field] in CHECK],key
    keep=[i for i,scene in enumerate(historic['ledger']['scene']) if scene in CHECK]
    for key,vec in historic['ledger'].items():
        assert clean['ledger'][key]==[vec[i] for i in keep],key
    # ----------------------------------------
    current=[r for r in pure if r['session'] in DATES]
    pack,=account.replay(current,[ID],resources)
    old.I.save(HERE/'追加七場.json.gz',pack)
    independent(current,resources,pack)
    old.I.save(HERE/'固定照合.json',{**checks,'旧全建玉一致':len(keep),'旧正本':old.I.ref(previous),
        '追加七場の判断':len(current),'追加判別':{s:{'判断':sum(r['session']==s for r in current),
        '旧成立':sum(r['signals'][0]!=0 and r['parent_branch'][0]!='F' for r in current if r['session']==s),
        '独立F成立':sum(r['signals'][0]!=0 and r['parent_branch'][0]=='F' for r in current if r['session']==s)} for s in DATES},
        '入力':[{k:e[k] for k in ('session','raw_lines','events','sha256_uncompressed','sha256_cache')} for e in resources],
        '純特徴確認':[{k:v for k,v in p.items() if k!='入力'} for p in old.I.read(WORK/'形成検査.json')['形成']],
        '実装':{str(p.relative_to(ROOT)):old.M.sha(p) for p in [Path(m.__file__) for m in
                (old,old.M,old.D,rule,reversal,reversal.E,day_rule,combined,native,account,account.F)]}})
    print('旧照合',len(keep),'追加取得',len(pack['positions']),flush=True)


# ----------------------------------------
def independent(current: list, resources: list, pack: dict) -> None:
    """
    機能：独立した線形走査で追加7場の全成立から再注文し、取得・枠監査と損益・保有秒を検算する。
    引数：current（list）は純入口、resources（list）は原順8列、pack（dict）は金融正本。
    返り値：None。照合件数を独立検算に保存する。
    """
    kernel=verifier.load()
    ledger=pack['ledger']
    count=0
    for resource, audit in zip(resources,pack['diagnostics'],strict=True):
        scene=resource['session']
        price=kernel.load_arrays(resource)
        hold=-float('inf')
        pending=False
        checks={'scene':scene,'純成立':0,'保有棄却':0,'予約棄却':0,'取得':0,'失効':0}
        for order in current:
            if order['session']!=scene or not order['signals'][0]:
                continue
            side=order['signals'][0]
            checks['純成立']+=1
            if order['time']<=hold:
                checks['予約棄却' if pending else '保有棄却']+=1
                continue
            cell=kernel.oracle(price,order['time'],order['line'],side,order['widths'][0],'H60')
            if cell is None:
                hold,pending=min(order['time']+30,price['force']),True
                checks['失効']+=1
                continue
            checks['取得']+=1
            for name in ('entry_line','entry_time','entry_price','exit_line','exit_time','exit_price','label','side',
                         'request_time','request_line','width','gross_pt','unknown_reason','reason'):
                assert ledger[name][count]==cell[name],(scene,count,name)
            net=None if cell['unknown'] else round(side*(cell['exit_price']-cell['entry_price'])*1000-583.6,1)
            assert pack['positions'][count]['confirmed_until']==cell['known_until']
            assert ledger['net'][count]==net and ledger['known'][count]==(net is not None)
            assert ledger['scene'][count]==scene and ledger['origin'][count]==order['origins'][0]
            hold=price['end'] if cell['unknown'] else cell['exit_time']
            pending=False
            count+=1
        assert checks==audit,(scene,checks,audit)
    assert count==len(ledger['scene'])
    old.I.save(HERE/'独立検算.json',{'場数':len(resources),'全純成立':sum(d['純成立'] for d in pack['diagnostics']),
             '取得':count,'未知':ledger['known'].count(False),'完了':True,'検算元':kernel.proof})


if __name__=='__main__':
    main()
