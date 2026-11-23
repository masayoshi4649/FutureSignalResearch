"""M04の利確を共通にして、早期の広い追尾と期限が迫ったときの可変追尾を分解する。"""
from pathlib import Path
import runpy

import numpy as np

MATURE = runpy.run_path(str(Path(__file__).with_name("成熟時の出口.py")))
prepare = MATURE["prepare"]
POLICIES = {
    "M27": "期限前保護のみ", "M28": "0.95Rで追尾・残り10分の保護",
    "M29": "0.95Rで追尾・残り8分の保護", "M30": "0.95Rで追尾・残り12分の保護",
    "M31": "期限前の0.35Rから保護", "M32": "期限前の0.55Rから保護",
    "M33": "利確指値幅の95%で追尾", "M34": "場末期限と分単位期限で起動を切替",
    "M35": "0.95Rで追尾・技術収縮なし",
}


def decide(code: str, context: dict, index, entry: int, side: int, width: float,
           horizon: str, term: dict) -> dict:
    """
    機能：M04の当初注文が生きている間に、必須追尾が先に成立した建玉を確定する。
    引数：code（str）・context（dict）は候補と形成済み場情報、index（PriceIndex）は原板、
    entry・side（int）は新規原行と側、width（float）は元IFD幅、horizon（str）・term（dict）は期限と終端。
    返り値：dict。M04に共通する価格条件または追尾の実決済行・事由・起動等。
    """
    base = MATURE["decide"]("M04", context, index, entry, side, width, horizon, term)
    end = base["exit_index"]
    stop = min(end, term["touch_end"]) if end >= 0 else term["touch_end"]
    normal = index.normal
    ids = normal[np.searchsorted(normal, entry+1):np.searchsorted(normal, stop)]
    if not len(ids):
        return base
    time = index.times[ids]
    opened = float(index.times[entry])
    deadline = context["deadline"] if horizon == "SESSION" else min(context["deadline"], opened+int(horizon[1:])*60)
    early = .95
    if code == "M27":
        early = np.inf
    elif code == "M33" and opened-context["start"] >= 225*60:
        early *= .90
    elif code == "M34" and horizon != "SESSION":
        early = .85
    window = {"M29": 8, "M30": 12}.get(code, 10)
    late = deadline-time <= window*60
    late_trigger = {"M31": .35, "M32": .55}.get(code, .45)
    if side == 0:
        move = index.rows["bid"][ids]-index.rows["ask"][entry]
    else:
        move = index.rows["bid"][entry]-index.rows["ask"][ids]
    peak = np.maximum.accumulate(np.maximum(0.0, move))
    active = np.logical_or.accumulate((move >= early*width) | (late & (move >= late_trigger*width)))
    floor = np.maximum(20.0, peak-.80*width)
    if code != "M35":
        narrow = late & context["squeeze"][side, context["bar"][ids]]
        floor = np.maximum(floor, np.where(narrow, peak-.35*width, 0.0))
    floor = np.maximum.accumulate(np.where(active, floor, -np.inf))
    # ----------------------------------------
    first = MATURE["FIRST"]["first_true"]
    armed = first(active)
    if armed < 0:
        return base
    base.update(activated=True, activation_index=int(ids[armed]), activation_time=float(time[armed]),
                floor_points=float(floor[-1]))
    trigger = first((move <= floor) & np.r_[False, active[:-1]])
    if trigger >= 0:
        base.update(trigger_index=int(ids[trigger]), trigger_time=float(time[trigger]),
                    trigger_reason="利益保護", floor_points=float(floor[trigger]))
        fill = int(np.searchsorted(time, time[trigger]+1))
        if fill < len(ids):
            base.update(exit_index=int(ids[fill]), status=5, reason="利益保護", peak_points=float(peak[fill]))
    return base
