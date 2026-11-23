"""完成足の高安・真の値幅で初期損切りを決め、利確の上限を独立に変える。"""
from pathlib import Path
import runpy

import numpy as np

OLD = next(Path(__file__).resolve().parents[2].glob("00219_*"))
MATURE = runpy.run_path(str(OLD/"成熟時の出口.py"))
POLICIES = [f"S{stop}{profit}" for stop in range(5) for profit in range(4)]


def prepare(index: object, scene: dict) -> dict:
    """
    機能：新規原行が含まれる分より前に完成した1分足12本の安値・高値と効率比を用意する。
    引数：index（PriceIndex）は気配索引、scene（dict）は場の開始・終了。
    返り値：dict。取得時の構造水準と、219から継承したATR・完成足の失速と収縮。
    """
    ctx = MATURE["prepare"](index, scene)
    start, cut = scene["start"], scene["end"]-900
    ids = index.normal[(index.times[index.normal]>=start) & (index.times[index.normal]<cut)]
    count = len(ctx["atr"])
    minimum, maximum, close, low12, high12, er12 = np.full((6,count), np.nan)
    if len(ids):
        minutes = ctx["bar"][ids]
        first = np.r_[0,np.flatnonzero(np.diff(minutes))+1]
        active = minutes[first]
        midpoint = .5*(index.rows["bid"][ids]+index.rows["ask"][ids])
        minimum[active] = np.minimum.reduceat(midpoint,first)
        maximum[active] = np.maximum.reduceat(midpoint,first)
        close[active] = midpoint[np.r_[first[1:]-1,len(ids)-1]]
    for i in range(12,count):
        low12[i] = minimum[i-12:i].min()
        high12[i] = maximum[i-12:i].max()
        if i>=13:
            history = close[i-13:i]
            if np.isfinite(history).all():
                length = np.abs(np.diff(history)).sum()
                er12[i] = abs(history[-1]-history[0])/length if length else 0.0
    ctx.update(low12=low12,high12=high12,er12=er12)
    return ctx


def stop_distance(group: int, ctx: dict, minute: int, side: int, price: float, width: float) -> tuple:
    """
    機能：当時の気配と完成足から、取得時に固定する損切りの距離と根拠を計算する。
    引数：group・minute・side（int）は損切り群、取得分と側、ctx（dict）は場情報、price・width（float）は建値・元幅。
    返り値：tuple。非負の初期距離（float）、参照した原値（floatまたはNone）、適用理由（str）。
    """
    if group==0:
        return width,None,"元幅"
    atr = ctx["atr"][minute]
    if group==3 and not (minute>=165 and ctx["er12"][minute]<=.35):
        return width,None,"往復条件外"
    if group==4:
        distance = 3*atr
        reason = "3ATR"
    else:
        distance = price-ctx["low12"][minute] if side==0 else ctx["high12"][minute]-price
        distance += .5*atr
        reason = "12分高安と半ATR"
    if not np.isfinite(distance):
        return width,None,"履歴不足"
    lower,upper = (.60,1.) if group==1 else (.85,1.10)
    return float(np.clip(distance,lower*width,upper*width)),float(distance),reason


def decide(code: str, ctx: dict, index: object, entry: int, side: int, width: float, horizon: str,
           term: dict, stop_model=stop_distance) -> dict:
    """
    機能：固定した損切り、利確指値、動的追尾と期限の時系列順を実側原行で再生する。
    引数：code・horizon（str）は候補・期限、ctx・term（dict）は場条件・共通終端、index（PriceIndex）は板。
        entry・side（int）は新規行・方向、width（float）は元IFD片幅、stop_model（callable）は初期距離の算式。
    返り値：dict。決済の原行、理由、当初の逆指値距離と水準、利益保護の発動・約定の時計。
    """
    group, mode = int(code[1]), int(code[2])
    minute = int(ctx["bar"][entry])
    opened = float(index.times[entry])
    price = float(index.rows["ask" if side==0 else "bid"][entry])
    sign = 1 if side==0 else -1
    mark = index.rows["bid" if side==0 else "ask"]
    distance, raw, why = stop_model(group,ctx,minute,side,price,width)
    target = width if mode==0 or minute<225 else .90*width
    ceiling = target if mode<2 else np.inf
    lower,upper = (price-distance,price+ceiling) if side==0 else (price-ceiling,price+distance)
    cap = term["touch_end"]
    hit = index.first_outside(entry+1,cap,lower,upper,side)
    end = hit if hit>=0 else term["exit"]
    status = (1 if sign*(mark[hit]-price)>0 else 2) if hit>=0 else term["status"]
    reason = {1:"静的利確",2:"静的損切",3:"期限決済",4:"場末決済"}.get(status,"決済不明")
    result = dict(exit_index=int(end),status=int(status),reason=reason,stop_points=distance,
                  stop_level=price-sign*distance,structural_distance=raw,stop_basis=why,
                  target_points=target if mode<2 else None,activated=False,activation_index=-1,
                  activation_time=None,trigger_index=-1,trigger_time=None,floor_points=None)
    if mode==0:
        return result
    # ----------------------------------------
    left,right = np.searchsorted(index.normal,[entry+1,min(end,cap) if end>=0 else cap])
    rows = index.normal[left:right]
    if not len(rows):
        return result
    time = index.times[rows]
    move = sign*(mark[rows]-price)
    peak = np.maximum.accumulate(np.maximum(0.0,move))
    deadline = ctx["deadline"] if horizon=="SESSION" else min(ctx["deadline"],opened+int(horizon[1:])*60)
    late = deadline-time <= 600
    near = move >= (.95 if horizon=="SESSION" else .85)*width
    active = np.logical_or.accumulate(near | (late & (move>=.45*width)) | ((mode==3) & (move>=target)))
    floor = np.maximum(20.0,peak-.80*width)
    shrink = late & ctx["squeeze"][side,ctx["bar"][rows]]
    floor = np.maximum(floor,np.where(shrink,peak-.35*width,0.0))
    if mode==3:
        floor = np.maximum(floor,np.where(peak>=target,np.maximum(.80*target,peak-.30*width),0.0))
    floor = np.maximum.accumulate(np.where(active,floor,-np.inf))
    if not active.any():
        return result
    armed = int(np.argmax(active))
    result.update(activated=True,activation_index=int(rows[armed]),activation_time=float(time[armed]),
                  floor_points=float(floor[-1]))
    triggered = (move<=floor) & np.r_[False,active[:-1]]
    if triggered.any():
        signal = int(np.argmax(triggered))
        result.update(trigger_index=int(rows[signal]),trigger_time=float(time[signal]),
                      floor_points=float(floor[signal]))
        fill = int(np.searchsorted(time,time[signal]+1))
        if fill<len(rows):
            result.update(exit_index=int(rows[fill]),status=5,reason="利益保護")
    return result
