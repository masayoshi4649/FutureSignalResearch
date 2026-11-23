"""元IFDの利確・損切り・保有期限を維持し、到達経路と残り時間で利益保護だけを追加する。"""
from pathlib import Path
import runpy

import numpy as np

MAIN = runpy.run_path(str(next(Path(__file__).resolve().parents[2].glob("00220_*/主比較/出口条件.py"))))
prepare = MAIN["prepare"]
POLICIES = [f"A{i:02d}" for i in range(13)]


def locks(code: str, time: np.ndarray, move: np.ndarray, opened: float, left: np.ndarray, width: float,
          weak: np.ndarray, twice: np.ndarray) -> tuple:
    """
    機能：観測時点の情報から起動状態と利益床を決める。
    引数：code（str）は出口、time・move・left（np.ndarray）は価格時計・順行・残り秒数、
    opened・width（float）は建時刻・元幅、weak・twice（np.ndarray）は完成足の技術条件。
    返り値：tuple。各原行に対応する起動状態とこれまでの最も有利な保護床。
    """
    peak = np.maximum.accumulate(move)
    arm = move >= .95*width
    floor = np.maximum(20.,peak-.80*width)
    late = left <= 600
    if code in ("A02","A03","A04","A05","A09","A10","A11"):
        late_arm = late & (move>=.45*width)
        if code=="A11":
            late_arm &= twice
        arm |= late_arm
        slowing = twice if code in ("A03","A09","A10","A11") else weak
        if code!="A04":
            gap = (.25+.40*np.clip(left/600,0,1))*width if code=="A05" else .35*width
            floor = np.maximum(floor,np.where(late & slowing,peak-gap,0))
    # ----------------------------------------
    if code in ("A06","A07","A08","A09"):
        improved = np.diff(np.r_[-np.inf,peak])>0
        last = np.maximum.accumulate(np.where(improved,time,opened))
        rejected = (peak>=.80*width) & (time-last>=60) & (peak-move>=.15*width) & (move>=.40*width)
        if code!="A06":
            rejected &= weak
        if code in ("A08","A09"):
            rejected &= left<=1800
        arm |= rejected
        floor = np.maximum(floor,np.where(np.logical_or.accumulate(rejected),peak-.45*width,0))
    if code=="A10":
        retreated = np.logical_or.accumulate((peak>=.80*width) & (move<=.65*width))
        retested = retreated & (move>=.80*width)
        arm |= retested
        floor = np.maximum(floor,np.where(np.logical_or.accumulate(retested),peak-.45*width,0))
    active = np.logical_or.accumulate(arm)
    return active,np.maximum.accumulate(np.where(active,floor,-np.inf))


def apply_rule(code: str, context: dict, index: object, entry: int, side: int,
               width: float, horizon: str, term: dict, rule: object, delay: int = 1) -> dict:
    """
    機能：元IFDの決済を対照に、先に執行できた追加の保護返済だけを適用する。
    引数：code・horizon（str）は条件と元期限、context・term（dict）は当時系列・打切り、
    index（PriceIndex）は板索引、entry・side（int）は新規原行・方向、width（float）は元幅、
    rule（callable）は各原行での追尾床を決める関数、delay（int）は追加保護の発動から執行までの最短秒数。
    返り値：dict。静的決済または保護での決済原行、価格幅、起動・発動時刻と床。
    """
    if code=="A00" or (code=="A12" and horizon!="SESSION"):
        return MAIN["settle"]("P2",width,context,index,entry,side,width,horizon,term)
    result = MAIN["settle"]("P0",width,context,index,entry,side,width,horizon,term)
    old_end = result["exit_index"]
    end = min(old_end,term["touch_end"]) if old_end>=0 else term["touch_end"]
    normal = index.normal
    lo,hi = np.searchsorted(normal,[entry+1,end])
    ids = normal[lo:hi]
    if not len(ids):
        return result
    side_quotes = index.rows["bid" if side==0 else "ask"][ids]
    entry_price = index.rows["ask" if side==0 else "bid"][entry]
    move = (side_quotes-entry_price)*(1 if side==0 else -1)
    time = index.times[ids]
    opened = float(index.times[entry])
    deadline = context["deadline"]
    if horizon!="SESSION":
        deadline = min(deadline,opened+60*int(horizon[1:]))
    bar = context["bar"][ids]
    by_bar = context["squeeze"][side]
    weak = by_bar[bar]
    twice = weak & (bar>=1) & by_bar[np.maximum(0,bar-1)]
    active,floor = rule(code,time,move,opened,deadline-time,width,weak,twice)
    # ----------------------------------------
    first_true = MAIN["TECH"]["first_true"]
    start = first_true(active)
    if start<0:
        return result
    result.update(activated=True,activation_index=int(ids[start]),activation_time=float(time[start]),
                  floor_points=float(floor[-1]))
    trigger = first_true((move<=floor) & np.r_[False,active[:-1]])
    if trigger>=0:
        result.update(trigger_index=int(ids[trigger]),trigger_time=float(time[trigger]),trigger_reason="利益保護",
                      floor_points=float(floor[trigger]))
        fill = int(np.searchsorted(time,time[trigger]+delay))
        if fill<len(ids):
            result.update(exit_index=int(ids[fill]),reason="利益保護",status=5)
    return result


def decide(code: str, context: dict, index: object, entry: int, side: int,
           width: float, horizon: str, term: dict) -> dict:
    """
    機能：初回登録の各条件で両側の常設注文と追尾を合わせて処理する。
    引数：code・horizon（str）は条件と期限、context・term（dict）は当時系列・打切り、
    index（PriceIndex）は板索引、entry・side（int）は取得と方向、width（float）は元幅。
    返り値：dict。実際の決済原行と判断の時刻。
    """
    return apply_rule(code,context,index,entry,side,width,horizon,term,locks)
