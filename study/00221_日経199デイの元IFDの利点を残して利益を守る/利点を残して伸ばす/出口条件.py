"""初期IFDを残し、早く一方向に進んだ建玉に限って利確目標を延ばす。"""
from pathlib import Path
import runpy

import numpy as np

STUDY = Path(__file__).resolve().parents[2]
BASE = runpy.run_path(str(next(STUDY.glob("00220_*/主比較/出口条件.py"))))
POLICIES = [f"H{i:02}" for i in range(9)]


def prepare(index: object, scene: dict) -> dict:
    """
    機能：原板の中値で当日完成した1分足から、各分に利用できる直前5分の上下端を計算する。
    引数：index（PriceIndex）は気配索引、scene（dict）はセッションの開始・終了。
    返り値：dict。開始時刻と直前5分高値・安値。
    """
    start, cut = scene["start"], scene["end"]-900
    n = int((cut-start)//60)+1
    ids = index.normal[(index.times[index.normal]>=start) & (index.times[index.normal]<cut)]
    bars = ((index.times[ids]-start)//60).astype(int)
    mid = (index.rows["bid"][ids]+index.rows["ask"][ids])/2
    highs, lows = np.full(n,-np.inf), np.full(n,np.inf)
    np.maximum.at(highs,bars,mid)
    np.minimum.at(lows,bars,mid)
    high5, low5 = np.full(n,np.nan), np.full(n,np.nan)
    for i in range(5,n):
        if np.isfinite(highs[i-5:i]).all():
            high5[i], low5[i] = highs[i-5:i].max(), lows[i-5:i].min()
    return {"start":start,"high5":high5,"low5":low5}


def decide(code: str, context: dict, index: object, entry: int, side: int,
           width: float, horizon: str, term: dict) -> dict:
    """
    機能：元の指値を置き、条件成立時の注文変更が有効になった後に限って延長・保護を適用する。
    引数：code・horizon（str）は候補と元期限、context・term（dict）は完成足・観測限界、
    index（PriceIndex）は板、entry・side（int）は新規原行と売買、width（float）は元の片幅。
    返り値：dict。初期幅、変更要求・発効時計、利益保護、決済原行・理由。
    """
    initial = BASE["settle"]("P0",width,context,index,entry,side,width,horizon,term)
    initial.update(extension_live=False, switch_request_time=None, switch_time=None, revised_target_points=None)
    if code=="H00":
        return initial
    sign = 1 if side==0 else -1
    price = float(index.rows["ask" if side==0 else "bid"][entry])
    marks = index.rows["bid" if side==0 else "ask"]
    normal, times = index.normal, index.times
    boundary = int(term["touch_end"])
    old_end = initial["exit_index"]
    if code=="H01":
        change = entry
        initial["target_points"] = 1.5*width
    else:
        stop = min(boundary, old_end) if old_end>=0 else boundary
        lower, upper = np.searchsorted(normal,[entry+1,stop])
        ids = normal[lower:upper]
        raw = sign*(marks[ids]-price)
        passed = np.flatnonzero(raw>=.60*width)
        if not len(passed):
            return initial
        first = passed[0]
        decision = int(ids[first])
        shallow = min(sign*(marks[entry]-price),raw[:first+1].min())>-.25*width
        steady = times[decision]-times[entry]<=600 and shallow
        minute = int((times[decision]-context["start"])//60)
        mid = (index.rows["ask"][decision]+index.rows["bid"][decision])/2
        breakout = mid>context["high5"][minute] if side==0 else mid<context["low5"][minute]
        eligible = {"H02":steady,"H03":steady and breakout,"H04":not steady,"H05":steady and width<=200,
                    "H06":steady and width>=350,"H07":steady,"H08":steady}
        if not eligible[code]:
            return initial
        initial["switch_request_time"] = float(times[decision])
        at = np.searchsorted(times[ids],times[decision]+1)
        if at==len(ids):
            return initial
        change = int(ids[at])
    # ----------------------------------------
    goal = (1.25 if code=="H07" else 1.5)*width
    initial.update(extension_live=True,switch_time=float(times[change]),revised_target_points=goal)
    lo,hi = (price-width,price+goal) if side==0 else (price-goal,price+width)
    hit = index.first_outside(max(entry+1,change),boundary,lo,hi,side)
    end, status = int(term["exit"]), int(term["status"])
    if hit>=0:
        end = int(hit)
        status = 1 if sign*(marks[end]-price)>0 else 2
    initial.update(exit_index=end,status=status,reason=BASE["REASONS"].get(status,"決済不明"))
    if code=="H08":
        return initial
    stop = min(end,boundary) if end>=0 else boundary
    left,right = np.searchsorted(normal,[max(entry+1,change),stop])
    ids = normal[left:right]
    moves = sign*(marks[ids]-price)
    passed = np.flatnonzero(moves>=width)
    if not len(passed):
        return initial
    armed = int(passed[0])
    ids, moves = ids[armed:], moves[armed:]
    floor = np.maximum(.9*width,np.maximum.accumulate(moves)-.25*width)
    initial.update(activated=True,activation_index=int(ids[0]),activation_time=float(times[ids[0]]),
                   floor_points=float(floor[-1]))
    triggers = np.flatnonzero(moves<=floor)
    if len(triggers):
        pos = int(triggers[0])
        trigger = int(ids[pos])
        initial.update(trigger_index=trigger,trigger_time=float(times[trigger]),trigger_reason="利益保護",
                       floor_points=float(floor[pos]))
        fill = np.searchsorted(times[ids],times[trigger]+1)
        if fill<len(ids):
            initial.update(exit_index=int(ids[fill]),status=5,reason="利益保護")
    return initial
