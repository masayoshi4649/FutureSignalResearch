"""日経固定通知へTOPIXの確定気配足を加え、単一建玉口座を再生する。"""
from collections.abc import Callable
from math import ceil, inf
from pathlib import Path
import json
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'work/217通知'
PREVIOUS = next((ROOT/'study').glob('00213_*'))
sys.path[:0] = [str(PREVIOUS/'日経取得通知の対照'), str(ROOT/'scripts/複合検証')]
import 追随を診断する as follow
import データ準備 as prep

RULES = {
    '通知00': '日経199_02固定通知をそのまま利用',
    '通知01': 'TOPIXの3分と12分変化がともに注文方向に逆行したら見送り',
    '通知02': 'TOPIXの3分変化が逆行し数量比が1.3以上なら見送り',
    '通知03': 'TOPIXの12分変化が逆行し12分経路効率が0.35以上なら見送り',
    '通知04': 'TOPIXの3分変化が逆行し12分経路効率が0.25未満なら見送り',
    '通知05': 'TOPIXの直近終値が15分出来高加重気配中心の逆側で、加重中心も3分前より逆行なら見送り',
    '通知06': 'TOPIXの直近終値が12分値幅の注文側端20%で3分変化が1分平均値幅の2倍超、日経の3分変化が逆行なら見送り',
    '通知07': '日経とTOPIXの3分変化がともに逆行し、TOPIXの12分変化も逆行なら見送り',
    '通知08': '日経の12分変化が順行だがTOPIXの12分変化と直近3分変化が逆行なら見送り',
    '通知09': 'TOPIXの直近終値が12分値幅の注文側端20%で3分変化が1分平均値幅の2倍超、数量比が1未満なら見送り',
}


# ----------------------------------------
def read(path: Path) -> object:
    """
    機能：日本語のJSONを読み込む。
    引数：path（Path）は保存先。
    返り値：objectは展開した内容。
    """
    return json.loads(path.read_bytes())


def cache_for(symbol: str, scene: str) -> Path:
    """
    機能：恒久8列を優先し、追加3日で存在しない8列だけ共用原板から再構築する。
    引数：symbol・scene（str）は商品と場。
    返り値：Pathは対象の原順8列。
    """
    source_name = scene + '.npz'
    paths = [next((ROOT/'inputs').glob(symbol+'原順8列_*'))/source_name,
             next((ROOT/'inputs').glob('00194_*'))/'原順8列'/symbol/source_name]
    if symbol == 'TOPIX':
        paths.append(ROOT/'work/216TOPIX専用/原順8列'/source_name)
    for path in paths:
        if path.exists():
            return path
    path = WORK/symbol/source_name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        raw_dir = ROOT.parent/'JP_OSE_Data/future'/symbol/scene
        raw = next(p for p in (raw_dir/'book.jsonl', raw_dir/'book.jsonl.gz') if p.exists())
        prep.build_one(raw, path, symbol, scene, ROOT.parent/'JP_OSE_Data')
    return path


def bars(path: Path, start: float, end: float) -> tuple:
    """
    機能：価格時計の高水位を保ち、正常板の中値で1分足と累積出来高差分を作る。
    引数：path（Path）は原順8列、start・end（float）は時刻。
    返り値：tupleは各足の最初の正常板時刻、終値・高値・安値・観測数量。
    """
    n = int((end-start)/60)
    first, close, high, low, volume = np.full((5,n), np.nan)
    with np.load(path, allow_pickle=False) as source:
        t = source['now']
        keep = np.isfinite(t) & (t >= np.maximum.accumulate(np.where(np.isfinite(t),t,-inf))) & (t>=start) & (t<end)
        minute = ((t[keep]-start)//60).astype(int)
        good = source['valid'][keep]
        times = t[keep][good]
        minute_good = minute[good]
        middle = ((source['ask'][keep]+source['bid'][keep])/2)[good]
        if len(middle):
            indices = np.r_[0,np.flatnonzero(np.diff(minute_good))+1]
            ids = minute_good[indices]
            first[ids] = times[indices]
            close[ids] = middle[np.r_[indices[1:]-1,len(middle)-1]]
            high[ids] = np.maximum.reduceat(middle,indices)
            low[ids] = np.minimum.reduceat(middle,indices)
        # ----------------------------------------
        qty, qt = source['volume'][keep],source['volume_time'][keep]
        allowed = np.isfinite(qty) & (qty>=0) & np.isfinite(qt) & (qt<=t[keep])
        qi, qtime, bucket = qty[allowed], qt[allowed], minute[allowed]
        if len(qi)>1:
            delta = np.diff(qi)
            usable = (delta>=0) & (np.diff(qtime)>=0) & (np.diff(bucket)<=1)
            sums = np.bincount(bucket[1:][usable], weights=delta[usable], minlength=n)
            invalid = set(bucket[1:][~usable]) | {bucket[0]}
            filled = np.array(sorted(set(bucket)-invalid), dtype=int)
            volume[filled] = sums[filled]
    return first,close,high,low,volume


def snapshot(columns: tuple, start: float, time: float, side: int) -> dict:
    """
    機能：通知と同秒の板を含めず、次の分の正常板を確認できた確定気配足から判断値を得る。
    引数：columns（tuple）は1分足、start・time（float）は場開始と通知、side（int）は注文方向。
    返り値：dictは方向正規化した変化、量・位置・経路効率・加重中心。履歴不足はNaN。
    """
    first, close, high, low, volume = columns
    i = int((time-start)//60)-1
    keys = 'r3 r12 efficiency volume_ratio edge advance vwap_bias vwap_change'.split()
    v = dict.fromkeys(keys,np.nan)
    if i<3 or i+1>=len(first) or not first[i+1]<time:
        return v
    c = close[:i+1]
    if np.isfinite(c[-4:]).all():
        v['r3'] = side*(c[-1]-c[-4])
    if i>=12 and np.isfinite(c[-13:]).all():
        change = side*(c[-1]-c[-13])
        path = np.abs(np.diff(c[-13:])).sum()
        top, bottom = max(high[i-11:i+1]), min(low[i-11:i+1])
        span = np.maximum(high[i-11:i+1],c[-13:-1])-np.minimum(low[i-11:i+1],c[-13:-1])
        v.update(r12=change,efficiency=abs(change)/path if path else 0,
                 edge=(c[-1]-bottom if side==1 else top-c[-1])/(top-bottom) if top>bottom else np.nan,
                 advance=v['r3']/span.mean() if span.mean()>0 else np.nan)
        qty = volume[i-11:i+1]
        if np.isfinite(qty).all() and qty[:-3].mean()>0:
            v['volume_ratio'] = qty[-3:].mean()/qty[:-3].mean()
    # ----------------------------------------
    if i>=17:
        qty = volume[i-17:i+1]
        mid = (high[i-17:i+1]+low[i-17:i+1]+c[-18:])/3
        if np.isfinite(qty).all() and np.isfinite(mid).all() and min(qty[-15:].sum(),qty[:15].sum())>0:
            recent = np.average(mid[-15:], weights=qty[-15:])
            before = np.average(mid[:15], weights=qty[:15])
            v.update(vwap_bias=side*(c[-1]-recent),vwap_change=side*(recent-before))
    return v


def vetoes(t: dict, n: dict) -> list:
    """
    機能：日経通知と逆向きの圧力・低効率・先行過熱を、事前固定した候補別に判定する。
    引数：t・n（dict）はTOPIX・日経の通知前観測。
    返り値：listは各口座の見送り真偽。必要値欠測時は元通知を通す。
    """
    short, medium = t['r3']<0, t['r12']<0
    chased = t['edge']>=0.8 and t['advance']>2
    return [False, short and medium, short and t['volume_ratio']>=1.3,
            medium and t['efficiency']>=0.35, short and t['efficiency']<0.25,
            t['vwap_bias']<0 and t['vwap_change']<0, chased and n['r3']<0,
            n['r3']<0 and short and medium, n['r12']>0 and short and medium,
            chased and t['volume_ratio']<1]


# ----------------------------------------
def replay(work: Path, rules: dict, decision: Callable) -> None:
    """
    機能：全181通知の技術条件・単独の約定代用を計算し、候補ごとに予約・保有枠を順次再生する。
    引数：work（Path）は出力先、rules（dict）は候補、decision（Callable）は通知時点の見送り判定。
    返り値：None。比較元帳、再現指紋、通知の採否を保存する。
    """
    work.mkdir(parents=True,exist_ok=True)
    old,_,_ = follow.materials()
    orders = {day:rows for day,(_,_,rows) in old.items()}
    middle = next((ROOT/'study').glob('00215_*'))
    latest = next((ROOT/'study').glob('00216_*'))
    added = ['2026-11-18_Day','2026-11-19_Day','2026-11-20_Day']
    orders[added[0]] = read(PREVIOUS/'日経の追加デイ/追加デイの照合結果.json')['結果']['純入口']['建玉']
    for day,where in zip(added[1:],(middle,latest),strict=True):
        orders[day] = read(where/'日経/固定結果.json')['結果']['建玉']
    original = read(PREVIOUS/'日経取得通知の対照/結果.json')['取引']
    for where in (middle,latest):
        for values in read(where/'通知と同期の結果.json')['通知対照'].values():
            original.extend(values['取得'])
    # ----------------------------------------
    books = {key:[] for key in rules}
    decisions = {key:[] for key in rules}
    inputs = {}
    for day,events in sorted(orders.items()):
        start,regular_end = prep.session_bounds(day)
        end = regular_end-600
        paths = {s:cache_for(s,day) for s in ('TOPIX','NK225')}
        inputs[day] = {s:follow.digest(p) for s,p in paths.items()}
        tb, nb = (bars(paths[s],start,end) for s in ('TOPIX','NK225'))
        prices = follow.quotes(paths['TOPIX'],start,end)
        release = dict.fromkeys(rules,-inf)
        for e in events:
            now,side = e['entry_time'], 1 if e['side']==0 else -1
            features = (snapshot(b,start,now,side) for b in (tb,nb))
            rejects = decision(*features)
            p = prices['now'].searchsorted(now)-1
            valid = p>=0 and now-prices['now'][p]<=60
            cell = None
            if valid:
                mid = (prices['bid'][p]+prices['ask'][p])/2
                width = ceil(4*mid*e['width']/e['entry_price'])/4
                cell = follow.exit_and_fill(prices,e,width,end)
            for (rule, book),reject in zip(books.items(),rejects,strict=True):
                status = '取得'
                if now<=release[rule]:
                    status='枠占有'
                elif reject:
                    status='技術見送り'
                elif not valid:
                    status='基準板不足'
                elif cell is None:
                    status='取得失効'
                    release[rule] = min(now+30,end-60)
                else:
                    release[rule] = end if cell['net'] is None else cell['exit_time']
                    book.append(dict(cell,scene=day,signal_time=now,nk_line=e['entry_line'],horizon=e['horizon']))
                decisions[rule].append((day,now,status))
    # ----------------------------------------
    assert list(sorted(books['通知00'],key=lambda x:x['entry_time'])) == list(sorted(original,key=lambda x:x['entry_time']))
    assert len(orders)==45 and sum(len(v) for v in orders.values())==181
    assert abs(follow.totals(books['通知00'])['収支']-266379.6)<1e-6
    mapped = {rule:[dict(t,label={'F':1,'A':-1,'N':0,'C':2}[t['label']],confirmed_until=t['known_until'])
                    for t in book] for rule,book in books.items()}
    for name,v in [('比較元帳',mapped),('通知採否',decisions),('入力指紋',inputs)]:
        (work/(name+'.json')).write_text(json.dumps(v,ensure_ascii=False,allow_nan=False),encoding='utf8')


if __name__=='__main__':
    replay(WORK,RULES,vetoes)
