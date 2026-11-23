"""期限近くの保護・順行不足・日中利確の16口座を比較する。"""
from pathlib import Path
import runpy

import numpy as np

FIRST = runpy.run_path(str(Path(__file__).with_name("出口候補.py")))
POLICIES = {
    "M01": "全場0.90R利確", "M02": "11時30分から0.90R", "M03": "11時30分から0.85R",
    "M04": "12時30分から0.90R", "M05": "残り10分と到達余地", "M06": "残り20分と到達余地",
    "M07": "残り15分の利益床", "M08": "残り8分の利益床", "M09": "残り15分の保護と無進展",
    "M10": "期限近くの逆行と遅い利益床", "M11": "15分順行なしと遅い利益床",
    "M12": "25分順行なしと遅い利益床", "M13": "0.85R到達後5分停滞", "M14": "0.90R到達後10分停滞",
    "M15": "残り10分の含み益を技術で保護", "M16": "午後利確と15分無進展・期限近くの保護",
}


def prepare(index, scene: dict) -> dict:
    """
    機能：既存の1・5分足の技術条件に直近8完成1分足の平均真値幅を加える。
    引数：index（PriceIndex）は日経の原板索引、scene（dict）は開始・場末時刻。
    返り値：dict。各原行で利用できた完成足の条件。
    """
    result = FIRST["prepare"](index, scene)
    cut = scene["end"]-900
    ids = index.normal[(index.times[index.normal] >= scene["start"]) & (index.times[index.normal] < cut)]
    n = result["squeeze"].shape[1]
    avg, tr, high, low, close = np.full((5, n), np.nan)
    if len(ids):
        bars = result["bar"][ids]
        value = (index.rows["ask"][ids]+index.rows["bid"][ids])/2
        first = np.r_[0, np.flatnonzero(np.diff(bars))+1]
        active = bars[first]
        high[active], low[active] = np.maximum.reduceat(value, first), np.minimum.reduceat(value, first)
        close[active] = value[np.r_[first[1:]-1, len(value)-1]]
        tr[1:] = np.maximum(high[1:], close[:-1])-np.minimum(low[1:], close[:-1])
        for i in range(9, n):
            avg[i] = tr[i-8:i].mean()
    result.update(atr=avg, deadline=cut-60)
    return result


def targets(code: str, elapsed: float) -> float:
    """
    機能：入口時間帯と方策によって建時に注文する利確幅の元注文比を決める。
    引数：code（str）は候補ID、elapsed（float）は開始から新規までの秒数。
    返り値：float。利確幅のR倍率。
    """
    if code == "M01" or code in ("M02", "M16") and elapsed >= 165*60 or code == "M04" and elapsed >= 225*60:
        return .90
    if code == "M03" and elapsed >= 165*60:
        return .85
    return 1.0


def dynamic(code: str, context: dict, times: np.ndarray, bars: np.ndarray, move: np.ndarray,
            peak: np.ndarray, side: int, opened: float, deadline: float, width: float) -> tuple:
    """
    機能：時間満了までの余地、失速、順行不足から追尾床と能動返済を決める。
    引数：code（str）・context（dict）は方策と場。times・bars・move・peak（np.ndarray）は時計・完成情報の参照分・値幅・最大益。
    side（int）は方向、opened・deadline・width（float）は取得・判定期限・元幅。
    返り値：tuple。各原行の起動・床、能動返済真偽、返済事由。
    """
    left = np.maximum(0.0, deadline-times)
    squeezed = context["squeeze"][side, bars]
    contrary = context["adverse"][side, bars]
    arm = np.zeros(len(times), dtype=bool)
    floor = np.full(len(times), 20.0)
    close = np.zeros(len(times), dtype=bool)
    reason = "逆行失効"
    if code in ("M05", "M06"):
        max_left = 600 if code == "M05" else 1200
        reach = context["atr"][bars]*np.sqrt(left/60)
        close = (left <= max_left) & (move >= .20*width) & (width-move > reach) & squeezed
        reason = "期限前の失速利確"
    if code in ("M07", "M08", "M09", "M16"):
        max_left = 480 if code == "M08" else 900
        arm = (left <= max_left) & (peak >= .35*width) & (move > 20)
        floor = np.maximum(floor, peak-.25*width)
    if code in ("M09", "M10"):
        close = (left <= 900) & (peak < .20*width) & (move <= -.20*width) & contrary
    if code in ("M10", "M11", "M12"):
        arm = peak >= .90*width
        floor = np.maximum(floor, peak-.70*width)
    if code in ("M11", "M12", "M16"):
        minimum = 1500 if code == "M12" else 900
        close = (times-opened >= minimum) & (peak < 20) & (move <= -.20*width) & contrary
    if code in ("M13", "M14"):
        ratio, wait = (.85, 300) if code == "M13" else (.90, 600)
        arm = peak >= ratio*width
        latest = np.maximum.accumulate(np.where(np.diff(np.r_[0.0, peak]) > 0, times, opened))
        tighten = (times-latest >= wait) & squeezed
        floor = np.maximum(floor, np.where(tighten, peak-.25*width, 0.0))
    if code == "M15":
        arm = (left <= 600) & (move >= .60*width)
        floor = np.maximum(floor, peak-np.where(squeezed, .10, .20)*width)
    active = np.logical_or.accumulate(arm)
    return active, np.maximum.accumulate(np.where(active, floor, -np.inf)), close, reason


def decide(code: str, context: dict, index, entry: int, side: int, width: float,
           horizon: str, term: dict) -> dict:
    """
    機能：既定の両端・期限・証拠不足と動的判断の翌秒約定を時系列で調停する。
    引数：code（str）・context（dict）は候補と指標、index（PriceIndex）は索引、entry・side（int）は取得行・方向、
    width（float）は元幅、horizon（str）は期限、term（dict）は元の観測・決済終端。
    返り値：dict。決済行・分類・事由と、保護起動・発動の原行、時刻、保護幅。
    """
    sign = 1 if side == 0 else -1
    opened = float(index.times[entry])
    price = float(index.rows["ask" if side == 0 else "bid"][entry])
    mark = index.rows["bid" if side == 0 else "ask"]
    target = width*targets(code, opened-context["start"])
    lower, upper = (price-width, price+target) if side == 0 else (price-target, price+width)
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
    peak = np.maximum.accumulate(np.maximum(move, 0.0))
    result["peak_points"] = float(peak[-1])
    if code in ("M01", "M02", "M03", "M04"):
        return result
    deadline = context["deadline"]
    if horizon != "SESSION":
        deadline = min(deadline, opened+int(horizon[1:])*60)
    times, bars = index.times[ids], context["bar"][ids]
    active, floor, close, exit_reason = dynamic(code, context, times, bars, move, peak, side, opened, deadline, width)
    touched = (move <= floor) & np.r_[False, active[:-1]]
    first = FIRST["first_true"]
    signal = first(touched | close)
    observed = len(ids)-1-int(end >= 0 and ids[-1] == end)
    if 0 <= signal <= observed:
        reason = "利益保護" if touched[signal] else exit_reason
        result.update(trigger_index=int(ids[signal]), trigger_time=float(times[signal]), trigger_reason=reason)
        fill = int(np.searchsorted(times, times[signal]+1))
        if fill <= observed:
            result.update(exit_index=int(ids[fill]), status=5, reason=reason, peak_points=float(peak[fill]))
        observed = signal
    activation = first(active[:observed+1])
    if activation >= 0:
        result.update(activated=True, activation_index=int(ids[activation]), activation_time=float(times[activation]),
                      floor_points=float(floor[observed]))
    return result
