"""M04の時間境界・利確幅の近傍と、一定順行からの必須追尾を再生する。"""
from pathlib import Path
import runpy

import numpy as np

MATURE = runpy.run_path(str(Path(__file__).with_name("成熟時の出口.py")))
prepare = MATURE["prepare"]
POLICIES = {
    "M17": "12時30分以後0.85R", "M18": "12時30分以後0.95R",
    "M19": "12時以後0.90R", "M20": "13時以後0.90R",
    "M21": "午後短縮・0.85Rで0.80R幅追尾", "M22": "午後短縮・0.90Rで0.80R幅追尾",
    "M23": "午後短縮・0.75Rで0.70R幅追尾", "M24": "午後短縮・0.85Rと停滞収縮",
    "M25": "午後短縮・0.90Rと期限前の起動・収縮", "M26": "午後短縮・0.80Rと期限前逆行",
}
LOCK = {"M21": (.85,.80), "M22": (.90,.80), "M23": (.75,.70),
        "M24": (.85,.80), "M25": (.90,.80), "M26": (.80,.75)}


def decide(code: str, context: dict, index, entry: int, side: int, width: float,
           horizon: str, term: dict) -> dict:
    """
    機能：建てた時刻に合わせた静的IFDと、順行後に発生する非緩和追尾を比較する。
    引数：code（str）はID、context（dict）は完成足の場内特徴、index（PriceIndex）は原行。
    entry・side（int）は取得行・方向、width（float）は元IFD幅、horizon（str）とterm（dict）は期限と終端。
    返り値：dict。静的決済／動的決済の原行・理由と、保護の起動・発動原行・時刻・床。
    """
    sign = 1 if side == 0 else -1
    opened = float(index.times[entry])
    boundary = {"M19": 195, "M20": 255}.get(code, 225)
    afternoon = opened-context["start"] >= boundary*60
    ratio = {"M17": .85, "M18": .95}.get(code, .90) if afternoon else 1.0
    price = float(index.rows["ask" if side == 0 else "bid"][entry])
    mark = index.rows["bid" if side == 0 else "ask"]
    lower, upper = (price-width, price+width*ratio) if side == 0 else (price-width*ratio, price+width)
    hit = index.first_outside(entry+1, term["touch_end"], lower, upper, side)
    end = hit if hit >= 0 else term["exit"]
    status = (1 if sign*(mark[hit]-price) > 0 else 2) if hit >= 0 else term["status"]
    reason = {1: "静的利確", 2: "静的損切", 3: "期限決済", 4: "場末決済"}.get(status, "決済不明")
    result = {"exit_index": int(end), "status": int(status), "reason": reason, "trigger_index": -1,
              "trigger_time": None, "trigger_reason": None, "floor_points": None, "peak_points": 0.0,
              "activated": False, "activation_index": -1, "activation_time": None}
    # ----------------------------------------
    stop = min(end+1, term["touch_end"]) if end >= 0 else term["touch_end"]
    normal = index.normal
    ids = normal[np.searchsorted(normal, entry+1):np.searchsorted(normal, stop)]
    if not len(ids):
        return result
    move = sign*(mark[ids]-price)
    peak = np.maximum.accumulate(np.maximum(move,0.0))
    result["peak_points"] = float(peak[-1])
    if code not in LOCK:
        return result
    times, bars = index.times[ids], context["bar"][ids]
    deadline = context["deadline"]
    if horizon != "SESSION":
        deadline = min(deadline, opened+int(horizon[1:])*60)
    activation, gap = LOCK[code]
    arm = move >= width*activation
    floor = np.maximum(20.0, peak-gap*width)
    if code == "M24":
        record = np.maximum.accumulate(np.where(np.diff(np.r_[0.0,peak]) > 0, times, opened))
        tighten = (times-record >= 300) & context["squeeze"][side, bars]
        floor = np.maximum(floor, np.where(tighten, peak-.35*width, 0.0))
    if code == "M25":
        late = deadline-times <= 600
        arm |= late & (move >= .45*width)
        tighten = late & context["squeeze"][side, bars]
        floor = np.maximum(floor, np.where(tighten, peak-.35*width, 0.0))
    if code == "M26" and afternoon:
        tighten = (deadline-times <= 900) & context["adverse"][side, bars]
        floor = np.maximum(floor, np.where(tighten, peak-.30*width, 0.0))
    # ----------------------------------------
    active = np.logical_or.accumulate(arm)
    floor = np.maximum.accumulate(np.where(active, floor, -np.inf))
    first = MATURE["FIRST"]["first_true"]
    observed = len(ids)-1-int(end >= 0 and ids[-1] == end)
    trigger = first((move <= floor) & np.r_[False, active[:-1]])
    if 0 <= trigger <= observed:
        result.update(trigger_index=int(ids[trigger]), trigger_time=float(times[trigger]), trigger_reason="利益保護")
        fill = int(np.searchsorted(times, times[trigger]+1))
        if fill <= observed:
            result.update(exit_index=int(ids[fill]), status=5, reason="利益保護", peak_points=float(peak[fill]))
        observed = trigger
    armed = first(active[:observed+1])
    if armed >= 0:
        result.update(activated=True, activation_index=int(ids[armed]), activation_time=float(times[armed]),
                      floor_points=float(floor[observed]))
    return result
