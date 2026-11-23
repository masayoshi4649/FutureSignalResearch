"""11月19日の朝の価格位置と、固定口座の取得・先着・損益を元の板で照合する。"""
from argparse import ArgumentParser
from bisect import bisect_left
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import correlation
from typing import NamedTuple
import gzip
import hashlib
import json
import math

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SCENE = '2026-11-19_Day'
SYMBOLS = ('NK225', 'TOPIX')
JST = timezone(timedelta(hours=9))
START = datetime(2026, 11, 19, 8, 45, tzinfo=JST).timestamp()
CLOSE = START + 405*60


# ----------------------------------------
class Quote(NamedTuple):
    """採用した価格時計、原板の物理行、最良買い・売り気配。"""
    time: float
    line: int
    bid: float
    ask: float

    @property
    def normal(self) -> bool:
        """
        機能：正常な最良気配を確認する。
        引数：self（Quote）は物理行。
        返り値：boolは価格が正で売り気配が買い気配を上回るとき真。
        """
        return 0 < self.bid < self.ask


# ----------------------------------------
def clock(at: float) -> str:
    """
    機能：価格時計を日本時間の時分秒で表示する。
    引数：at（float）はエポック秒。
    返り値：strは時分秒。
    """
    return datetime.fromtimestamp(at, JST).strftime('%H:%M:%S')


# ----------------------------------------
def read_book(symbol: str) -> tuple[list[Quote], dict]:
    """
    機能：原板を物理行順に読み、デイ内の価格が正で価格時計が戻っていない行を採用する。
    引数：symbol（str）は対象先物。
    返り値：tupleは採用原行の列と、検算に使った原板の指紋。
    """
    raw = ROOT.parent/'JP_OSE_Data/future'/symbol/SCENE/'book.jsonl'
    rows = []
    previous = START
    digest = hashlib.sha256()
    with raw.open('rb') as stream:
        for line, data in enumerate(stream, 1):
            digest.update(data)
            obj = json.loads(data)
            stamp = obj.get('CurrentPriceTime')
            if not stamp:
                continue
            t = datetime.fromisoformat(stamp).timestamp()
            if previous <= t <= START+420*60 and (obj.get('CurrentPrice') or 0) > 0:
                rows.append(Quote(t, line, obj['Buy1']['Price'], obj['Sell1']['Price']))
                previous = t
    return rows, {'商品':symbol, '物理行':line, '採用行':len(rows), '正常気配':sum(q.normal for q in rows),
                  '原板SHA256':digest.hexdigest(), 'バイト数':raw.stat().st_size}


# ----------------------------------------
def measurements(rows: list[Quote]) -> tuple[dict, list]:
    """
    機能：開始後最初と各5分境界直前の仲値から、前回と同じ時計で区間の値動きを得る。
    引数：rows（list[Quote]）は単一商品の採用原行。
    返り値：tupleは端点・3区間の変化と15:30までの5分騰落率。
    """
    valid = [q for q in rows if q.normal]
    times = [q.time for q in valid]
    gaps = [i for i in range(1,len(times)) if times[i]-times[i-1] > 300]
    indices = []
    for i in range(82):
        t = START + i*300
        j = bisect_left(times, t) - (0 if i == 0 else 1)
        indices.append(j if 0 <= j < len(times) and abs(times[j]-t) <= 30 else None)
    # ----------------------------------------
    def change(a: int, b: int) -> dict | None:
        """
        機能：正常板の途中空白と端点欠測を確認して変化を求める。
        引数：a・b（int）は開始からの5分窓境界番号。
        返り値：dictまたはNoneは指数ポイント・bp変化。
        """
        i,j = indices[a],indices[b]
        if i is None or j is None or i >= j or bisect_left(gaps,i+1) != bisect_left(gaps,j+1):
            return None
        start = (valid[i].bid+valid[i].ask)/2
        end = (valid[j].bid+valid[j].ask)/2
        return {'ポイント':end-start,'bp':10000*(end-start)/start}
    edges = {}
    for n in (0,3,6,9):
        idx = indices[n]
        q = valid[idx] if idx is not None else None
        edges[clock(START+300*n)] = {'気配時刻':clock(q.time),'最良買':q.bid,'最良売':q.ask,
                                     '仲値':(q.bid+q.ask)/2,'原行':q.line} if q else None
    return {'端点':edges, '寄り前':change(0,3), '寄り後15分':change(3,6), '寄り後30分':change(3,9)}, [change(i,i+1) for i in range(81)]


# ----------------------------------------
def check_trades(symbol: str, rows: list[Quote], trades: list[dict]) -> list[dict]:
    """
    機能：建値と原板の一致を検査し、各建値の次の原行から独立にIFD・期限・場末を再走査する。
    引数：symbol（str）は商品、rows（list[Quote]）は元の原板、trades（list[dict]）は固定口座の建玉。
    返り値：list[dict]は原行で再計算した側・先着・費用後損益。
    """
    multiplier, cost = (100,1077) if symbol == 'NK225' else (1000,583.6)
    result = []
    for t in trades:
        assert t['scene'] == SCENE
        entry = rows[t['entry_index']]
        direction = 1 if t['side'] == 0 else -1
        base = entry.ask if direction == 1 else entry.bid
        assert (entry.line,entry.time,entry.normal,base) == (t['entry_line'],t['entry_time'],True,t['entry_price'])
        deadline = math.inf if t['horizon']=='SESSION' else entry.time+60*int(t['horizon'][1:])
        last = last_normal = entry.time
        exit_quote, label = None, 2
        worst = direction*((entry.bid if direction==1 else entry.ask)-base)
        worst_time = entry.time
        for q in rows[t['entry_index']+1:]:
            if q.time > min(CLOSE,deadline+30) or (last < min(CLOSE,deadline) and q.time-last > 300):
                break
            if last_normal < min(CLOSE,deadline) and q.time-last_normal > 300:
                break
            last = q.time
            if not q.normal:
                continue
            last_normal = q.time
            mark = q.bid if direction == 1 else q.ask
            points = direction*(mark-base)
            if points < worst:
                worst, worst_time = points, q.time
            if q.time <= deadline and abs(points) >= t['width']:
                exit_quote, label = q, (1 if points > 0 else -1)
                break
            if q.time >= min(deadline, CLOSE-59):
                exit_quote, label = q, 0
                break
        net = None
        if exit_quote is not None:
            net = round(points*multiplier-cost, 2)
            assert (exit_quote.time,exit_quote.line,mark,points*multiplier) == (t['exit_time'],t['exit_line'],t['exit_price'],t['gross'])
        assert label == t['label'] and net == t['net']
        result.append({'方向':'買' if direction==1 else '売','取得時計':clock(entry.time),'取得物理行':entry.line,
                       '決済物理行':exit_quote.line if exit_quote else None,'費用後円':net,'先着':label,
                       '観測中の最大逆行ポイント':-min(worst,0),'最大逆行の初回時刻':clock(worst_time)})
    return result


# ----------------------------------------
def compare_position(trades: list[dict]) -> dict:
    """
    機能：TOPIXの朝LCの発注時刻より厳密に前の90秒以内に分かる日経のEMA8乖離を読む。
    引数：trades（list[dict]）はTOPIXの固定口座の建玉。
    返り値：dictは朝の実取得数、該当LCごとの判別結果。
    """
    early = [t for t in trades if t['entry_time']<START+900]
    candidates = [t for t in early if t['added']]
    result = {'寄り前取得数':len(early),'寄り前LC取得数':len(candidates),'LC価格位置の検査':[]}
    if not candidates:
        return result
    path = ROOT/'work/215日経/母集団/当時特徴.json.gz'
    with gzip.open(path,'rb') as f:
        source = json.load(f)
    field = [c['name'] for c in source['catalog']].index('q0_entry_minus_ema8_atr5_to_side')
    local = [r for r in source['rows'] if r['session']==SCENE]
    times = [r['metadata']['q0']['time'] for r in local]
    assert times and times == sorted(times)
    for t in candidates:
        query = t['request_time']
        i = bisect_left(times,query)-1
        peer = local[i] if i>=0 and query-times[i]<=90 else None
        side = 'buy' if t['side']==0 else 'sell'
        pos = peer[side]['x'][field] if peer else None
        if pos is not None and not math.isfinite(pos):
            pos = None
        if peer is None:
            status = '直前90秒に判断なし'
        elif pos is None:
            status = '位置算出不能'
        elif pos > 1.5:
            status = '注文方向へ1.5ATR超'
        elif pos < -2:
            status = '注文方向と反対へ2ATR超'
        else:
            status = '範囲内'
        result['LC価格位置の検査'].append({'売買':side,'発注判断':clock(query),'相手判断':clock(times[i]) if peer else None,
                                         '方向付き価格位置ATR':pos,'区分':status,'元収支円':t['net']})
    return result


# ----------------------------------------
def main() -> None:
    """
    機能：原板の朝の値動きと、任意で固定建玉の先着・費用後損益・朝LCの位置を確認する。
    引数：なし。コマンドラインの「--取引」で固定建玉の照合も行う。
    返り値：None。照合結果をUTF-8のJSONに保存する。
    """
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--取引',action='store_true')
    args = parser.parse_args()
    rows, market, windows = {}, {'場':SCENE,'原板':{}}, {}
    for s in SYMBOLS:
        rows[s],market['原板'][s] = read_book(s)
        market[s],windows[s] = measurements(rows[s])
    # ----------------------------------------
    market['5分変化の相関'] = {}
    for name,lo,hi in [('全対象時間',0,81),('寄り前',0,3),('09時から09時半',3,9)]:
        pairs = [(a['bp'],b['bp']) for a,b in zip(windows['NK225'][lo:hi],windows['TOPIX'][lo:hi],strict=True) if a and b]
        unique = len(pairs)>1 and all(len(set(col))>1 for col in zip(*pairs))
        market['5分変化の相関'][name] = {'正常窓':len(pairs), '予定窓':hi-lo, '相関':correlation(*zip(*pairs)) if unique else None}
    (HERE/'価格.json').write_text(json.dumps(market,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    if not args.取引:
        return
    # ----------------------------------------
    ts = {'NK225':json.loads((HERE.parent/'日経/固定結果.json').read_bytes())['結果']['建玉'],
          'TOPIX':json.loads((HERE.parent/'TOPIX/固定照合.json').read_bytes())['追加']['取得']}
    checked = {'全取引の原板再照合':{},'09時前の全取得':{},'TOPIXの寄り前LC':compare_position(ts['TOPIX'])}
    for s in SYMBOLS:
        checked['全取引の原板再照合'][s] = check_trades(s,rows[s],ts[s])
        checked['09時前の全取得'][s] = [{'取得':clock(t['entry_time']), '側':'買' if t['side']==0 else '売',
                                    'LC':t['added'], '費用後円':t['net'],
                                    '寄り後15分の注文方向ポイント':market[s]['寄り後15分']['ポイント']*(1 if t['side']==0 else -1)
                                        if market[s]['寄り後15分'] else None} for t in ts[s] if t['entry_time']<START+900]
    (HERE/'建玉の照合.json').write_text(json.dumps(checked,ensure_ascii=False,indent=2)+'\n',encoding='utf8')


if __name__ == '__main__':
    main()
