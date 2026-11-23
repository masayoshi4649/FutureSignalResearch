"""深く逆行した建玉が回復した時点で、後続の保護と返済を比較する。"""
from pathlib import Path
import runpy

import numpy as np

SHARED = runpy.run_path(str(Path(__file__).resolve().parents[1]/"出口候補.py"))
prepare = SHARED["prepare"]
POLICIES = {"K00":"遅い追尾のみ", "K01":"半幅逆行後に建値回復で返済", "K02":"深い逆行後の建値回復",
            "K03":"半幅逆行から利益に戻った後の追尾", "K04":"深い逆行から利益に戻った後の追尾",
            "K05":"損失縮小時にも失速なら返済", "K06":"利益回復後の失速返済"}


def decide(code: str, context: dict, index, entry: int, side: int, width: float, horizon: str, term: dict) -> dict:
    """
    機能：元IFDが生きている時間内で、利益追尾と深い逆行からの回復を原行順に判定する。
    引数：code（str）は条件、context・term（dict）は完成足・期限、indexは価格索引、
    entry・side（int）は新規原行と実側、width（float）は元片幅、horizon（str）は元期限。
    返り値：dict。代用約定原行・理由・保護又は返済の発動時計。
    """
    if code not in POLICIES:
        raise ValueError(code)
    # E01/E02の静的幅変更を使わず、常に1R対1Rで受ける。
    mark = index.rows["bid" if side==0 else "ask"]
    price = float(index.rows["ask" if side==0 else "bid"][entry])
    sign = 1 if side==0 else -1
    hit = index.first_outside(entry+1,term["touch_end"],price-width,price+width,side)
    end = hit if hit>=0 else term["exit"]
    status = (1 if sign*(mark[hit]-price)>0 else 2) if hit>=0 else term["status"]
    result = {"status":int(status),"exit_index":int(end),"reason":{1:"静的利確",2:"静的損切",3:"期限決済",4:"場末決済"}.get(status,"決済不明"),
              "activated":False,"activation_time":None,"trigger_time":None,"floor_points":None}
    normal = index.normal
    stop = min(end,term["touch_end"]) if end>=0 else term["touch_end"]
    ids = normal[np.searchsorted(normal,entry+1):np.searchsorted(normal,stop)]
    if not len(ids):
        return result
    # ----------------------------------------
    move = sign*(mark[ids]-price)
    peak = np.maximum.accumulate(move)
    low = np.minimum.accumulate(move)
    prior_loss = low <= -({"K02":.70,"K04":.70,"K05":.55,"K06":.55}.get(code,.50))*width
    regained = np.maximum.accumulate(prior_loss & (move>=20))
    regular = peak >= .90*width
    floor = np.where(regular,np.maximum(20,peak-.65*width),-np.inf)
    if code in ("K03","K04"):
        recent_peak = np.maximum.accumulate(np.where(regained,move,-np.inf))
        floor = np.maximum(floor,np.where(regained,np.maximum(20,recent_peak-.25*width),-np.inf))
    floor = np.maximum.accumulate(floor)
    touched = (move<=floor) & np.r_[False,np.isfinite(floor[:-1])]
    recovery = np.zeros(len(ids),dtype=bool)
    if code in ("K01","K02"):
        recovery = prior_loss & (move>=20)
    elif code in ("K05","K06"):
        stalled = context["squeeze"][side,context["bar"][ids]]
        recovery = (prior_loss & (move>=-.10*width) if code=="K05" else regained & (move>=20)) & stalled
    first = SHARED["first_true"](touched | recovery)
    observed = first if first>=0 else len(ids)-1
    activated = SHARED["first_true"](np.isfinite(floor[:observed+1]))
    if activated>=0:
        result.update(activated=True,activation_time=float(index.times[ids[activated]]),floor_points=float(floor[observed]))
    if first>=0:
        trigger = float(index.times[ids[first]])
        result["trigger_time"] = trigger
        fill = np.searchsorted(index.times[ids],trigger+1)
        if fill<len(ids):
            result.update(exit_index=int(ids[fill]),status=5,reason="利益保護" if touched[first] else "逆行後の戻り返済")
    return result
