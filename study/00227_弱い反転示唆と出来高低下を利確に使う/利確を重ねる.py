"""RCの注文を残しながら、当時観測できた追加条件でのみ決済を早める。"""
from pathlib import Path
import runpy

import numpy as np

HERE = Path(__file__).resolve().parent
RC = runpy.run_path(str(next(HERE.parent.glob("00223_*/反対の入口シグナル/出口条件.py"))))


def overlay(context: dict, index: object, entry: int, side: int, width: float, horizon: str, term: dict,
            signal: object, action: str, min_peak: float=.25, trail_width: float=.15, delay: int=1) -> dict:
    """
    機能：RCの実決済に先行した追加の利確注文だけを、正常な清算側気配で評価する。
    引数：context・term（dict）は当時特徴と観測限界、index（PriceIndex）は原板、entry・side（int）は
    取得行と側、width（float）は1R、horizon（str）は場末まで、signal（callable）は行ごとの追加条件、
    action（str）は即時・追尾、min_peak・trail_width（float）はR倍率、delay（int）は執行までの最短秒。
    返り値：dict。追加の成立・発動・約定の有無、実現した出口、追尾記録。
    """
    delay = context.get("執行秒",delay)
    assert action in ("即時","追尾") and delay>=1
    base = RC["decide"]("R02" if delay==1 else f"R02L{delay}",context,index,entry,side,width,horizon,term)
    out = dict(base,extra_signal=-1,extra_signal_time=None,extra_trigger=-1,extra_trigger_time=None,extra_fill=False)
    end = base["exit_index"]
    limit = min(end,term["touch_end"]) if end>=0 else term["touch_end"]
    first,last = index.normal.searchsorted([entry+1,limit])
    ids = index.normal[first:last]
    if not len(ids):
        return out
    # 決済要求を送った後には追加の要求を出さない。未約定の元価格注文は全期間で優先する。
    base_trigger = base["trigger_index"]
    count = ids.searchsorted(base_trigger) if base_trigger>=0 else len(ids)
    active_ids = ids[:count]
    if not len(active_ids):
        return out
    price = index.rows["ask" if side==0 else "bid"][entry]
    mark = index.rows["bid" if side==0 else "ask"][active_ids]
    move = (mark-price)*(1 if side==0 else -1)
    peak = np.maximum.accumulate(move)
    flags = signal(context,index,active_ids,entry,side,width,move,peak)
    eligible = np.flatnonzero(flags & (peak>=min_peak*width) & (move>=20))
    if not len(eligible):
        return out
    start = int(eligible[0])
    added = int(active_ids[start])
    out.update(extra_signal=added,extra_signal_time=float(index.times[added]))
    floor = None
    if action=="即時":
        trigger = start
    else:
        if base["activation_index"]<0 or added<base["activation_index"]:
            out.update(activated=True,activation_index=added,activation_time=float(index.times[added]))
        path = move[start:]
        floors = np.maximum(20,np.maximum.accumulate(path)-trail_width*width)
        hits = np.flatnonzero(path[1:]<=floors[1:])
        if not len(hits):
            return out
        trigger = start+1+int(hits[0])
        floor = float(floors[trigger-start])
    # ----------------------------------------
    fired = int(active_ids[trigger])
    out.update(extra_trigger=fired,extra_trigger_time=float(index.times[fired]))
    pos = np.searchsorted(index.times[ids],index.times[fired]+delay)
    if pos>=len(ids):
        return out
    fill = int(ids[pos])
    arm = out["activation_index"]
    if arm>fired:
        arm = -1
    reason = "追加示唆で利確要求" if action=="即時" else "追加示唆からの追尾返済"
    out.update(exit_index=fill,status=5,reason=reason,trigger_reason=reason,trigger_index=fired,
               trigger_time=float(index.times[fired]),floor_points=floor,activated=arm>=0,activation_index=arm,
               activation_time=float(index.times[arm]) if arm>=0 else None,extra_fill=True)
    return out
