"""B400で固定利確と追尾を変えた比較、さらに0.85R順行時の最低0.50R確保を試す。"""
from pathlib import Path
import runpy

import numpy as np

CORE = runpy.run_path(str(Path(__file__).resolve().parents[1]/"主比較/出口条件.py"))
prepare = CORE["prepare"]
POLICIES = ["B400"+s for s in ("P1","P2","P5","P6","P7","G3","G4")]


def decide(code: str, context: dict, index: object, entry: int, side: int, width: float,
           horizon: str, term: dict) -> dict:
    """
    機能：幅上限400ptで損切りを決め、元の利確・追尾か、0.50R保護を強める段階追尾を再生する。
    引数：code・horizon（str）は方策と保有期限、context・term（dict）は当時状態と終端、
    index（PriceIndex）は原板、entry・side（int）は開始原行・売買、width（float）は元のIFD幅。
    返り値：dict。保護の起動・発動・実際の決済原行と、初期の損切り幅と利確幅。
    """
    opened = float(index.times[entry])
    stop_pts = min(400.0,CORE["stop_size"]("S3",context,opened,width))
    profit_id = code[4:]
    if profit_id.startswith("P"):
        return CORE["settle"](profit_id,stop_pts,context,index,entry,side,width,horizon,term)
    assert profit_id in ("G3","G4")
    static = "P1" if profit_id=="G3" else "P9"
    result = CORE["settle"](static,stop_pts,context,index,entry,side,width,horizon,term)
    end = result["exit_index"]
    stop = min(end,term["touch_end"]) if end>=0 else term["touch_end"]
    left,right = np.searchsorted(index.normal,[entry+1,stop])
    ids = index.normal[left:right]
    if not len(ids):
        return result
    # ----------------------------------------
    times = index.times[ids]
    if side==0:
        move = index.rows["bid"][ids]-index.rows["ask"][entry]
    else:
        move = index.rows["bid"][entry]-index.rows["ask"][ids]
    deadline = context["deadline"]
    if horizon!="SESSION":
        deadline = min(deadline,opened+int(horizon[1:])*60)
    late = deadline-times<=600
    threshold = move>=.85*width
    active = np.logical_or.accumulate(threshold | (late & (move>=.45*width)))
    if not np.any(active):
        return result
    peak = np.maximum.accumulate(move)
    floor = np.maximum(20.0,peak-.80*width)
    reduce = late & context["squeeze"][side,context["bar"][ids]]
    floor = np.maximum(floor,np.where(reduce,peak-.35*width,0))
    floor = np.maximum(floor,np.where(peak>=.85*width,.50*width,0))
    floor = np.maximum.accumulate(np.where(active,floor,-np.inf))
    first = int(active.argmax())
    result.update(activated=True,activation_index=int(ids[first]),activation_time=float(times[first]),
                  floor_points=float(floor[-1]))
    hit = (move<=floor) & np.r_[False,active[:-1]]
    if hit.any():
        trigger = int(hit.argmax())
        result.update(trigger_index=int(ids[trigger]),trigger_time=float(times[trigger]),
                      trigger_reason="利益保護",floor_points=float(floor[trigger]))
        fill = int(np.searchsorted(times,times[trigger]+1))
        if fill<len(ids):
            result.update(exit_index=int(ids[fill]),status=5,reason="利益保護")
    return result
