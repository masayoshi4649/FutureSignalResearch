"""日経199_02の元の利確・損切と場末の時間を維持し、順行と完成足に応じて利益追尾を加える。"""
from pathlib import Path
import runpy

import numpy as np

STUDIES = Path(__file__).resolve().parents[2]
TECH = runpy.run_path(str(next(STUDIES.glob("00219_*/出口候補.py"))))
STATIC = runpy.run_path(str(next(STUDIES.glob("00221_*/元IFDの寄与/出口定義.py"))))
prepare = TECH["prepare"]
START = {"P03":.35, "P04":.55, "P05":.70, "P06":.85, "P07":.55, "P08":.70, "P09":.70,
         "P10":.85, "P11":.90, "P12":.70}
POLICIES = ["P01", "P02", *START]


def protection(code: str, context: dict, ids: np.ndarray, side: int, width: float,
               move: np.ndarray, times: np.ndarray) -> tuple:
    """
    機能：原板の順行と公表済みの1分足を用い、各原行で初めて知り得る起動状態と保護床を求める。
    引数：code（str）は条件名、context（dict）は公表済み特徴、ids・move・times（np.ndarray）は原行・実側順行幅・秒、
    side（int）は売買、width（float）は元のIFD片幅。
    返り値：tuple[np.ndarray, np.ndarray]。起動状態と、利益側へ正規化した非緩和の床。
    """
    peak = np.maximum.accumulate(move)
    arm = peak*100>1077 if code in ("P01","P02") else peak>=START[code]*width
    minimum = 0.0 if code=="P01" else 20.0
    gap = .60 if code in ("P11","P12") else .80
    floor = np.maximum(minimum,peak-gap*width)
    # ----------------------------------------
    if code=="P07":
        floor = np.maximum(20.0,np.where(peak>=.90*width,.40*width,np.where(peak>=.75*width,.20*width,0.0)))
    elif code in ("P08","P09","P10"):
        bars = context["bar"][ids]
        weak = context["squeeze"][side,bars]
        if code!="P08":
            weak = weak & context["broken"][side,bars]
        if code=="P10":
            arm = arm | ((peak>=.55*width) & (move>=.25*width) & weak)
        else:
            floor = np.maximum(floor,np.where(weak,peak-.45*width,minimum))
    elif code=="P11":
        pulled = np.logical_or.accumulate((peak>=.70*width) & (peak-move>=.15*width))
        arm = arm | (pulled & (peak-move<=.05*width))
    active = np.logical_or.accumulate(arm)
    return active,np.maximum.accumulate(np.where(active,floor,-np.inf))


def settle(code: str, context: dict, index: object, entry: int, side: int,
           width: float, horizon: str, term: dict, protection_rule: object=protection) -> dict:
    """
    機能：元の±1Rと場末返済を優先し、追尾がそれより前に実行された場合の原行を返す。
    引数：code・horizon（str）は出口IDと場末期限、context・term（dict）は完成足情報と観測終端、
    index（PriceIndex）は気配索引、entry・side（int）は新規原行と向き、width（float）は片幅、
    protection_rule（callable）は各原行の当時情報を起動と床へ変換する規則。
    返り値：dict。価格注文・実返済・観測不足と、起動・発動時の価格時計および保護床。
    """
    assert horizon=="SESSION"
    name,separator,delay = code.partition("L")
    seconds = int(delay) if separator else 1
    assert seconds>=1
    result = STATIC["decide"]("D00",context,index,entry,side,width,horizon,term)
    result.update(activated=False,activation_time=None,activation_index=-1,trigger_time=None,
                  trigger_index=-1,trigger_reason=None,floor_points=None)
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
    active,floor = protection_rule(name,context,ids,side,width,move,times)
    first = TECH["first_true"](active)
    if first<0:
        return result
    # ----------------------------------------
    result.update(activated=True,activation_index=int(ids[first]),activation_time=float(times[first]),
                  floor_points=float(floor[-1]))
    trigger = TECH["first_true"]((move<=floor) & np.r_[False,active[:-1]])
    if trigger>=0:
        result.update(trigger_index=int(ids[trigger]),trigger_time=float(times[trigger]),
                      trigger_reason="順行後の利益保護",floor_points=float(floor[trigger]))
        fill = int(np.searchsorted(times,times[trigger]+seconds))
        if fill<len(ids):
            result.update(exit_index=int(ids[fill]),status=5,reason="順行後の利益保護")
    return result


decide = settle
