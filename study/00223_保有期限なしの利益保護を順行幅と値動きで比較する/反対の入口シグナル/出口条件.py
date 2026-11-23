"""保有中に出た反対側の199_02主シグナルで利益床と早期返済を比較する。"""
from pathlib import Path
import runpy
import numpy as np

STUDIES = Path(__file__).resolve().parents[2]
OLD = runpy.run_path(str(next(STUDIES.glob("00220_*/主比較/出口条件.py"))))
POLICIES = [f"R{i:02d}" for i in range(8)]


def prepare_signals(index: object, scene: dict, signals: dict) -> dict:
    """
    機能：入口判断時点までに公表された主シグナルの原行と方向を完成足の指標に結合する。
    引数：index（PriceIndex）は板、scene（dict）は場、signals（dict）は当時の判断・注文幅のみ。
    返り値：dict。正常な場内時計の主シグナルと確定足の判定。
    """
    result = OLD["prepare"](index,scene)
    valid = (signals["core"]!=0) & (np.where(signals["branches"]==0,signals["mw"],signals["fw"])>0)
    rows = signals["index"][valid]
    assert np.array_equal(index.times[rows],signals["time"][valid])
    assert np.array_equal(index.rows["source_line"][rows],signals["line"][valid])
    assert np.all(np.diff(rows)>=0)
    result.update(signal_rows=rows,signal_times=index.times[rows],signal_sides=signals["core"][valid])
    return result


def decide(code: str, context: dict, index: object, entry: int, side: int, width: float, horizon: str, term: dict) -> dict:
    """
    機能：建玉の途中で新しく成立した反対方向の主シグナルを、その原行以降でのみ保護に使う。
    引数：code・horizon（str）は方策IDと場末期限、context・term（dict）は特徴と観測終端、
    index（PriceIndex）は板、entry・side（int）は新規位置と側、width（float）は初期片幅。
    返り値：dict。返済原行・時刻の手掛かりと発動理由を含む。
    """
    code,_,suffix = code.partition("L")
    delay = int(suffix or 1)
    result = OLD["settle"]("P0",width,context,index,entry,side,width,horizon,term,delay)
    end = result["exit_index"]
    stop = min(end,term["touch_end"]) if end>=0 else term["touch_end"]
    lo,hi = np.searchsorted(index.normal,[entry+1,stop])
    ids = index.normal[lo:hi]
    if not len(ids):
        return result
    sign = 1 if side==0 else -1
    times = index.times[ids]
    price = index.rows["ask" if side==0 else "bid"][entry]
    move = sign*(index.rows["bid" if side==0 else "ask"][ids]-price)
    peak = np.maximum.accumulate(move)
    rows = context["signal_rows"]
    opposite = np.zeros(len(ids),bool)
    two = np.zeros(len(ids),bool)
    if len(rows):
        pos = rows.searchsorted(ids,side="right")-1
        last = pos.clip(0)
        older = (pos-1).clip(0)
        signs,alerts = context["signal_sides"],context["signal_times"]
        opposite = (pos>=0) & (rows[last]>entry) & (signs[last]==-sign) & (times-alerts[last]<=90)
        window = {"R10":120,"R11":300,"R12":300}.get(code,180)
        two = opposite & (pos>=1) & (rows[older]>entry) & (signs[older]==-sign) & (times-alerts[older]<=window)
        if code=="R12":
            third = (pos-2).clip(0)
            two &= (pos>=2) & (rows[third]>entry) & (signs[third]==-sign) & (times-alerts[third]<=window)
    # ----------------------------------------
    bar = context["bar"][ids]
    activation = {"R13":.40,"R14":.15}.get(code,.25)
    narrow = opposite & (move>=20) & (peak>=activation*width)
    if code in ("R00","R07"):
        narrow[:] = False
    elif code in ("R02","R06","R10","R11","R12","R13","R14","R15","R16"):
        narrow &= two
    elif code=="R03":
        narrow &= context["squeeze"][side,bar]
    elif code=="R04":
        narrow &= peak-move>=.20*width
    elif code=="R05":
        narrow = opposite & (move>=20)
    narrow = np.logical_or.accumulate(narrow)
    peak_after = np.maximum.accumulate(np.where(narrow,move,-np.inf))
    broad = peak>=.95*width
    gap = {"R05":.40,"R15":.40,"R16":.15}.get(code,.25)
    floors = np.maximum.accumulate(np.maximum(np.where(broad,np.maximum(20,peak-.80*width),-np.inf),
                         np.where(narrow,np.maximum(20,peak_after-gap*width),-np.inf)))
    active = np.isfinite(floors)
    crossed = (move<=floors) & np.r_[False,active[:-1]]
    adverse = two & (peak*100>1077) & (move*100<1077) & context["adverse"][side,bar] if code in ("R06","R07") else np.zeros(len(ids),bool)
    triggers = np.flatnonzero(crossed | adverse)
    at = int(triggers[0]) if triggers.size else len(ids)-1
    starts = np.flatnonzero(active[:at+1])
    if starts.size:
        arm = int(starts[0])
        result.update(activated=True,activation_index=int(ids[arm]),activation_time=float(times[arm]),floor_points=float(floors[at]))
    if triggers.size:
        reason = "反対シグナルによる早期損切" if adverse[at] and not crossed[at] else "利益保護"
        result.update(trigger_time=float(times[at]),trigger_index=int(ids[at]),trigger_reason=reason)
        fill = int(np.searchsorted(times,times[at]+delay))
        if fill<len(ids):
            result.update(exit_index=int(ids[fill]),status=5,reason=reason)
    return result
