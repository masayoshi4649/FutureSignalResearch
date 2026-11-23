"""初期損切4案と利確10案を同じ199_02入口・返済時計で比較する。"""
from pathlib import Path
import runpy

import numpy as np

OLD = next(Path(__file__).resolve().parents[2].glob("00219_*"))
TECH = runpy.run_path(str(OLD/"出口候補.py"))
ER = runpy.run_path(str(OLD/"逆行時の出口.py"))
POLICIES = [f"S{s}P{p}" for s in range(4) for p in range(10)]
REASONS = {1: "静的利確", 2: "静的損切", 3: "期限決済", 4: "場末決済"}


def prepare(index: object, scene: dict) -> dict:
    """
    機能：各板原行で利用できた完成足の失速・収縮と12分効率、元の返済要求時計を準備する。
    引数：index（PriceIndex）は板索引、scene（dict）は開始・終了定義。
    返り値：dict。219と同じ時系列の情報。
    """
    context = TECH["prepare"](index,scene)
    context["er"] = ER["prepare"](index,scene)["er"]
    context["deadline"] = scene["end"]-960
    return context


def stop_size(stop_id: str, context: dict, opened: float, width: float) -> float:
    """
    機能：新規時に確定した情報で初期損切り幅を固定する。
    引数：stop_id（str）はS番号、context（dict）は場情報、opened・width（float）は取得秒と元の片幅pt。
    返り値：float。建値から逆方向にとる正の価格差pt。
    """
    minute = int((opened-context["start"])//60)
    if stop_id=="S3":
        wider = minute>=165 and abs(context["er"][minute])<=.35
        return width*(1.10 if wider else 1.0)
    return width*{"S0":.75,"S1":1.0,"S2":1.10}[stop_id]


def settle(profit_id: str, stop_points: float, context: dict, index: object, entry: int, side: int,
           width: float, horizon: str, term: dict, delay_seconds: float = 1.0) -> dict:
    """
    機能：取得時に与えた損切り幅と利確方法を独立に指定し、実側の板原行で返済を決める。
    引数：profit_id（str）はP番号、stop_points（float）は初期逆行幅pt、context（dict）は完成足情報、
    index（PriceIndex）は原板、entry・side（int）は新規行・側、width（float）は元のR。
    horizon（str）・term（dict）は元期限・打切り。delay_seconds（float）は保護要求後の最短秒。
    返り値：dict。返済原行・起動・床・初期の利確/損切幅と理由。
    """
    assert stop_points>0 and width>0 and delay_seconds>=1
    opened = float(index.times[entry])
    afternoon = opened-context["start"]>=225*60
    targets = {"P0":1.0,"P1":.90 if afternoon else 1.0,"P2":1.0,
               "P3":.90 if afternoon else 1.0,"P6":1.5,"P7":1.0}
    target_points = width*targets[profit_id] if profit_id in targets else None
    price = float(index.rows["ask" if side==0 else "bid"][entry])
    sign = 1 if side==0 else -1
    mark = index.rows["bid" if side==0 else "ask"]
    target = target_points if target_points is not None else np.inf
    lo,hi = (price-stop_points,price+target) if side==0 else (price-target,price+stop_points)
    hit = index.first_outside(entry+1,term["touch_end"],lo,hi,side)
    end,status = int(term["exit"]),int(term["status"])
    if hit>=0:
        end = int(hit)
        status = 1 if sign*(mark[end]-price)>0 else 2
    result = dict(exit_index=end,status=status,reason=REASONS.get(status,"決済不明"),activated=False,
                  activation_index=-1,activation_time=None,trigger_index=-1,trigger_time=None,
                  trigger_reason=None,floor_points=None,initial_stop_points=float(stop_points),
                  target_points=target_points,initial_stop_multiple=float(stop_points/width))
    if profit_id in ("P0","P1","P9"):
        return result
    # ----------------------------------------
    stop = min(end,term["touch_end"]) if end>=0 else term["touch_end"]
    left,right = np.searchsorted(index.normal,[entry+1,stop])
    ids = index.normal[left:right]
    if not len(ids):
        return result
    times = index.times[ids]
    move = sign*(mark[ids]-price)
    peak = np.maximum.accumulate(move)
    if profit_id in ("P7","P8"):
        arm = move>=(.95 if horizon=="SESSION" else .90)*width
        floor = np.maximum(20.0,peak-.70*width)
    else:
        assert profit_id in ("P2","P3","P4","P5","P6")
        deadline = context["deadline"]
        if horizon!="SESSION":
            deadline = min(deadline,opened+int(horizon[1:])*60)
        late = deadline-times<=600
        arm = (move>=(.95 if horizon=="SESSION" else .85)*width) | (late & (move>=.45*width))
        floor = np.maximum(20.0,peak-.80*width)
        squeeze = late & context["squeeze"][side,context["bar"][ids]]
        floor = np.maximum(floor,np.where(squeeze,peak-.35*width,0.0))
        if profit_id in ("P5","P6"):
            passed = peak>=width
            floor[passed] = np.maximum(floor[passed],np.maximum(.80*width,peak[passed]-.30*width))
    # ----------------------------------------
    active = np.logical_or.accumulate(arm)
    starts = TECH["first_true"](active)
    if starts<0:
        return result
    floor = np.maximum.accumulate(np.where(active,floor,-np.inf))
    result.update(activated=True,activation_index=int(ids[starts]),activation_time=float(times[starts]),
                  floor_points=float(floor[-1]))
    trigger = TECH["first_true"]((move<=floor) & np.r_[False,active[:-1]])
    if trigger>=0:
        result.update(trigger_index=int(ids[trigger]),trigger_time=float(times[trigger]),
                      trigger_reason="利益保護",floor_points=float(floor[trigger]))
        fill = int(np.searchsorted(times,times[trigger]+delay_seconds))
        if fill<len(ids):
            result.update(exit_index=int(ids[fill]),status=5,reason="利益保護")
    return result


def decide(code: str, context: dict, index: object, entry: int, side: int,
           width: float, horizon: str, term: dict) -> dict:
    """
    機能：S番号の損切り幅を決め、P番号の利確で取得から返済まで再生する。
    引数：code（str）は組合せ、context・term（dict）は当時特徴・期限、index（PriceIndex）は板、
    entry・side（int）は新規原行と側、width（float）・horizon（str）は元幅と元の保有期限。
    返り値：dict。原行番号と損切り幅、保護と返済情報。
    """
    points = stop_size(code[:2],context,float(index.times[entry]),width)
    return settle(code[2:],points,context,index,entry,side,width,horizon,term)
