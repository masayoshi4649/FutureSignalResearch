"""元IFDの損切り水準に達したときの時計と、建てる時点で指定する非常停止幅を比較する。"""
import numpy as np


POLICIES = {
    "W01": "損切1.10RのIFD", "W02": "損切1.25RのIFD", "W03": "損切1.50RのIFD",
    "W04": "元幅と遅い追尾", "W05": "損切1.10Rと遅い追尾", "W06": "損切1.25Rと遅い追尾",
    "W07": "損切1.50Rと遅い追尾", "W08": "往復中の損切1.25R", "W09": "順行中の損切1.25R",
    "W10": "大きい日中レンジの損切1.25R", "W11": "午前の狭幅IFDの損切1.25R", "W12": "午後の往復中の損切1.25R",
    "W13": "逆行が30秒続けば返済", "W14": "逆行が120秒続けば返済", "W15": "往復中に限り連続逆行120秒",
}
SCALES = {"W01": 1.1, "W02": 1.25, "W03": 1.5, "W04": 1., "W05": 1.1, "W06": 1.25, "W07": 1.5,
          "W13": 1.25, "W14": 1.25}
# 比較元、条件付初期倍率、効率上限、開始後の時刻境界（分）、追尾開始、追尾幅。値幅はR比。
NEIGHBORS = {
    "W16": ("W12", 1.25, .35, 165, np.inf, .70),
    "W17": ("W12", 1.10, .35, 165, .85, .70), "W18": ("W12", 1.50, .35, 165, .85, .70),
    "W19": ("W12", 1.25, .25, 165, .85, .70), "W20": ("W12", 1.25, .45, 165, .85, .70),
    "W21": ("W12", 1.25, .35, 105, .85, .70), "W22": ("W12", 1.25, .35, 225, .85, .70),
    "W23": ("W12", 1.25, .35, 165, .90, .70), "W24": ("W12", 1.25, .35, 165, .95, .70),
    "W25": ("W05", 1.10, .35, 165, .90, .70), "W26": ("W05", 1.10, .35, 165, .95, .70),
    "W27": ("W12", 1.10, .35, 165, .90, .70), "W28": ("W12", 1.50, .35, 165, .90, .70),
    "W29": ("W12", 1.25, .35, 165, .85, 1.), "W30": ("W05", 1.10, .35, 165, .85, 1.),
}
POLICIES.update({key: "逆行幅と保護開始の近傍"+key[1:] for key in NEIGHBORS})
HORIZON_GUARDS = {"W31": ("W27", .90), "W32": ("W27", .85), "W33": ("W12", .90),
                  "W34": ("W12", .85), "W35": ("W05", .90), "W36": ("W04", .90)}
POLICIES.update({key: "元の保有期限に応じた利益床"+key[1:] for key in HORIZON_GUARDS})


def prepare(index, scene: dict) -> dict:
    """
    機能：正常気配中値から確定した1分足だけで、取得分の開始までの経路と価格幅を作る。
    引数：index（PriceIndex）は48バイト気配索引、scene（dict）は場の開始・終了。
    返り値：dict。取引開始と各分の利用可能な効率、直近5分変化、12本レンジ。
    """
    start, cut = scene["start"], scene["end"] - 900
    count = int((cut-start)//60)+1
    ids = index.normal[(index.times[index.normal] >= start) & (index.times[index.normal] < cut)]
    close, high, low, er, delta, span = np.full((6, count), np.nan)
    if len(ids):
        slot = ((index.times[ids]-start)//60).astype(int)
        mid = (index.rows["bid"][ids]+index.rows["ask"][ids])/2
        first = np.r_[0, np.flatnonzero(np.diff(slot))+1]
        blocks = slot[first]
        close[blocks] = mid[np.r_[first[1:]-1,len(mid)-1]]
        high[blocks] = np.maximum.reduceat(mid, first)
        low[blocks] = np.minimum.reduceat(mid, first)
    for i in range(13, count):
        prices = close[i-13:i]
        if np.isfinite(prices).all():
            length = np.abs(np.diff(prices)).sum()
            er[i] = (prices[-1]-prices[0])/length if length else 0.0
            delta[i] = prices[-1]-prices[-6]
            span[i] = np.max(high[i-12:i])-np.min(low[i-12:i])
    return {"start": start, "er": er, "delta": delta, "span": span}


def initial(code: str, c: dict, opened: float, sign: int, width: float) -> tuple:
    """
    機能：建玉時点の当時情報から非常停止幅と逆行の連続判定秒を固定する。
    引数：code（str）は候補、c（dict）は場の系列、opened（float）は新規秒、sign（int）とwidth（float）は方向・元幅。
    返り値：tuple。非常停止倍率、連続逆行を理由に返済するまでの秒数（無効なら0）。
    """
    if code in SCALES:
        return SCALES[code], {"W13": 30, "W14": 120}.get(code, 0)
    i = int((opened-c["start"])//60)
    sideways = abs(c["er"][i]) <= .35
    not_opposed = sign*c["delta"][i] >= -.15*width
    choices = {"W08": sideways and not_opposed, "W09": sign*c["er"][i] >= .25 and sign*c["delta"][i] > 0,
               "W10": c["span"][i] >= .60*width and not_opposed, "W11": i < 165 and width <= 200,
               "W12": i >= 165 and sideways, "W15": sideways and not_opposed}
    wide = choices[code]
    return (1.25 if wide else 1.0), (120 if wide and code == "W15" else 0)


def decide(code: str, context: dict, index, entry: int, side: int, width: float,
           horizon: str, term: dict) -> dict:
    """
    機能：固定した非常停止・利確・非緩和追尾・連続逆行返済を有効な原行順で比較する。
    引数：code・horizon（str）は候補と旧期限、context・term（dict）は当時系列と期限、indexは価格索引、
    entry・side（int）は取得行と側、width（float）は元IFD幅。
    返り値：dict。実返済行、返済理由、保護・執行時計と取得時決定の非常停止倍率。
    """
    sign = 1 if side == 0 else -1
    opened = float(index.times[entry])
    price = float(index.rows["ask" if side == 0 else "bid"][entry])
    quote = index.rows["bid" if side == 0 else "ask"]
    start_r, trail_r = .85, .70
    stop_rule, normal_start = HORIZON_GUARDS.get(code, (code, .85))
    if stop_rule in NEIGHBORS:
        parent, allowed, max_er, boundary, start_r, trail_r = NEIGHBORS[stop_rule]
        minute = int((opened-context["start"])//60)
        widened = parent == "W05" or (minute >= boundary and abs(context["er"][minute]) <= max_er)
        scale, seconds = (allowed if widened else 1.), 0
    else:
        scale, seconds = initial(stop_rule, context, opened, sign, width)
    if code in HORIZON_GUARDS:
        start_r = .95 if horizon == "SESSION" else normal_start
    loss = width*scale
    lower, upper = (price-loss, price+width) if side == 0 else (price-width, price+loss)
    hit = index.first_outside(entry+1, term["touch_end"], lower, upper, side)
    end = hit if hit >= 0 else term["exit"]
    status = (1 if sign*(quote[hit]-price) > 0 else 2) if hit >= 0 else term["status"]
    reason = {1: "静的利確", 2: "静的損切", 3: "期限決済", 4: "場末決済"}.get(status, "決済不明")
    result = dict(exit_index=int(end), status=int(status), reason=reason, activated=False, activation_index=-1,
                  activation_time=None, trigger_index=-1, trigger_time=None, trigger_reason=None,
                  floor_points=None, initial_stop_multiple=scale, initial_inside_wait_s=seconds)
    if code in ("W01", "W02", "W03", "W16"):
        return result
    # ----------------------------------------
    # 静的IFD・期限との同原行は既存注文を優先し、判定の後1秒以上たつまで執行しない。
    stop = min(end, term["touch_end"]) if end >= 0 else term["touch_end"]
    left, right = np.searchsorted(index.normal, [entry+1, stop])
    ids = index.normal[left:right]
    if not len(ids):
        return result
    times = index.times[ids]
    move = sign*(quote[ids]-price)
    peak = np.maximum.accumulate(move)
    active = peak >= start_r*width
    floor = np.maximum(20.0, peak-trail_r*width)
    protected = (move <= floor) & np.r_[False, active[:-1]]
    fails = np.zeros(len(ids), dtype=bool)
    if seconds:
        outside = move <= -width
        began = outside & ~np.r_[False, outside[:-1]]
        last_crossing = np.maximum.accumulate(np.where(began, times, -np.inf))
        fails = outside & (times-last_crossing >= seconds)
    signals = protected | fails
    observed = len(ids)-1
    if np.any(signals):
        trigger = int(signals.argmax())
        observed = trigger
        reason = "利益保護" if protected[trigger] else "連続逆行返済"
        result.update(trigger_index=int(ids[trigger]), trigger_time=float(times[trigger]), trigger_reason=reason)
        fill = int(np.searchsorted(times, times[trigger]+1))
        if fill < len(ids):
            result.update(exit_index=int(ids[fill]), status=5, reason=reason)
    if active[observed]:
        activation = int(active[:observed+1].argmax())
        result.update(activated=True, activation_index=int(ids[activation]), activation_time=float(times[activation]),
                      floor_points=float(floor[observed]))
    return result
