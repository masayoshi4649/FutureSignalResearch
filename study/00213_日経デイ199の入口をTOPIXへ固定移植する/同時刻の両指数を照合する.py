"""各指数で成立した時刻・方向・幅・期限を両指数へ同時に照会する事後の経路診断。"""
from collections import defaultdict
from pathlib import Path
import gzip
import json
import statistics

from 金融再生 import ROOT, HERE, read, load_scene, closing, settle


# ----------------------------------------
def ledgers() -> tuple:
    """
    機能：日経199_02と呼値換算TOPIXの取得を、同じ42デイに限定して復元する。
    引数：なし。
    返り値：tupleは指数別の取得一覧と原板台帳のパス。
    """
    old = next((ROOT/'study').glob('00199_*'))
    topo = read(next((HERE/'金融正本').glob('*03*.gz')))['取得']
    nikkei = []
    for folder in (old/'保存金融', old/'追加二場/保存金融'):
        ledger = read(next(folder.glob('*02__C0_IFD.json.gz')))['ledger']
        nikkei.extend({k:v[i] for k,v in ledger.items()} for i,scene in enumerate(ledger['scene']) if scene.endswith('_Day'))
    books = {'NK225': [next((ROOT/'inputs').glob(pattern)) for pattern in
             ['00163*/価格索引/manifest.json','00167*/原板数値索引/manifest.json',
              '00180*/原板数値索引/manifest.json','00194*/NK225/原板数値索引/manifest.json']],
             'TOPIX':[ROOT/'work/今回移植/原行索引/manifest.json']}
    return {'NK225':nikkei, 'TOPIX':[t for t in topo if t['scene'] <= '2026-11-17_Day']}, books


# ----------------------------------------
def summarize(pairs: list) -> dict:
    """
    機能：両側の損益が確定した同じ通知集合について、設定幅を1とする平均と先着数を求める。
    引数：pairs（list）は同一意思決定から両指数を測った観測。
    返り値：dictは母数・欠測・各指数の標準化損益、黒字日数、先着分布。
    """
    complete = [p for p in pairs if all(p[s] is not None and p[s]['net'] is not None for s in ('NK225','TOPIX'))]
    out = {'通知':len(pairs),'両側確定':len(complete),'いずれか取得不可':sum(any(p[s] is None for s in ('NK225','TOPIX')) for p in pairs)}
    for symbol, multiplier in [('NK225',100),('TOPIX',1000)]:
        legs = [p[symbol] for p in complete]
        values = [t['gross']/(multiplier*t['width']) for t in legs]
        net = [t['net']/(multiplier*t['width']) for t in legs]
        out[symbol] = {'平均費用前幅比':statistics.mean(values), '平均費用後幅比':statistics.mean(net),
                       '費用後正':sum(v>0 for v in net),'順':sum(t['label']==1 for t in legs),
                       '逆':sum(t['label']==-1 for t in legs),'未到達':sum(t['label']==0 for t in legs)}
    return out


# ----------------------------------------
def main() -> None:
    """
    機能：元取得の1秒後以降30秒未満に両指数を同じ方向で観測し、元期限・呼値数で決済する。
    引数：なし。単一枠で実現した旧取得集合を診断時点として用いる。
    返り値：None。各通知の両側原行と集計を保存する。重複保有の仮想損益は合算しない。
    """
    requests, books = ledgers()
    spec = {s['session']:s for s in read(ROOT/'work/今回移植/索引計画.json')['scenes']}
    manifests = {symbol:{item['session']:(fn.parent,item) for fn in files for item in read(fn)['scenes']}
                 for symbol,files in books.items()}
    pairs = defaultdict(list)
    stats = {}
    for scene in sorted({r['scene'] for r in requests['NK225']}):
        indices = {s:load_scene(*m[scene]) for s,m in manifests.items()}
        cut = spec[scene]['end']-900
        for origin, trades in requests.items():
            for t in (r for r in trades if r['scene']==scene):
                event = t['entry_time']
                nk_width = t['width'] * (20 if origin=='TOPIX' else 1)
                pair = {'場':scene,'通知':event,'側':t['side'],'日経表記幅':nk_width,'期限':t['horizon']}
                for symbol, index in indices.items():
                    entry = index.first_normal(event+1)
                    valid = entry >= 0 and index.times[entry] < min(event+30, cut-60)
                    width = nk_width if symbol=='NK225' else nk_width/20
                    pair[symbol] = settle(index,entry,t['side'],width,t['horizon'],cut,closing(index,cut),symbol) if valid else None
                pairs[origin].append(pair)
    for origin, group in pairs.items():
        stats[origin] = summarize(group)
    for name, data in [('同期照合の明細.json.gz',pairs),('同期照合の集計.json',stats)]:
        raw = (json.dumps(data,ensure_ascii=False,indent=None,allow_nan=False)+'\n').encode()
        (HERE/name).write_bytes(gzip.compress(raw,mtime=0) if name.endswith('.gz') else raw)


if __name__=='__main__':
    main()
