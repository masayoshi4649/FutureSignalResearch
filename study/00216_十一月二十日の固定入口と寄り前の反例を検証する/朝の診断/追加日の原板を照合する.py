"""11月20日デイの朝の価格、判別時に公表済みの日経の位置、建玉保有中の実側原行を照合する。"""
from argparse import ArgumentParser
from bisect import bisect_left
from datetime import datetime
from pathlib import Path
from statistics import correlation
import gzip
import hashlib
import json
import math
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(next((ROOT/'study').glob('00215_*'))/'朝の診断'))
import 原板で追加日を照合する as fixed

SCENE = '2026-11-20_Day'
START = datetime.fromisoformat(SCENE[:10]+'T08:45:00+09:00').timestamp()
fixed.SCENE, fixed.START, fixed.CLOSE = SCENE, START, START+405*60


# ----------------------------------------
def quotes(symbol: str) -> tuple:
    """
    機能：元の物理行順で価格時計と気配を読み、採用した原板の内容指紋を記録する。
    引数：symbol（str）は商品。
    返り値：tupleは価格時計付きの採用行と入力指紋。
    """
    folder = ROOT.parent/'JP_OSE_Data/future'/symbol/SCENE
    raw = next(p for p in (folder/'book.jsonl', folder/'book.jsonl.gz') if p.is_file())
    digest = hashlib.sha256()
    rows, previous = [], START
    with (gzip.open(raw,'rb') if raw.suffix=='.gz' else raw.open('rb')) as stream:
        for line, data in enumerate(stream,1):
            digest.update(data)
            r = json.loads(data)
            stamp = r.get('CurrentPriceTime')
            if not stamp:
                continue
            t = datetime.fromisoformat(stamp).timestamp()
            if previous <= t <= START+420*60 and (r.get('CurrentPrice') or 0)>0:
                rows.append(fixed.Quote(t,line,r['Buy1']['Price'],r['Sell1']['Price']))
                previous = t
    return rows, {'入力':raw.name,'内容SHA256':digest.hexdigest(),'物理行':line,'採用行':len(rows),
                  '正常気配':sum(q.normal for q in rows)}


# ----------------------------------------
def position(trades: list) -> list:
    """
    機能：寄り前のTOPIX短期回復入口だけについて、日経の厳密な過去90秒の取得位置を照合する。
    引数：trades（list）はTOPIXの固定台帳。
    返り値：listは条件に該当した建玉と当時の日経の分類。該当なしは空列。
    """
    early = [t for t in trades if t['added'] and t['entry_time'] < START+900]
    if not early:
        return []
    with gzip.open(ROOT/'work/216日経/母集団/当時特徴.json.gz','rb') as stream:
        features = json.load(stream)
    column = [r['name'] for r in features['catalog']].index('q0_entry_minus_ema8_atr5_to_side')
    day = [r for r in features['rows'] if r['session']==SCENE]
    clocks = [r['metadata']['q0']['time'] for r in day]
    assert clocks and clocks==sorted(clocks)
    result = []
    for trade in early:
        t = trade['request_time']
        i = bisect_left(clocks,t)-1
        known = i>=0 and t-clocks[i]<=90
        side = 'buy' if trade['side']==0 else 'sell'
        pos = day[i][side]['x'][column] if known else None
        if pos is not None and not math.isfinite(pos):
            pos = None
        if not known:
            category = '直前90秒に判断なし'
        elif pos is None:
            category = '位置算出不能'
        elif pos>1.5:
            category = '注文方向へ1.5ATR超'
        elif pos < -2:
            category = '注文方向と反対へ2ATR超'
        else:
            category = '範囲内'
        result.append({'注文側':side,'注文時計':fixed.clock(t),'日経の直前判断':fixed.clock(clocks[i]) if known else None,
                       '方向付き価格位置ATR':pos,'分類':category,'費用後円':trade['net']})
    return result


# ----------------------------------------
def paths(symbol: str, raw: list, trades: list) -> list:
    """
    機能：旧独立走査で決済を確認し、正常な返済側気配で保有中の有利・不利な最大変動を測る。
    引数：symbol（str）、raw（list）は採用原行、trades（list）は自指数の固定建玉。
    返り値：listは約定検査・最大順行逆行・費用控除後の最高値の明細。
    """
    checked = fixed.check_trades(symbol,raw,trades)
    multiple,cost = (100,1077) if symbol=='NK225' else (1000,583.6)
    for t,d in zip(trades,checked,strict=True):
        sign = 1 if t['side']==0 else -1
        # 決済不明の場合も、確定して観測できた範囲だけを数える。
        stop = t['exit_index']+1 if t['exit_time'] is not None else bisect_left(
            [q.time for q in raw], t['confirmed_until']+1)
        live = [q for q in raw[t['entry_index']:stop] if q.normal]
        points = [sign*((q.bid if sign==1 else q.ask)-t['entry_price']) for q in live]
        best = max(points)
        worst = min(points)
        assert -min(worst,0)==d['観測中の最大逆行ポイント']
        d.update(建値=t['entry_price'],決済時計=fixed.clock(t['exit_time']) if t['exit_time'] else None,
                 決済価格=t['exit_price'],最大順行ポイント=max(0,best),
                 最高値幅の初回時刻=fixed.clock(live[points.index(best)].time),
                 最高費用後評価円=round(multiple*best-cost,2))
    return checked


# ----------------------------------------
def main() -> None:
    """
    機能：追加日の価格と、任意で売買判断・各建玉の実側BBOを検算する。
    引数：なし。コマンドラインの --取引 で両口座の生成済み結果を読む。
    返り値：None。日本語の機械可読記録を出力する。
    """
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--取引',action='store_true')
    args = parser.parse_args()
    raw, parts = {}, {}
    market = {'対象':SCENE,'原板':{},'同期5分':{}}
    for s in fixed.SYMBOLS:
        raw[s],market['原板'][s] = quotes(s)
        market[s],parts[s] = fixed.measurements(raw[s])
    for name, lo, hi in (('08:45から15:30',0,81),('現物寄り前',0,3),('09:00から09:30',3,9)):
        pairs = [(a['bp'],b['bp']) for a,b in zip(parts['NK225'][lo:hi],parts['TOPIX'][lo:hi],strict=True) if a and b]
        measurable = len(pairs)>1 and all(len(set(column))>1 for column in zip(*pairs))
        market['同期5分'][name] = {'予定窓':hi-lo,'正常窓':len(pairs),'同時相関':correlation(*zip(*pairs)) if measurable else None}
    (HERE/'価格.json').write_text(json.dumps(market,ensure_ascii=False,allow_nan=False,indent=2)+'\n',encoding='utf8')
    if not args.取引:
        return
    # ----------------------------------------
    ts = {'NK225':json.loads((HERE.parent/'日経/固定結果.json').read_bytes())['結果']['建玉'],
          'TOPIX':json.loads((HERE.parent/'TOPIX/固定照合.json').read_bytes())['追加']['取得']}
    check = {'寄り前取得':{},'寄り前TOPIX短期回復入口の日経価格位置':position(ts['TOPIX']),'全取引の原板照合':{}}
    for s in fixed.SYMBOLS:
        check['全取引の原板照合'][s] = paths(s,raw[s],ts[s])
        check['寄り前取得'][s] = [{'側':'買' if t['side']==0 else '売','取得時計':fixed.clock(t['entry_time']),
                               'LC':t['added'],'費用後円':t['net']} for t in ts[s] if t['entry_time']<START+900]
    (HERE/'建玉の照合.json').write_text(json.dumps(check,ensure_ascii=False,allow_nan=False,indent=2)+'\n',encoding='utf8')


if __name__=='__main__':
    main()
