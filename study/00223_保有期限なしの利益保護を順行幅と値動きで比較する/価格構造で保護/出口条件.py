"""元の±1Rを保ち、短期の安値割れと利方向の再試行失敗で利益保護の幅を変える。"""
from pathlib import Path
import runpy

import numpy as np


STUDIES = Path(__file__).resolve().parents[2]
TECH = runpy.run_path(str(next(STUDIES.glob("00219_*/出口候補.py"))))
STATIC = runpy.run_path(str(next(STUDIES.glob("00221_*/元IFDの寄与/出口定義.py"))))
POLICIES = ["S00","S01","S02","S03","S04","S05","S06"]
THRESHOLDS = {"S01":.45,"S02":.45,"S03":.45,"S04":.30,"S05":.65,"S06":.45}


def completed_prices(index: object, scene: dict, bars: np.ndarray) -> tuple:
    """
    機能：正常な最良気配から取引開始基準の1分高値・安値・終値を計算する。
    引数：index（PriceIndex）は原板索引、scene（dict）は場の時計、bars（np.ndarray）は原行の分番号。
    返り値：tuple。高値・安値・終値の配列。観測がない分はNaN。
    """
    cut = scene["end"]-900
    size = int((cut-scene["start"])//60)+1
    high,low,close = np.full((3,size),np.nan)
    normal = index.normal
    ids = normal[(index.times[normal]>=scene["start"]) & (index.times[normal]<cut)]
    if len(ids):
        minute = bars[ids]
        mid = (index.rows["ask"][ids]+index.rows["bid"][ids])/2
        first = np.r_[0,np.flatnonzero(np.diff(minute))+1]
        high[minute[first]] = np.maximum.reduceat(mid,first)
        low[minute[first]] = np.minimum.reduceat(mid,first)
        close[minute[first]] = mid[np.r_[first[1:]-1,len(mid)-1]]
    return high,low,close


def structure(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> tuple:
    """
    機能：建玉方向を正に直した価格列で、確定した二つの山の間の安値割れと上位足の継続を判別する。
    引数：high・low・close（np.ndarray）は同じ売買方向に正規化した各分の高値・安値・終値。
    返り値：tuple。翌分から使える最初の山の分番号、上位足判定の可否、上昇継続状態。
    """
    size = len(close)
    first_top = np.full(size,-1,dtype=int)
    ready,positive = np.zeros((2,size),dtype=bool)
    tops = []
    streak = 0
    ema = 0
    for j in range(size-1):
        if not np.isfinite(close[j]):
            streak = 0
            tops.clear()
            continue
        ema = ema+(close[j]-ema)*2/9 if streak else close[j]
        streak += 1
        next_minute = j+1
        boundary = next_minute//5*5
        if boundary>=10 and streak>=next_minute-boundary+10:
            ready[next_minute] = True
            positive[next_minute] = close[boundary-1]>close[boundary-6] and close[j]>ema
        # ----------------------------------------
        if streak>=3 and high[j-1]>high[j-2] and high[j-1]>=high[j]:
            tops.append(j-1)
        if len(tops)<2 or streak<4:
            continue
        a,b = tops[-2:]
        if not (2<=b-a<=9 and 1<=j-b<=4 and high[b]<=high[a]):
            continue
        valley = min(low[a+1:b])
        if close[j]<valley<=close[j-1] and close[j]<close[j-3]:
            first_top[next_minute] = a
    return first_top,ready,positive


def prepare(index: object, scene: dict) -> dict:
    """
    機能：各正常行で公表済みの1分・5分の状態を、買いと売りの鏡像で準備する。
    引数：index（PriceIndex）は原板索引、scene（dict）は場の開始・終了定義。
    返り値：dict。完成価格の構造、前の高値の形成時刻、利用可能な観測時計。
    """
    context = TECH["prepare"](index,scene)
    high,low,close = completed_prices(index,scene,context["bar"])
    context["structure"] = (structure(high,low,close),structure(-low,-high,-close))
    return context


def patterns(context: dict, index: object, ids: np.ndarray, entry: int, side: int) -> tuple:
    """
    機能：両順行後パターンと5分継続拒否について、当該建玉で利用可能な各原行の判定を返す。
    引数：context（dict）は完成足、index（PriceIndex）は原板、ids（np.ndarray）は有効原行、
    entry・side（int）は新規原行と方向。
    返り値：tuple。5分も伴う安値割れ、再試行の失敗、継続中以外でどちらか成立、の真偽列。
    """
    bars = context["bar"][ids]
    top,ready,positive = context["structure"][side]
    after_entry = context["start"]+60*top[bars]>=index.times[entry]
    retest = (top[bars]>=0) & after_entry
    broken = context["broken"][side,bars] & context["adverse"][side,bars]
    return broken,retest,(broken|retest) & ready[bars] & ~positive[bars]


def early_structure(code: str, context: dict, index: object, ids: np.ndarray, entry: int,
                    side: int, width: float, move: np.ndarray, peak: np.ndarray) -> tuple:
    """
    機能：場内時計に制約を置かず、順行と構造により早期保護を選ぶ初回条件を評価する。
    引数：code（str）は候補、context（dict）は完成足、index（PriceIndex）は板、ids・move・peak（np.ndarray）は
    有効原行・利益方向値幅・既知最大順行、entry・side（int）は新規原行と方向、width（float）は元幅。
    返り値：tuple。各正常原行での早期保護、全起動、保護床の候補値。
    """
    early = np.zeros(len(ids),dtype=bool)
    if code!="S00":
        broken,retest,either = patterns(context,index,ids,entry,side)
        pattern = {"S01":broken,"S02":retest,"S06":True}.get(code,either)
        early = (peak>=THRESHOLDS[code]*width) & (move>=.15*width) & pattern
    return early,(peak>=.90*width)|early,np.maximum(20,peak-np.where(early,.40,.80)*width)


def settle(code: str, context: dict, index: object, entry: int, side: int, width: float,
           horizon: str, term: dict, early_rule: object, delay_seconds: int=1) -> dict:
    """
    機能：元の両注文と場末を維持し、利益保護の起動・発動・実際に返せる原行を順に求める。
    引数：code・horizon（str）は候補と場末期限、context・term（dict）は確定技術と観測終端、
    index（PriceIndex）は原板、entry・side（int）は新規原行と側、width（float）は片幅、
    early_rule（callable）は早期保護の候補判定、delay_seconds（int）は執行遅延。
    返り値：dict。元価格注文または保護の返済原行・時刻と設定した床。
    """
    assert horizon=="SESSION" and delay_seconds>=1
    result = STATIC["decide"]("D00",context,index,entry,side,width,horizon,term)
    result.update(activated=False,activation_index=-1,activation_time=None,trigger_time=None,
                  trigger_index=-1,trigger_reason=None,floor_points=None,structure_at=None)
    end = result["exit_index"]
    stop = min(end,term["touch_end"]) if end>=0 else term["touch_end"]
    left,right = np.searchsorted(index.normal,[entry+1,stop])
    ids = index.normal[left:right]
    if not len(ids):
        return result
    sign = 1 if side==0 else -1
    price = index.rows["ask" if side==0 else "bid"][entry]
    move = sign*(index.rows["bid" if side==0 else "ask"][ids]-price)
    times = index.times[ids]
    peak = np.maximum.accumulate(move)
    early,arm,floors = early_rule(code,context,index,ids,entry,side,width,move,peak)
    # ----------------------------------------
    active = np.logical_or.accumulate(arm)
    start = TECH["first_true"](active)
    if start<0:
        return result
    floor = np.maximum.accumulate(np.where(active,floors,-np.inf))
    crossing = np.r_[False,active[:-1] & (move[1:]<=floor[:-1])]
    trigger = TECH["first_true"](crossing)
    until = trigger if trigger>=0 else len(ids)-1
    proof = TECH["first_true"](early[:until+1])
    result.update(activated=True,activation_index=int(ids[start]),activation_time=float(times[start]),
                  floor_points=float(floor[trigger-1] if trigger>=0 else floor[-1]),
                  structure_at=float(times[proof]) if proof>=0 else None)
    if trigger>=0:
        result.update(trigger_time=float(times[trigger]),trigger_index=int(ids[trigger]),
                      trigger_reason="構造確認と利益保護")
        fill = int(np.searchsorted(times,times[trigger]+delay_seconds))
        if fill<len(ids):
            result.update(exit_index=int(ids[fill]),status=5,reason="構造確認と利益保護")
    return result


def decide(code: str, context: dict, index: object, entry: int, side: int, width: float,
           horizon: str, term: dict, delay_seconds: int=1) -> dict:
    """
    機能：初回の構造条件を元の価格注文と比較し、実行可能な返済を返す。
    引数：code・horizon（str）は候補と期限、context・term（dict）は観測済み技術と場末、
    index（PriceIndex）は原板、entry・side（int）は取得原行・側、width（float）は元幅、delay_seconds（int）は執行遅延。
    返り値：dict。静的または追尾の返済行と起動履歴。
    """
    return settle(code,context,index,entry,side,width,horizon,term,early_structure,delay_seconds)
