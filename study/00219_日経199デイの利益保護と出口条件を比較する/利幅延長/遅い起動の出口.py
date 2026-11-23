"""元利確までのゆらぎを許す、遅めの建値保護と利幅延長を組み合わせる。"""
from pathlib import Path
import runpy

import numpy as np

PREVIOUS = runpy.run_path(str(Path(__file__).resolve().with_name("出口定義.py")))
prepare = PREVIOUS["prepare"]
POLICIES = ("L08", "L09", "L10", "L11", "L12", "L13", "L14")
SETTINGS = {
    "L08": ("L00", 1.00, .85, .90, .25),
    "L09": ("L00", 1.00, .95, .90, .25),
    "L10": ("L03", 1.50, .85, .90, .25),
    "L11": ("L03", 1.25, .85, .90, .25),
    "L12": ("L03", 1.50, .95, .95, .20),
    "L13": ("L04", 1.50, .95, .95, .20),
    "L14": ("L06", 1.50, .95, .95, .20),
}


def decide(policy: str, ctx: dict, index: object, entry: int, side: int,
           width: float, horizon: str, term: dict) -> dict:
    """
    機能：元幅付近で保護を設定し、延長局面は元の利確価格を通過した後に厚く利益を守る。
    引数：policy（str）は案、ctx・term（dict）は場特徴と決済の終端、index（PriceIndex）は原行索引、
        entry・side（int）は買売と取得原行、width（float）は元幅、horizon（str）は保有期限。
    返り値：dict。採用決済原行・状態・実際の目標倍率・発動原行の診断を含む。
    """
    gate, extension, arm, lock, distance = SETTINGS[policy]
    sign = 1 if side == 0 else -1
    multiple = extension if PREVIOUS["target"](gate,ctx,index,entry,sign)>1 else 1.0
    price = float(index.rows["ask" if side == 0 else "bid"][entry])
    mark = index.rows["bid" if side == 0 else "ask"]
    cap = term["touch_end"]
    lower, upper = (price-width, price+multiple*width) if side==0 else (price-multiple*width, price+width)
    hit = index.first_outside(entry+1, cap, lower, upper, side)
    end, status = int(term["exit"]), int(term["status"])
    if hit >= 0:
        end = int(hit)
        status = 1 if sign*(mark[end]-price)>0 else 2
    result = {"exit_index": end, "status": status, "reason": PREVIOUS["REASON"][status],
              "activated": False, "activation_index": -1, "activation_time": None,
              "trigger_index": -1, "trigger_time": None, "floor_points": None,
              "target_multiple": multiple, "protection_trigger_time": None, "protection_trigger_line": None,
              "protection_floor": None, "protection_trigger_points": None}
    # ----------------------------------------
    a,b = np.searchsorted(index.normal, [entry+1, min(cap,end) if end>=0 else cap])
    rows = index.normal[a:b]
    if not len(rows):
        return result
    points = sign*(mark[rows]-price)
    peak = np.maximum.accumulate(points)
    floor = np.maximum(lock*width,peak-distance*width)
    floor[peak<width] = 20
    protection = (peak>=arm*width) & (points<=floor)
    alarm = np.zeros(len(rows), dtype=bool)
    if policy == "L14" and multiple>1:
        reached = np.flatnonzero(peak >= width)
        if len(reached):
            first_time = index.times[rows[reached[0]]]
            alarm = (index.times[rows] >= first_time+180) & (peak < 1.10*width)
    alerts = np.flatnonzero(protection | alarm)
    starts = np.flatnonzero(peak>=arm*width)
    if len(starts):
        first = int(rows[starts[0]])
        result.update(activated=True, activation_index=first, activation_time=float(index.times[first]),
                      floor_points=float(floor[alerts[0] if len(alerts) else -1]))
    if len(alerts):
        i = int(alerts[0])
        signal = int(rows[i])
        time = float(index.times[signal])
        result.update(protection_trigger_time=time, protection_trigger_line=int(index.rows["source_line"][signal]),
                      protection_trigger_points=float(points[i]), protection_floor=float(floor[i]),
                      trigger_index=signal, trigger_time=time)
        fill = index.first_normal(time+1, signal)
        if 0 <= fill < cap and (end < 0 or fill < end):
            result.update(exit_index=int(fill), status=5, reason="遅い段階保護" if protection[i] else "延長後の停滞")
    return result
