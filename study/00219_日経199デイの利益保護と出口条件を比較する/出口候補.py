"""日経199_02の実側気配を使った単純IFD・利益保護・複合技術返済の候補。"""
import numpy as np


POLICIES = {
    "E01": "損切だけ0.75R", "E02": "利確だけ0.75R",
    "E03": "費用後利益発生で床", "E04": "0.35Rで床",
    "E05": "0.35Rから0.50R追尾", "E06": "0.50Rから0.65R追尾",
    "E07": "0.65Rから0.45R追尾", "E08": "順行3段階で保護床を上げる",
    "E09": "失速・収縮で追尾幅を変更", "E10": "可変追尾と12分無進展",
    "E11": "費用床と25分無進展", "E12": "追尾と1分価格構造失効",
    "E13": "入口時間帯で追尾起動を変更", "E14": "高値益の更新停止と技術失速",
}
START_R = {"E03": 0.0, "E04": .35, "E05": .35, "E06": .50, "E07": .65,
           "E08": .45, "E09": .40, "E10": .40, "E11": .65, "E12": .50, "E14": .45}
TRAIL_R = {"E05": .50, "E06": .65, "E07": .45, "E12": .65}


def prepare(index, scene: dict) -> dict:
    """
    機能：正常な板の中値から1分足と直前までの完成足による売買両側の判断を用意する。
    引数：index（PriceIndex）は日経原板索引、scene（dict）は当日の開始・終了時刻。
    返り値：dict。正常原行の分番号と、各観測分に利用可能な技術判定。
    """
    start, cut = scene["start"], scene["end"] - 900
    minutes = int((cut - start) // 60) + 1
    bar_by_row = np.floor((index.times - start) / 60).astype(np.int32)
    normal = index.normal
    allowed = normal[(index.times[normal] >= start) & (index.times[normal] < cut)]
    bar = bar_by_row[allowed]
    high, low, close = np.full((3, minutes), np.nan)
    if len(bar):
        mid = (index.rows["ask"][allowed] + index.rows["bid"][allowed]) / 2
        first = np.r_[0, np.flatnonzero(np.diff(bar)) + 1]
        high[bar[first]] = np.maximum.reduceat(mid, first)
        low[bar[first]] = np.minimum.reduceat(mid, first)
        close[bar[first]] = mid[np.r_[first[1:] - 1, len(bar) - 1]]
    # ----------------------------------------
    squeeze, adverse, broken = np.zeros((3, 2, minutes), dtype=bool)
    spread = np.full(minutes, np.nan)
    ema_fast = ema_slow = last_diff = 0.0
    streak = 0
    for i in range(minutes - 1):
        last = close[i]
        if not np.isfinite(last):
            streak = 0
            continue
        if streak:
            ema_fast += (last-ema_fast)*.5
            ema_slow += (last-ema_slow)*2/9
        else:
            ema_fast = ema_slow = last
            last_diff = 0.0
        streak += 1
        diff = ema_fast-ema_slow
        change = diff-last_diff
        last_diff = diff
        if streak < 8:
            continue
        spread[i] = np.std(close[i-7:i+1])
        path = np.abs(np.diff(close[i-3:i+1])).sum()
        efficiency = (last-close[i-3])/path if path else 0.0
        contraction = streak >= 11 and spread[i-3] > 0 and spread[i] <= .75*spread[i-3]
        boundary = (i+1)//5*5
        ready5 = boundary >= 10 and streak >= i+1-boundary+10
        change5 = close[boundary-1]-close[boundary-6] if ready5 else np.nan
        for side, sign in ((0, 1), (1, -1)):
            # i分足の結果は、次の分に入ってから利用できる。
            squeeze[side, i+1] = ((sign*change < 0 and sign*efficiency <= 0)
                                   or (contraction and sign*(last-ema_fast) < 0))
            adverse[side, i+1] = sign*(last-ema_slow) < 0 and sign*efficiency <= -.5 and sign*change5 < 0
            broken[side, i+1] = last < min(low[i-5:i]) if side == 0 else last > max(high[i-5:i])
    return {"start": start, "bar": bar_by_row, "squeeze": squeeze, "adverse": adverse, "broken": broken}


def first_true(test: np.ndarray) -> int:
    """
    機能：原行順の条件列で最初に成立した相対位置を得る。
    引数：test（np.ndarray）は真偽列。
    返り値：int。未成立なら−1。
    """
    if not len(test) or not test.any():
        return -1
    return int(test.argmax())


def protection(code: str, context: dict, time: np.ndarray, bar: np.ndarray, side: int,
               width: float, opened: float, peak: np.ndarray) -> tuple:
    """
    機能：起動水準と各正常原行の非緩和床を計算する。
    引数：code（str）、context（dict）、time・bar・peak（np.ndarray）は方策・場・正常行の時計・分・最大益。
    side（int）は売買、width・opened（float）は元IFD幅と建時刻。
    返り値：tuple。起動状態の真偽列と売買方向に正規化した床pt列。
    """
    if code == "E13":
        start_r = .65 if opened-context["start"] < 165*60 else .35
    else:
        start_r = START_R[code]
    active = (peak >= width*start_r) & (peak > 10.77)
    floor = np.full(len(peak), 20.0)
    if code in TRAIL_R:
        floor = np.maximum(floor, peak-TRAIL_R[code]*width)
    elif code == "E08":
        floor = np.maximum(floor, np.where(peak >= .85*width, .55*width, np.where(peak >= .70*width, .35*width, 0.0)))
    elif code in ("E09", "E10", "E13"):
        gap = np.where(context["squeeze"][side, bar], .30, .75)*width
        floor = np.maximum(floor, peak-gap)
    elif code == "E14":
        new_peak = np.diff(np.r_[0.0, peak]) > 0
        last_record = np.maximum.accumulate(np.where(new_peak, time, opened))
        tighten = (time-last_record >= 600) & context["squeeze"][side, bar]
        floor = np.maximum(floor, np.where(tighten, peak-.25*width, 0.0))
    return active, np.maximum.accumulate(np.where(active, floor, -np.inf))


def decide(code: str, context: dict, index, entry: int, side: int, width: float,
           horizon: str, term: dict) -> dict:
    """
    機能：元の先着・期限と並行して、新しい出口が先に完了したかを正常原行で決定する。
    引数：code（str）は方策、context（dict）は完成足判定、index（PriceIndex）は価格索引。
    entry・side（int）は建玉の原行・方向、width（float）は元IFD幅、horizon（str）は元期限名、
    term（dict）は期限・場末・欠測を処理した観測終端。
    返り値：dict。決済原行・分類・理由と、その建玉の起動／発動時計・床・最大順行。
    """
    sign = 1 if side == 0 else -1
    mark = index.rows["bid" if side == 0 else "ask"]
    price = float(index.rows["ask" if side == 0 else "bid"][entry])
    target = width * (.75 if code == "E02" else 1.0)
    loss = width * (.75 if code == "E01" else 1.0)
    lower, upper = (price-loss, price+target) if side == 0 else (price-target, price+loss)
    hit = index.first_outside(entry+1, term["touch_end"], lower, upper, side)
    end = hit if hit >= 0 else term["exit"]
    status = (1 if sign*(mark[hit]-price) > 0 else 2) if hit >= 0 else term["status"]
    reason = {1: "静的利確", 2: "静的損切", 3: "期限決済", 4: "場末決済"}.get(status, "決済不明")
    result = {"exit_index": int(end), "status": int(status), "reason": reason, "trigger_index": -1,
              "trigger_time": None, "trigger_reason": None, "floor_points": None, "peak_points": 0.0,
              "activated": False, "activation_index": -1, "activation_time": None}
    # ----------------------------------------
    normal = index.normal
    stop = min(end+1, term["touch_end"]) if end >= 0 else term["touch_end"]
    ids = normal[np.searchsorted(normal, entry+1):np.searchsorted(normal, stop)]
    if not len(ids):
        return result
    move = sign*(mark[ids]-price)
    peak = np.maximum.accumulate(np.maximum(move, 0.0))
    result["peak_points"] = float(peak[-1])
    if code in ("E01", "E02"):
        return result
    opened = float(index.times[entry])
    time = index.times[ids]
    bar = context["bar"][ids]
    active, floor = protection(code, context, time, bar, side, width, opened, peak)
    # 保護の起動原行を過去に遡ってタッチした扱いにしない。
    touched = (move <= floor) & np.r_[False, active[:-1]]
    adverse = context["adverse"][side, bar]
    if code == "E10":
        rejected = (time-opened >= 720) & (peak < .25*width) & (move <= -.28*width) & adverse
    elif code == "E11":
        rejected = (time-opened >= 1500) & (peak < .20*width) & (move <= -.15*width) & adverse
    elif code == "E12":
        rejected = (peak < .30*width) & (move <= -.40*width) & adverse & context["broken"][side, bar]
    else:
        rejected = False
    signal = first_true(touched | rejected)
    observed = len(ids)-1
    if end >= 0 and ids[-1] == end:
        observed -= 1
    if 0 <= signal <= observed:
        trigger = int(ids[signal])
        reason = "利益保護" if touched[signal] else "逆行失効"
        result.update(trigger_index=trigger, trigger_time=float(time[signal]), trigger_reason=reason)
        fill = int(np.searchsorted(time, time[signal]+1.0))
        if fill <= observed:
            result.update(exit_index=int(ids[fill]), status=5, reason=reason, peak_points=float(peak[fill]))
        # 発動後の待機中に成立した別の技術条件や床更新は採用しない。
        observed = signal
    activated = first_true(active[:observed+1])
    if activated >= 0:
        result.update(activated=True, activation_index=int(ids[activated]),
                      activation_time=float(time[activated]), floor_points=float(floor[observed]))
    return result
