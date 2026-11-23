"""取得時の朝の価格位置と完成1分足に応じて利確幅を決め、観測中の利益を段階的に保護する。"""
import numpy as np

POLICIES = ("L00", "L01", "L02", "L03", "L04", "L05", "L06", "L07")
REASON = {1: "利確先着", 2: "損切先着", 3: "通常期限返済", 4: "事前要求の強制返済",
          10: "価格gap未知", 11: "BBOgap未知", 12: "通常期限BBO不足", 13: "強制返済窓BBO不足", 14: "EOF未知"}


def prepare(index: object, scene: dict) -> dict:
    """
    機能：当日最初の正常気配と、取得時に完成済みの足だけで比較する3分方向効率の系列を作る。
    引数：index（PriceIndex）は原行順48バイト索引、scene（dict）は場の開始・終了。
    返り値：dict。朝の正常中値と開始時計、取得時の分番号に対応する直前4終値の方向効率。
    """
    start = scene["start"]
    valid = index.normal[(index.times[index.normal] >= start) & (index.times[index.normal] < scene["end"]-900)]
    minutes = ((index.times[valid]-start)//60).astype(int)
    count = int((scene["end"]-900-start)//60)+1
    close = np.full(count, np.nan)
    efficiency = np.full(count, np.nan)
    if not len(valid):
        return {"start": start, "open": float("nan"), "first": -1, "efficiency": efficiency}
    midpoint = (index.rows["bid"][valid]+index.rows["ask"][valid])/2
    final = np.r_[np.flatnonzero(np.diff(minutes) != 0), len(valid)-1]
    close[minutes[final]] = midpoint[final]
    for minute in range(4,count):
        history = close[minute-4:minute]
        if np.isfinite(history).all():
            length = abs(np.diff(history)).sum()
            if length > 0:
                efficiency[minute] = (history[-1]-history[0])/length
    return {"start": start, "open": float(midpoint[0]), "first": int(valid[0]), "efficiency": efficiency}


def target(policy: str, ctx: dict, index: object, entry: int, sign: int) -> float:
    """
    機能：取得原行の時刻と気配・過去の1分足から、利確幅を元の幅の倍数で確定する。
    引数：policy（str）はID、ctx（dict）は場情報、index（PriceIndex）は板、entry・sign（int）は取得原行と方向。
    返り値：float。元幅の1倍・1.25倍・1.5倍。
    """
    minutes = int((index.times[entry]-ctx["start"])//60)
    morning = 0 <= minutes < 165
    mid = (index.rows["bid"][entry]+index.rows["ask"][entry])/2
    aligned = ctx["first"] >= 0 and entry >= ctx["first"] and sign*(mid-ctx["open"]) > 0
    supports = 0 <= minutes < len(ctx["efficiency"]) and sign*ctx["efficiency"][minutes] >= .25
    permitted = {"L00": False, "L01": True, "L02": morning, "L03": morning and aligned,
                 "L04": morning and aligned and supports, "L05": morning and aligned and supports,
                 "L06": aligned and supports, "L07": morning and aligned and supports}
    if permitted[policy]:
        return 1.5 if policy == "L05" else 1.25
    return 1.0


def decide(policy: str, ctx: dict, index: object, entry: int, side: int,
           width: float, horizon: str, term: dict) -> dict:
    """
    機能：取得後に固定した両側の立会注文と、1秒以上後に実行する保護返済の先着を決める。
    引数：policy（str）はID、ctx・term（dict）は場情報と期限、index（PriceIndex）は板、
        entry・side（int）は取得原行と側、width（float）は元IFD幅、horizon（str）は元期限名。
    返り値：dict。採用された原行、理由・状態、目標倍率・保護の発動記録。
    """
    sign = 1 if side == 0 else -1
    price = float(index.rows["ask" if side == 0 else "bid"][entry])
    multiple = target(policy, ctx, index, entry, sign)
    cap = term["touch_end"]
    lower, upper = (price-width, price+multiple*width) if side==0 else (price-multiple*width, price+width)
    hit = index.first_outside(entry+1, cap, lower, upper, side)
    end, status = int(term["exit"]), int(term["status"])
    mark = index.rows["bid" if side == 0 else "ask"]
    if hit >= 0:
        end = int(hit)
        status = 1 if sign*(mark[end]-price) > 0 else 2
    result = {"exit_index": end, "status": status, "reason": REASON[status], "target_multiple": multiple,
              "activated": False, "activation_index": -1, "activation_time": None,
              "trigger_index": -1, "trigger_time": None, "floor_points": None,
              "protection_trigger_line": None, "protection_trigger_time": None, "protection_trigger_points": None,
              "protection_floor": None}
    # ----------------------------------------
    begin, stop = np.searchsorted(index.normal, [entry+1, min(cap,end) if end>=0 else cap])
    rows = index.normal[begin:stop]
    if not len(rows):
        return result
    points = sign*(mark[rows]-price)
    peak = np.maximum.accumulate(points)
    floor = np.maximum(20.0, peak-.60*width)
    passed = peak >= width
    floor[passed] = np.maximum(.80*width, peak[passed]-.30*width)
    armed = peak >= (.70 if policy == "L07" else .50)*width
    reached = np.flatnonzero(armed & (points <= floor))
    starts = np.flatnonzero(armed)
    if len(starts):
        first = int(rows[starts[0]])
        result.update(activated=True, activation_index=first, activation_time=float(index.times[first]),
                      floor_points=float(floor[reached[0] if len(reached) else -1]))
    if len(reached):
        at = int(reached[0])
        trigger = int(rows[at])
        trigger_time = float(index.times[trigger])
        result.update(protection_trigger_line=int(index.rows["source_line"][trigger]),
                      protection_trigger_time=trigger_time, protection_trigger_points=float(points[at]),
                      protection_floor=float(floor[at]), trigger_index=trigger, trigger_time=trigger_time)
        fill = index.first_normal(trigger_time+1, trigger)
        if 0 <= fill < cap and (end < 0 or fill < end):
            result.update(exit_index=int(fill), status=5, reason="段階追尾")
    return result
