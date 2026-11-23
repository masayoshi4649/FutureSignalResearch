"""場末までの残り時間と直近の真値幅で、広い追尾に利益保護を加える。"""
from pathlib import Path
import runpy
import numpy as np

STUDIES = Path(__file__).resolve().parents[2]
OLD = runpy.run_path(str(next(STUDIES.glob("00220_*/主比較/出口条件.py"))))
VOL = runpy.run_path(str(next(STUDIES.glob("00219_*/成熟時の出口.py"))))
prepare = VOL["prepare"]
POLICIES = [f"V{i:02d}" for i in range(9)]


def decide(code: str, context: dict, index: object, entry: int, side: int, width: float, horizon: str, term: dict) -> dict:
    """
    機能：場末と値幅から利確までの余地を見積もり、初期の両注文に広幅・狭幅の利益保護を追加する。
    引数：code・horizon（str）は出口ID・場末期限、context・term（dict）は完成足・再生終端、
    index（PriceIndex）は板、entry・side（int）は新規原行・向き、width（float）は1Rのポイント数。
    返り値：dict。実際の返済原行、保護の時刻・床、初期価格幅。
    """
    code,_,suffix = code.partition("L")
    delay = int(suffix or 1)
    result = OLD["settle"]("P2" if code=="V01" else "P0",width,context,index,entry,side,width,horizon,term,delay)
    if code in ("V00","V01"):
        return result
    end = result["exit_index"]
    bound = min(end,term["touch_end"]) if end>=0 else term["touch_end"]
    left,right = np.searchsorted(index.normal,[entry+1,bound])
    ids = index.normal[left:right]
    if not len(ids):
        return result
    # ----------------------------------------
    times = index.times[ids]
    bar = context["bar"][ids]
    price = index.rows["ask" if side==0 else "bid"][entry]
    move = (index.rows["bid" if side==0 else "ask"][ids]-price)*(1 if side==0 else -1)
    peak = np.maximum.accumulate(move)
    remaining = np.maximum(0,context["deadline"]-times)/60
    reach = context["atr"][bar]*np.sqrt(remaining)*(2 if code=="V07" else 1)
    signal = move>=(.50 if code=="V06" else .30)*width
    if code!="V04":
        signal &= width-move>reach
    if code!="V02":
        signal &= context["squeeze"][side,bar]
    if code=="V05":
        signal &= remaining<=60
    if code=="V08" and width!=350:
        signal[:] = False
    broad = peak>=.95*width
    narrow = np.logical_or.accumulate(signal)
    tight_peak = np.maximum.accumulate(np.where(narrow,move,-np.inf))
    floors = np.maximum.accumulate(np.maximum(np.where(broad,np.maximum(20,peak-.80*width),-np.inf),
                                               np.where(narrow,np.maximum(20,tight_peak-.35*width),-np.inf)))
    active = np.isfinite(floors)
    if not active.any():
        return result
    start = int(np.flatnonzero(active)[0])
    result.update(activated=True,activation_time=float(times[start]),activation_index=int(ids[start]),floor_points=float(floors[-1]))
    triggers = np.flatnonzero((move<=floors) & np.r_[False,active[:-1]])
    if triggers.size:
        trigger = int(triggers[0])
        result.update(trigger_time=float(times[trigger]),trigger_index=int(ids[trigger]),
                      trigger_reason="残存値幅による利益保護",floor_points=float(floors[trigger]))
        fill = int(np.searchsorted(times,times[trigger]+delay))
        if fill<len(ids):
            result.update(exit_index=int(ids[fill]),status=5,reason="残存値幅による利益保護")
    return result
