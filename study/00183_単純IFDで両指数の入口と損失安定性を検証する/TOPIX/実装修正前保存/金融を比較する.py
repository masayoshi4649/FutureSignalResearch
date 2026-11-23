"""金融前固定されたTOPIX純入口を、固定幅ごとに単一建玉で再生する。"""
from pathlib import Path
from copy import deepcopy
from datetime import datetime,timedelta
import gzip,hashlib,json,sys
import numpy as np
import 入口とIFD as M

sys.path.insert(0,str(M.ROOT/'work/183損失安定性'))
import 安定性183 as A


def sessions(entries):
    """
    機能: 全場と三帯の保有率分母を作る。
    引数: entries(list[dict])は入力場。
    返り値: list[dict]は全場。0取得も除外しない。
    """
    result=[]
    for e in entries:
        scene=e['session'];start,end,_=M.bounds(scene);kind='DAY' if scene.endswith('Day') else 'NIGHT'
        if kind=='DAY':phases=[{'name':'DAY','start':start,'end':end}]
        else:
            ny=datetime.fromtimestamp(start,M.NY);op=datetime.combine(ny.date(),datetime.min.time(),M.NY)+timedelta(hours=9,minutes=30)
            phases=[{'name':'PRE','start':start,'end':op.timestamp()},{'name':'POST','start':op.timestamp(),'end':end}]
        result.append({'scene':scene,'kind':kind,'start':start,'end':end,'phases':phases})
    return result


def empty(identifier,meta):
    """
    機能: 型付き単一建玉台帳を初期化する。
    引数: identifier(str),meta(list[dict])は全場。
    返り値: dictは空pack。
    """
    return {'id':identifier,'product':'ミニTOPIX1枚換算','sessions':meta,'positions':[],
      'ledger':{k:[] for k in ('net','known','scene','phase','entry_time','exit_time','entry_price','exit_price','side','gross_pt','width','label','reason','unknown_reason','request_time','request_line','entry_line','exit_line')},
      'diagnostics':[]}


def append(pack,cell,slip=.25):
    """
    機能: 一取得を同時保有なしの台帳へ追加する。
    引数: pack(dict),cell(dict),slip(float)は片道追加費用pt。
    返り値: None。
    """
    unknown=cell['unknown'];end=M.bounds(cell['session'])[1]
    net=None if unknown else round(cell['gross_pt']*1000-83.6-2*slip*1000,1)
    values={'net':net,'known':not unknown,'scene':cell['session'],'phase':{'DAY':0,'PRE':1,'POST':2}[cell['band']]}
    for k in pack['ledger']:
        pack['ledger'][k].append(values[k] if k in values else cell[k])
    pack['positions'].append({'scene':cell['session'],'fill':cell['entry_time'],'exit':cell['exit_time'],
        'confirmed_until':cell['known_until'],'possible_until':end if unknown else cell['exit_time']})


def terse(group):
    """
    機能: 主要な安定性の値を短表へ写す。
    引数: group(dict)は共通集計。
    返り値: dictは短い表示値。
    """
    t,s,h,p=group['trades'],group['sessions'],group['holding'],group['path']['known_contribution']
    return {'取得':t['all_count'],'未知':t['unknown_count'],'利益':t['known_profit'],'損失':t['known_loss'],'既知収支':t['known_net'],
       '赤字場率上限':s['negative_rate']['upper'],'赤字取引率上限':t['negative_rate']['upper'],
       '参加場':s['participating_count'],'全場':s['eligible_count'],'保有下限':h['held_lower_ratio'],
       '建玉中央値下限':t['net_median']['lower'],'場中央値下限':s['net_median']['lower'],'両中央値':group['both_medians_positive'],
       '最悪場':p['worst_scene_net'],'場末DD既知寄与':p['max_drawdown']['amount'],'連続赤字場上限':s['negative_streak']['upper']}


def main():
    """
    機能: 13入口×3幅を再生し、事前順位・費用感度を保存する。
    引数: なし。
    返り値: None。旧資料を変更しない。
    """
    cfg=M.read(M.HERE/'条件.json');assert cfg['SourceSHA']==M.sha(M.HERE/'入口とIFD.py')
    assert cfg['純特徴SHA']==M.sha(M.HERE/'純特徴.json.gz')
    source={'金融runner':M.sha(Path(__file__)),'安定性':M.sha(M.ROOT/'work/183損失安定性/安定性183.py'),'条件':M.sha(M.HERE/'条件.json')}
    marker=M.HERE/'金融開始前固定.json';assert not marker.exists();M.save(marker,source)
    entries=M.read(M.HERE/'入力台帳.json')['entries'];meta=sessions(entries)
    pure=json.loads(gzip.decompress((M.HERE/'純特徴.json.gz').read_bytes()));scene_rows={s['scene']:[] for s in meta}
    for row in pure:scene_rows[row['session']].append(row)
    ids={(i,w):f'TOPIX183_{name}_W{w:g}_H60' for i,name in enumerate(M.NAMES) for w in M.WIDTHS}
    packs={k:empty(v,meta) for k,v in ids.items()}
    for e in entries:
        route=M.Route(e);rows=scene_rows[e['session']];cache={}
        for (ci,w),pack in packs.items():
            busy=-float('inf');accepted=blocked=expired=signals=0
            for r in rows:
                side=r['signals'][ci]
                if not side:continue
                signals+=1
                if r['time']<=busy:blocked+=1;continue
                key=(r['time'],r['line'],side,w)
                if key not in cache:cache[key]=route.cell(*key)
                cell=cache[key]
                if cell is None:expired+=1;continue
                accepted+=1;append(pack,cell);busy=route.end if cell['unknown'] else cell['exit_time']
            pack['diagnostics'].append({'scene':e['session'],'純成立':signals,'保有棄却':blocked,'取得':accepted,'失効':expired})
        print(e['session'],len(rows),len(cache),flush=True)
    periods={'全80':[s['scene'] for s in meta[:-1]],'前48':[s['scene'] for s in meta[:48]],'後25':[s['scene'] for s in meta[48:73]],
      '追加7':[s['scene'] for s in meta[73:80]],'本日1':[meta[-1]['scene']]}
    all_metrics={};compact=[];rankings={}
    for (ci,w),pack in packs.items():
        stat=A.evaluate_pack(pack,periods);all_metrics[(ci,w)]=stat
        M.save(M.HERE/'金融正本'/(pack['id']+'.json.gz'),pack)
        compact.append({'id':pack['id'],'candidate':M.NAMES[ci],'width':w,'全81':{k:terse(v) for k,v in stat['groups'].items()},
           '期間':{p:{k:terse(v) for k,v in b.items()} for p,b in stat['periods'].items()}})
    for w in M.WIDTHS:
        for period in ('全80','前48'):
            for b in ('DAY','NIGHT'):
                base=all_metrics[(0,w)]['periods'][period][b]
                order=sorted(range(len(M.NAMES)),key=lambda ci:(A.rank_key(all_metrics[(ci,w)]['periods'][period][b],base),ids[(ci,w)]))
                rankings[f'W{w:g}_{period}_{b}']=[{'id':ids[(ci,w)],'gate':A.gate(all_metrics[(ci,w)]['periods'][period][b],base)} for ci in order]
    M.save(M.HERE/'全39組安定性.json.gz',{'metrics':list(all_metrics.values()),'順位':rankings})
    M.save(M.HERE/'全39組短表.json',{'rows':compact,'順位':rankings,'費用':'片道41.8円+0.25pt、miniTOPIX1pt1000円'})
    sensitivity=[]
    for slip in (0.,.5):
        for (ci,w),original in packs.items():
            pack=deepcopy(original)
            pack['ledger']['net']=[None if g is None else round(g*1000-83.6-2*slip*1000,1) for g in pack['ledger']['gross_pt']]
            stat=A.evaluate_pack(pack)
            sensitivity.append({'id':pack['id'],'片道滑りpt':slip,'全81':{b:terse(g) for b,g in stat['groups'].items()}})
    M.save(M.HERE/'費用感度.json',sensitivity)
    for name,ranking in rankings.items():
        first=ranking[0];row=next(r for r in compact if r['id']==first['id'])
        print(name,json.dumps({'id':first['id'],'gate':first['gate'],'全81':row['全81'][name.split('_')[-1]]},ensure_ascii=False),flush=True)
    assert cfg['SourceSHA']==M.sha(M.HERE/'入口とIFD.py')


if __name__=='__main__':main()
