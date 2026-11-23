"""203の転換入口を同じq0の反対BBOで診断し、単純な1-pと区別する。"""
from pathlib import Path
from collections import defaultdict
from copy import deepcopy
import sys,json,math
import numpy as np
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).parent
sys.path.insert(0,str(ROOT/'work/203TOPIX'))
import 入口203 as E
import 金融203 as F203
sys.path.insert(0,str(ROOT/'work/183損失安定性'))
import TOPIXを独立検算する as T
sys.path.insert(0,str(ROOT/'work/202TOPIX'))
from 原因202 import describe
M=E.M;F=F203.F;A=F.A
INDICES=(8,9,20,21)


def append_checked(pack,cell,row,ci,oracle,counts):
    """
    機能: 反対側取得を台帳へ追加し、独立したBBO線形走査と全金融属性を照合する。
    引数: pack/cell/row(dict),ci(int),oracle(dict),counts(dict)。
    返り値: None。既存の金融正本は変更しない。
    """
    F.append(pack,dict(cell,origin=f'203_I{ci:02d}_同時点の反対側診断'))
    i=len(pack['ledger']['net'])-1
    for field,value in oracle.items():
        actual=pack['positions'][i][field] if field=='confirmed_until' else pack['ledger'][field][i]
        counts['金融属性']+=T.V.check_equal(actual,value,(pack['id'],row['session'],i,field))
    counts['取得']+=1


def describe_groups(pack,pure,maps,ci):
    """
    機能: 固定転換源の当時長期支持と新中期の支持を群別に診断する。
    引数: pack(dict),pure/maps(dict),ci(int)。
    返り値: dictは損益・到達・未知・支持数の群別一覧。
    """
    ledger=pack['ledger'];groups=defaultdict(list)
    form=0 if ci<16 else 1
    for i,scene in enumerate(ledger['scene']):
        if 'Night' not in scene:continue
        key=(scene,ledger['request_time'][i],ledger['request_line'][i]);row=maps[form][key];birth=pure[key]['births'][ci]
        old=birth['old_direction'];new=-old
        names=['全体','帯/'+row['band'],'決済/'+ledger['reason'][i]]
        names.append('旧30方向支持' if E.direction30(row)==old else '旧30方向不一致')
        names.append('価格が旧30EMA21側' if old*(row['close']-row['m30']['ema21'])>0 else '価格が旧30EMA21側でない')
        names.append('新15DI傾き支持' if row['m15']['slope'] is not None and new*row['m15']['di']>0 and new*row['m15']['slope']>0 else '新15DI傾き非支持')
        for name in names:groups[name].append(i)
    return {name:describe(ledger,indices) for name,indices in groups.items()}


def main():
    """
    機能: 同じ実取得q0の反対側独立診断と、全純出生の反転単一枠口座を分けて再生する。
    引数: なし。
    返り値: None。条件採用ではなく既使用81場の事後原因診断を別フォルダへ保存する。
    """
    original={p.name:M.sha(p) for p in E.HERE.glob('*') if p.is_file()}
    pure_list=E.read(E.HERE/'純入口.json.gz');pure={(r['session'],r['time'],r['line']):r for r in pure_list}
    by=defaultdict(list)
    for row in pure_list:by[row['session']].append(row)
    maps={form:{(r['session'],r['time'],r['line']):r for r in E.read(ROOT/'inputs/TOPIX原順8列_20260921_20261116'/name)} for form,name in enumerate(('純特徴183.json.gz','純特徴184直接.json.gz'))}
    states=E.read(E.HERE/'全28組安定性.json.gz')['metrics'];old={ci:E.read(E.HERE/'金融正本'/(states[ci]['id']+'.json.gz')) for ci in INDICES}
    entries=deepcopy(E.read(M.HERE/'入力台帳.json')['entries']);rawmap={r['session']:r for r in E.read(ROOT/'inputs/TOPIX原順8列_20260921_20261116/台帳.json')['entries']}
    for entry in entries:entry['cache_absolute']=str(ROOT/rawmap[entry['session']]['path'])
    meta=F.sessions(entries);packs={};acquired={}
    for ci in INDICES:
        for mode in ('同取得q0独立','全出生単一枠'):
            pack=F.empty(f'203原因_I{ci:02d}_{mode}_反対BBO',meta);pack['ledger']['origin']=[];packs[(ci,mode)]=pack
        ledger=old[ci]['ledger'];acquired[ci]={(scene,ledger['request_time'][i],ledger['request_line'][i]) for i,scene in enumerate(ledger['scene']) if 'Night' in scene}
    M.save(HERE/'診断開始前固定.json',{'区分':'203の事後原因診断。205の新入口比較や採用ではない。','対象':list(INDICES),'反転':'同じ固定q0・幅・H60の反対BBO。単一枠は全出生を再生。独立取引の合算を口座としない。','SourceSHA':M.sha(Path(__file__)),'203読取SHA':original})
    counts={'取得':0,'金融属性':0,'独立集計属性':0};cache_count=0
    for entry in entries:
        scene=entry['session']
        if 'Night' not in scene:continue
        route=M.Route(entry);start,end,force=T.bounds(scene)
        with np.load(entry['cache_absolute'],allow_pickle=False) as archive:raw={k:archive[k] for k in ('now','line','bid','ask','valid')}
        t=raw['now'];finite=np.isfinite(t);prior=np.maximum.accumulate(np.where(finite,t,-np.inf));mask=finite&(t>=start)&(t<end)&(t>=prior)&raw['valid'];arrays={k:v[mask] for k,v in raw.items() if k!='valid'}
        cells={};oracles={}
        for ci in INDICES:
            for mode in ('同取得q0独立','全出生単一枠'):
                pack=packs[(ci,mode)];busy=-math.inf;diag={'純成立':0,'保有棄却':0,'失効':0,'取得':0}
                for row in by[scene]:
                    if not row['signals'][ci]:continue
                    key=(scene,row['time'],row['line'])
                    if mode=='同取得q0独立' and key not in acquired[ci]:continue
                    diag['純成立']+=1
                    if mode=='全出生単一枠' and row['time']<=busy:diag['保有棄却']+=1;continue
                    side=-row['signals'][ci];width=row['widths'][ci];query=(row['time'],row['line'],side,width)
                    if query not in cells:
                        cells[query]=route.cell(*query);first=int(np.searchsorted(arrays['now'],row['time']+1));fillable=first<len(arrays['now']) and arrays['now'][first]<=min(row['time']+30,force) and arrays['now'][first]<force
                        oracles[query]=T.financial_oracle(arrays,scene,row['time'],side,width) if fillable else None
                        assert (cells[query] is None)==(oracles[query] is None)
                    cell=cells[query]
                    if cell is None:diag['失効']+=1;busy=min(row['time']+30,force);continue
                    append_checked(pack,cell,row,ci,oracles[query],counts);diag['取得']+=1;busy=end if cell['unknown'] else cell['exit_time']
                pack['diagnostics'].append({'scene':scene,**diag})
        cache_count+=len(cells);print(scene,len(cells),flush=True)
    periods={'全80':[r['scene'] for r in meta[:80]],'前48':[r['scene'] for r in meta[:48]],'後25':[r['scene'] for r in meta[48:73]],'追加7':[r['scene'] for r in meta[73:80]],'本日1':[meta[-1]['scene']]};report=[]
    for ci in INDICES:
        row={'index':ci,'旧固定':describe_groups(old[ci],pure,maps,ci)}
        for mode in ('同取得q0独立','全出生単一枠'):
            pack=packs[(ci,mode)];M.save(HERE/'診断台帳'/(pack['id']+'.json.gz'),pack);item={'群':describe_groups(pack,pure,maps,ci)}
            if mode=='全出生単一枠':
                stat=A.evaluate_pack(pack,periods);counts['独立集計属性']+=T.inspect_groups(pack,stat);item['口座']=stat
            row[mode]=item
        report.append(row)
    assert all(M.sha(E.HERE/name)==sha for name,sha in original.items())
    M.save(HERE/'反対BBO診断.json',{'区分':'既使用81場の事後診断。独立反転は同取得q0、口座反転は全純出生と未知保有を再生。どちらも採用候補へ置換しない。','結果':report,'独立確認':counts,'別照合セル':cache_count,'203不変':True})
    for row in report:print(json.dumps({'index':row['index'],'旧固定':row['旧固定']['全体'],'同取得q0反対':row['同取得q0独立']['群']['全体'],'全出生反対':row['全出生単一枠']['群']['全体']},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
