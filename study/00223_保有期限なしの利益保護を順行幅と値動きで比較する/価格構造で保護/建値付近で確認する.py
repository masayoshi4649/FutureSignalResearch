"""一度利益が乗った後、建値近くに戻るときだけ複数足の逆行を確認して返済する。"""
from pathlib import Path
import runpy

import numpy as np


FIRST = runpy.run_path(str(Path(__file__).with_name("出口条件.py")))
prepare = FIRST["prepare"]
POLICIES = [f"S{i}" for i in range(20,27)]


def decide(code: str, context: dict, index: object, entry: int, side: int, width: float,
           horizon: str, term: dict, delay_seconds: int=1) -> dict:
    """
    機能：広い追尾と静的な両注文に、建値へ戻るときの構造崩れによる実側返済を追加する。
    引数：code・horizon（str）は候補と期限、context・term（dict）は当時の技術と観測終端、
    index（PriceIndex）は原板、entry・side（int）は新規原行と側、width（float）は片幅、delay_seconds（int）は執行遅延。
    返り値：dict。先に実行可能だった返済と、その時点までの追尾起動・発動履歴。
    """
    result = FIRST["decide"]("S00",context,index,entry,side,width,horizon,term,delay_seconds)
    end = result["exit_index"]
    stop = min(end,term["touch_end"]) if end>=0 else term["touch_end"]
    left,right = np.searchsorted(index.normal,[entry+1,stop])
    ids = index.normal[left:right]
    if not len(ids):
        return result
    sign = 1 if side==0 else -1
    price = index.rows["ask" if side==0 else "bid"][entry]
    move = sign*(index.rows["bid" if side==0 else "ask"][ids]-price)
    peak = np.maximum.accumulate(move)
    qualify = {"S24":.25,"S25":.65}.get(code,.45)
    low,high = (-.35,-.10) if code=="S23" else (-.15,.08)
    broken,retest,either = FIRST["patterns"](context,index,ids,entry,side)
    tech = {"S20":broken,"S21":retest,"S26":True}.get(code,either)
    trigger = FIRST["TECH"]["first_true"]((peak>=qualify*width) & (move>=low*width) & (move<=high*width) & tech)
    if trigger<0:
        return result
    times = index.times[ids]
    fill = int(np.searchsorted(times,times[trigger]+delay_seconds))
    if fill>=len(ids):
        return result
    # ----------------------------------------
    active = FIRST["TECH"]["first_true"](peak[:trigger+1]>=.90*width)
    result.update(activated=active>=0,activation_index=int(ids[active]) if active>=0 else -1,
                  activation_time=float(times[active]) if active>=0 else None,
                  floor_points=float(max(20,peak[trigger]-.80*width)) if active>=0 else None,
                  trigger_index=int(ids[trigger]),trigger_time=float(times[trigger]),structure_at=float(times[trigger]),
                  trigger_reason="建値付近の逆行確認",exit_index=int(ids[fill]),status=5,reason="建値付近の逆行確認")
    return result
