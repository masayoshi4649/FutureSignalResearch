"""両指数の同期した値動き、寄り付き前後、過去の変動幅で換算した同一通知の経路を調べる。"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import statistics
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = next((ROOT/'study').glob('00213_*'))
sys.path.insert(0, str(OLD))
from 同時刻の両指数を照合する import ledgers
from 金融再生 import read, load_scene, closing, settle

SYMBOLS = ('NK225', 'TOPIX')
TICKS = np.array([5.0, 0.25])
YEN = np.array([100.0, 1000.0])
JST = timezone(timedelta(hours=9))


# ----------------------------------------
class Midpoints:
    """単調な価格時計上の正常BBOと空白の位置。"""

    def __init__(self, index: object) -> None:
        """
        機能：正常な最良気配の仲値を原行順に用意する。
        引数：index（PriceIndex）は一商品・一場の検査済み索引。
        返り値：None。
        """
        normal = index.rows[index.normal]
        self.t = normal['time']
        self.mid = (normal['bid'] + normal['ask'])/2
        self.gaps = np.flatnonzero(np.diff(self.t) > 300) + 1

    def at(self, clock: float, first: bool=False) -> int | None:
        """
        機能：直前30秒以内の正常気配、または開始時だけ以降30秒以内の最初の気配を返す。
        引数：clock（float）は価格時計、first（bool）は開始を探す指定。
        返り値：intまたはNoneは該当位置。
        """
        i = int(self.t.searchsorted(clock)) - (0 if first else 1)
        return i if 0 <= i < len(self.t) and abs(self.t[i]-clock)<=30 else None

    def change(self, start: int | None, end: int | None) -> tuple | None:
        """
        機能：端点が既知かつ正常板空白がない場合の値幅と変化率を返す。
        引数：start/end（intまたはNone）は場内の正常板位置。
        返り値：tupleまたはNoneはポイント変化、bp変化。
        """
        if start is None or end is None or start >= end:
            return None
        if self.gaps.searchsorted(start, side='right') != self.gaps.searchsorted(end, side='right'):
            return None
        change = self.mid[end]-self.mid[start]
        return float(change), float(10000*change/self.mid[start])


# ----------------------------------------
def market_summary(rows: list) -> dict:
    """
    機能：同じ時刻の5分変化と、隣接する5分だけをずらした変化の相関・振幅を集計する。
    引数：rows（list）は同時観測が可能な場・窓・ポイント・bp。
    返り値：dictは観測数、相関と尺度別の変動。
    """
    if not rows:
        return {'窓':0}
    points = np.array([r['pt'] for r in rows])
    bp = np.array([r['bp'] for r in rows])
    lookup = {(r['場'],r['分']):r for r in rows}
    lag = [(lookup[r['場'],r['分']-5]['bp'],r['bp']) for r in rows if (r['場'],r['分']-5) in lookup]
    result = {'窓':len(rows),'場':len({r['場'] for r in rows}),
              '同時相関':float(np.corrcoef(bp.T)[0,1]) if len(bp)>2 else None,
              'RMS_bp':np.sqrt((bp**2).mean(axis=0)).tolist(),
              'RMS_ティック':np.sqrt(((points/TICKS)**2).mean(axis=0)).tolist(),'隣接窓':len(lag)}
    if len(lag)>2:
        before, after = np.array(lag).transpose(1,0,2)
        result['日経先TOPIX後相関'] = float(np.corrcoef(before[:,0],after[:,1])[0,1])
        result['TOPIX先日経後相関'] = float(np.corrcoef(before[:,1],after[:,0])[0,1])
    return result


# ----------------------------------------
def opening_summary(rows: list) -> dict:
    """
    機能：通常日の寄り前・後の符号を、各通知の売買方向又は場の寄り前方向にそろえて比較する。
    引数：rows（list）は各時点の両指数の符号付き変化率。欠測は行ごとに除いたもの。
    返り値：dictは正・負・同値の件数と平均・中央値bp。
    """
    if not rows:
        return {'同時完了':0}
    values = np.array(rows)
    return {'同時完了':len(rows),'順':(values>0).sum(axis=0).tolist(),'逆':(values<0).sum(axis=0).tolist(),
            '同値':(values==0).sum(axis=0).tolist(),'平均bp':values.mean(axis=0).tolist(),
            '中央値bp':np.median(values,axis=0).tolist()}


# ----------------------------------------
def width_summary(rows: list) -> dict:
    """
    機能：同一通知で両幅・両商品の決済が判明した組だけを比較する。
    引数：rows（list）は当時までの換算率と各取引の診断結果。
    返り値：dictは設定幅に対する損益と先着件数。
    """
    result = {'同時完了':len(rows)}
    if not rows:
        return result
    for k in ('日経','TOPIX呼値','TOPIX過去変動'):
        cells = [r[k] for r in rows]
        result[k] = {'順':sum(c['label']==1 for c in cells),'逆':sum(c['label']==-1 for c in cells),
                     '未到達':sum(c['label']==0 for c in cells),
                     '平均費用後幅比':statistics.mean(c['net']/(c['width']*(100 if k=='日経' else 1000)) for c in cells),
                     '平均費用前幅比':statistics.mean(c['gross']/(c['width']*(100 if k=='日経' else 1000)) for c in cells)}
    return result


# ----------------------------------------
def contrasts(means: np.ndarray) -> np.ndarray:
    """
    機能：二つの判断元・二つの取引商品ごとの平均を、対角差と二方向の平均差に分ける。
    引数：means（ndarray）は列順が日経判断の日経・TOPIX、TOPIX判断の日経・TOPIXの平均。
    返り値：ndarrayは対角差・判断元の差・取引商品の差。
    """
    a,b,c,d = means.T
    return np.array([a-d, (a-c+b-d)/2, (a-b+c-d)/2]).T


# ----------------------------------------
def decompose(old_pairs: dict, days: list) -> dict:
    """
    機能：213の同時計観測の日付集中、前後差、連続5日ブロックでのばらつきを求める。
    引数：old_pairs（dict）は固定観測、days（list）は旧42場。範囲は選択前に固定する。
    返り値：dictは幅単位の対角差と各要因。乱数種は固定。
    """
    sums = np.zeros((len(days),4))
    counts = np.zeros_like(sums)
    for i,source in enumerate(SYMBOLS):
        for pair in old_pairs[source]:
            if not all(pair[s] and pair[s]['net'] is not None for s in SYMBOLS):
                continue
            n = days.index(pair['場'])
            for j,s in enumerate(SYMBOLS):
                t = pair[s]
                sums[n,2*i+j] += t['net']/(t['width']*YEN[j])
                counts[n,2*i+j] += 1
    parts = {}
    for key,idx in [('旧42日',slice(None)),('前24日',slice(0,24)),('後18日',slice(24,None))]:
        mean = sums[idx].sum(axis=0)/counts[idx].sum(axis=0)
        parts[key] = {'平均幅比':mean.tolist(),'対角差と判断元差と商品差':contrasts(mean).tolist(),
                      '件数':counts[idx].sum(axis=0).astype(int).tolist()}
    indices = np.arange(len(days))
    leave = np.array([contrasts(sums[indices!=i].sum(axis=0)/counts[indices!=i].sum(axis=0)) for i in indices])
    rng = np.random.default_rng(214)
    starts = rng.integers(0,len(days),size=(10000,(len(days)+4)//5))
    selected = ((starts[:,:,None]+np.arange(5))%len(days)).reshape(len(starts),-1)[:,:len(days)]
    sampled = contrasts(sums[selected].sum(axis=1)/counts[selected].sum(axis=1))
    parts['一日ずつ除外の最小最大'] = np.stack((leave.min(axis=0),leave.max(axis=0))).tolist()
    parts['連続5日循環再抽出の中央95%'] = np.quantile(sampled,[.025,.975],axis=0).tolist()
    return parts


# ----------------------------------------
def main() -> None:
    """
    機能：旧42日と既評価の追加1日の固定診断を原行から実行し、数値と由来を保存する。
    引数：なし。
    返り値：None。新しい取引候補を選ばない。
    """
    trades, books = ledgers()
    new_nikkei = read(OLD/'日経の追加デイ/追加デイの照合結果.json')['結果']['純入口']['建玉']
    trades['NK225'].extend(new_nikkei)
    trades['TOPIX'] = read(next((OLD/'金融正本').glob('*03*.gz')))['取得']
    books['NK225'].append(ROOT/'work/213保留診断/日経追加/原行索引/manifest.json')
    refs = {s:{r['session']:(f.parent,r) for f in paths for r in read(f)['scenes']} for s,paths in books.items()}
    holidays = set(read(ROOT/'docs/データ監査/現物制度属性と入口の分布/分類前固定.json')['現物休場日'])
    days = sorted({r['scene'] for r in trades['NK225']})
    assert len(days)==43 and days[-1]=='2026-11-18_Day'
    old_pairs = read(OLD/'同期照合の明細.json.gz')
    fixed = {(source,p['場'],p['通知']):p for source,items in old_pairs.items() for p in items}
    groups = defaultdict(list)
    windows, previous, ratios, coverage = [], [], {}, {}
    cases, measured, signatures = defaultdict(list), defaultdict(Counter), {}
    for number, day in enumerate(days):
        period = '旧42日' if day!=days[-1] else '追加1日'
        holiday = day[:10] in holidays
        midnight = datetime.fromisoformat(day[:10]).replace(tzinfo=JST)
        start = (midnight+timedelta(hours=8,minutes=45)).timestamp()
        cut = start+405*60
        indices = [load_scene(*refs[s][day]) for s in SYMBOLS]
        signatures[day] = [refs[s][day][1]['index']['sha256'] for s in SYMBOLS]
        mids = [Midpoints(i) for i in indices]
        before9 = [m.at(start+900) for m in mids]
        checkpoints = {h:[m.at(start+60*h) for m in mids] for h in (30,45)}
        sample = []
        for minute in range(0,405,5):
            diffs = [m.change(m.at(start+60*minute,first=minute==0),m.at(start+60*(minute+5))) for m in mids]
            if any(v is None for v in diffs):
                continue
            sample.append({'場':day,'分':minute,'休日':holiday,'pt':[v[0] for v in diffs],'bp':[v[1] for v in diffs]})
        windows.extend(sample)
        coverage[day]=len(sample)
        ratio = None
        if len(previous)>=5 and all(len(x)>0 for x in previous[-5:]):
            prices = np.array([r['pt'] for daily in previous[-5:] for r in daily])
            rms = np.sqrt((prices**2).mean(axis=0))
            ratio = rms[1]/rms[0]
            ratios[day] = {'倍率':ratio,'共通窓':len(prices)}
        previous.append(sample)
        # ----------------------------------------
        # 入口にかかわらず、通常日全体で先物開始から現物寄り前までの動きが続くかを測る。
        opens = [m.change(m.at(start,first=True),b) for m,b in zip(mids,before9)]
        if not holiday and all(x is not None for x in opens):
            for h, ends in checkpoints.items():
                after = [m.change(b,e) for m,b,e in zip(mids,before9,ends)]
                if all(x is not None for x in after) and all(x[0]!=0 for x in opens):
                    groups[f'{period}/全通常日/{h}'].append([np.sign(a[0])*b[1] for a,b in zip(opens,after)])
        for source in SYMBOLS:
            for t in (r for r in trades[source] if r['scene']==day):
                event, side = t['entry_time'], t['side']
                direction = 1 if side==0 else -1
                key = f'{period}/{source}'
                budget = measured[key]
                budget['通知']+=1
                if event<start+900 and not holiday:
                    budget['通常日の09時前']+=1
                    own = [m.at(event+1,first=True) for m in mids]
                    pres = [m.change(o,b) for m,o,b in zip(mids,own,before9)]
                    if all(x is not None for x in pres):
                        groups[key+'/寄り前'].append([direction*x[1] for x in pres])
                    for h,ends in checkpoints.items():
                        post = [m.change(b,e) for m,b,e in zip(mids,before9,ends)]
                        if all(x is not None for x in post):
                            groups[key+f'/寄り後{h}'].append([direction*x[1] for x in post])
                if ratio is None:
                    budget['直前5日不足']+=1
                    continue
                width = t['width']*(20 if source=='TOPIX' else 1)
                cell = {}
                for name,i,w in [('日経',0,width),('TOPIX呼値',1,width/20),
                                 ('TOPIX過去変動',1,np.ceil(width*ratio*4)/4)]:
                    idx = indices[i]
                    fill = idx.first_normal(event+1)
                    if fill<0 or idx.times[fill]>=min(event+30,cut-60):
                        continue
                    v = settle(idx,fill,side,w,t['horizon'],cut,closing(idx,cut),SYMBOLS[i])
                    if period=='旧42日' and name!='TOPIX過去変動':
                        assert fixed[(source,day,event)][SYMBOLS[i]]==v
                    if v['net'] is not None:
                        cell[name]=v
                if len(cell)==3:
                    cases[key].append(cell)
                else:
                    budget['同時完了せず']+=1
    split = {}
    for label,dates in [('旧42日',days[:-1]),('追加1日',days[-1:])]:
        eligible = [r for r in windows if r['場'] in dates]
        masks = {'全体':eligible,'現物通常日': [r for r in eligible if not r['休日']],
                 '通常日寄り前':[r for r in eligible if not r['休日'] and r['分']<15],
                 '通常日09時から09時半':[r for r in eligible if not r['休日'] and 15<=r['分']<45],
                 '現物休場日':[r for r in eligible if r['休日']]}
        split[label] = {k:market_summary(rows) for k,rows in masks.items()}
    result = {'配列順':list(SYMBOLS),'5分同期':split,'日別5分窓':coverage,'直前5日倍率':ratios,
              '現物寄り前後':{k:opening_summary(rows) for k,rows in groups.items()},
              '幅尺度の母数':measured,'幅尺度の効果':{k:width_summary(rows) for k,rows in cases.items()},
              '213の幅差の分解':decompose(old_pairs,days[:-1]),'原行索引SHA256':signatures}
    for key,count in measured.items():
        assert sum((count['直前5日不足'],count['同時完了せず'],len(cases[key])))==count['通知']
    (HERE/'値動きの集計.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False,indent=1)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
