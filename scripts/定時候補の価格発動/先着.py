"""定時に固定した高安への将来発動と、新規約定後の先着を独立に測る。"""

from bisect import bisect_left, bisect_right
from collections import Counter
from copy import deepcopy
import math

EVENT_FIELDS = {"now", "line", "last", "bid", "ask", "valid"}
SOURCE_FIELDS = ("session", "index", "minutes", "start", "end", "confirm", "confirm_line", "publish", "missing", "open", "high", "low", "close")
BINDING = ("slot_id", "session", "scheduled", "time", "line")


def finite(value: object) -> bool:
    """boolを除く有限数値を判定する。

    引数: value(object)は入力値。
    返り値: boolは有限なint/floatならTrue。
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def normal(event: dict) -> bool:
    """元flagと返済可能BBOの正常性を検査する。

    引数: event(dict)は元6列。
    返り値: boolは有限正bid<askかつvalid True。Last条件は分離する。
    """
    return event["valid"] is True and finite(event["bid"]) and finite(event["ask"]) and 0 < event["bid"] < event["ask"]


def trigger_normal(event: dict) -> bool:
    """発動監視に使えるLastとBBOを同時に検査する。

    引数: event(dict)は元6列。
    返り値: boolは正常BBOかつ有限正Last。
    """
    return normal(event) and finite(event["last"]) and event["last"] > 0


def prepare_events(events) -> dict:
    """場ごとの元行・正常BBO・発動正常行を一度だけ索引化する。

    引数: events(iterable[dict])は有限非後退価格時計の元6列。
    返り値: dictは独立索引。市場ファイル・Engine・旧labelを呼ばない。
    """
    rows, quotes, observations = [], [], []
    previous_line, previous_time = 0, -math.inf
    for event in events:
        if not isinstance(event, dict) or set(event) != EVENT_FIELDS or type(event["valid"]) is not bool:
            raise ValueError("先着eventsは元6列が必要")
        if type(event["line"]) is not int or event["line"] <= previous_line or not finite(event["now"]) or event["now"] < previous_time:
            raise ValueError("先着eventsの原行又は時計順が不正")
        row = deepcopy(event)
        rows.append(row)
        if normal(row):
            quotes.append(row)
        if trigger_normal(row):
            observations.append(row)
        previous_line, previous_time = row["line"], row["now"]
    return {"schema": "条件先着索引1", "rows": rows, "times": [row["now"] for row in rows],
        "by_key": {(row["now"], row["line"]): row for row in rows}, "quotes": quotes,
        "quote_keys": [(row["now"], row["line"]) for row in quotes], "quote_times": [row["now"] for row in quotes],
        "observations": observations, "observation_keys": [(row["now"], row["line"]) for row in observations]}


def validate_condition(slot: dict, condition: dict, force: float, end: float) -> None:
    """元定時と公開3分SOURCE・固定高安・満了を検査する。

    引数: slot/condition(dict)は固定候補と4項目条件、force/end(float)は場の期限。
    返り値: None。不完全又は未来出典、左右不整合は拒否する。
    """
    if slot.get("ready") is not True or type(slot.get("side")) is not int or slot["side"] not in (-1, 1):
        raise ValueError("条件先着は準備済み方向候補が必要")
    if not all(finite(slot.get(key)) for key in ("scheduled", "time")) or type(slot.get("line")) is not int or slot["line"] < 1:
        raise ValueError("設定keyが不正")
    if not isinstance(condition, dict) or set(condition) != {"high", "low", "source", "expires"}:
        raise ValueError("条件は固定4項目が必要")
    source = condition["source"]
    if not isinstance(source, dict) or set(source) != set(SOURCE_FIELDS):
        raise ValueError("条件SOURCE13不成立")
    if source["session"] != slot["session"] or type(source["index"]) is not int or source["index"] < 0 or source["minutes"] != 3:
        raise ValueError("条件足の場又は番号が不正")
    if source["publish"] is not True or type(source["missing"]) is not int or source["missing"] != 0:
        raise ValueError("条件足は公開完全足が必要")
    if not all(finite(source[key]) for key in ("start", "end", "confirm", "open", "high", "low", "close")):
        raise ValueError("条件足の有限値不成立")
    if type(source["confirm_line"]) is not int or source["confirm_line"] < 0:
        raise ValueError("条件足の公開原行不正")
    if source["end"] - source["start"] != 180 or source["confirm"] < source["end"] or source["end"] > slot["scheduled"]:
        raise ValueError("条件足の完全幅又は終了時点が不正")
    if (source["confirm"], source["confirm_line"]) > (slot["time"], slot["line"]):
        raise ValueError("条件足が設定keyの未来")
    if not 0 < source["low"] <= min(source["open"], source["close"]) <= max(source["open"], source["close"]) <= source["high"]:
        raise ValueError("条件OHLC不正")
    if any(not finite(condition[key]) for key in ("high", "low", "expires")) or (condition["high"], condition["low"]) != (source["high"], source["low"]):
        raise ValueError("固定高安とSOURCEが不一致")
    if condition["expires"] != slot["scheduled"] + 900 or not finite(force) or not finite(end) or not slot["time"] < condition["expires"] < force < end:
        raise ValueError("条件寿命又は場期限が不正")


def timer_line(index: dict, moment: float, inclusive: bool = False) -> int | None:
    """timer以前に観測済みの最後の原行を返す。

    引数: index(dict)は元行索引、moment(float)はtimer、inclusive(bool)は同秒含有。
    返り値: int|Noneは最後の既知原行。境界後行を未来参照しない。
    """
    position = (bisect_right if inclusive else bisect_left)(index["times"], moment)
    return index["rows"][position - 1]["line"] if position else None


def gap_arrival(index: dict, last_observed: float, deadline: float, until: tuple | None = None) -> dict | None:
    """最終正常観測から300秒をstrict超す最初の原行を特定する。

    引数: index(dict)は全原行索引、last_observed/deadline(float)は監視時計、until(tuple|None)は次正常観測key。
    返り値: dict|Noneは期限未満の最初到着行。正常性に関係なく取消時計の出典にする。
    """
    position = bisect_right(index["times"], last_observed + 300)
    if position == len(index["rows"]):
        return None
    event = index["rows"][position]
    if event["now"] >= deadline or until is not None and (event["now"], event["line"]) > until:
        return None
    return event


def barrier(index: dict, fill: dict, side: int, force: float, end: float) -> dict:
    """実観測の新規BBOから125/250と空白を独立に逐行比較する。

    引数: index(dict)は正常板索引、fill(dict)は新規行、side(int)は±1、force/end(float)は場時計。
    返り値: dictはoutcome/end/mfe/mae。force最初同秒正常行までを含む。
    """
    price = fill["ask"] if side == 1 else fill["bid"]
    start = bisect_left(index["quote_keys"], (fill["now"], fill["line"]))
    previous, high, low = fill["now"], 0.0, 0.0
    result = {"outcome": "不足", "end_time": fill["now"], "end_line": fill["line"], "mfe": high, "mae": low}
    for position in range(start, len(index["quotes"])):
        quote = index["quotes"][position]
        if quote["now"] >= end:
            break
        if quote["now"] > force:
            result.update(outcome="期限" if force - previous <= 300 else "不足", end_time=force, end_line=quote["line"])
            break
        gain = side * ((quote["bid"] if side == 1 else quote["ask"]) - price)
        high, low = max(high, gain), min(low, gain)
        result.update(end_time=quote["now"], end_line=quote["line"], mfe=high, mae=low)
        if quote["now"] - previous > 300:
            break
        previous = quote["now"]
        if gain <= -125 or gain >= 250:
            result["outcome"] = "125" if gain <= -125 else "250"
            break
        if quote["now"] == force:
            result["outcome"] = "期限"
            break
    return result


def label(events, slot: dict, condition: dict, force: float, end: float) -> dict:
    """設定後の最初発動・期限内仮約定・新入口先着を一候補独立に測る。

    引数: events(iterable[dict]|dict)は元行又はprepare_events索引、slot/condition(dict)は固定判断と条件、force/end(float)は場時計。
    返り値: dictは元定時・条件・trigger・未発動等・新fill・125/250。実建玉占有は参照しない。
    """
    index = events if isinstance(events, dict) and events.get("schema") == "条件先着索引1" else prepare_events(events)
    validate_condition(slot, condition, force, end)
    origin = {key: deepcopy(slot[key]) for key in BINDING}
    result = {**origin, **{key: slot[key] for key in ("policy", "side", "role")}, "origin_slot": deepcopy(origin),
        "condition": deepcopy(condition), "trigger": None, "request_time": None, "request_line": None,
        "condition_outcome": "未発動", "condition_reason": "次定時まで未発動", "watch_started": False, "watch_quality": False,
        "filled": False, "outcome": "未発動", "end_time": min(condition["expires"], force, end), "end_line": None}
    setting = index["by_key"].get((slot["time"], slot["line"]))
    if setting is None:
        raise ValueError("設定keyの原行がない")
    if not trigger_normal(setting):
        result.update(condition_outcome="観測不足", condition_reason="設定Last又はBBO不正", outcome="観測不足", end_time=slot["time"], end_line=slot["line"])
        return result
    side = slot["side"]
    level = condition["high"] if side == 1 else condition["low"]
    if side * (setting["last"] - level) > 0:
        result.update(condition_outcome="既超過", condition_reason="設定時に発動線を既超過", outcome="既超過", end_time=slot["time"], end_line=slot["line"])
        return result
    result["watch_started"] = True
    deadline = min(condition["expires"], force, end)
    last_observed = slot["time"]
    start = bisect_right(index["observation_keys"], (slot["time"], slot["line"]))
    stop = bisect_left(index["observation_keys"], (deadline, -math.inf))
    for position in range(start, stop):
        event = index["observations"][position]
        if event["now"] >= deadline:
            break
        gap = gap_arrival(index, last_observed, deadline, (event["now"], event["line"]))
        if gap is not None:
            result.update(condition_outcome="観測不足", condition_reason="発動監視の正常価格間隔300秒超", watch_quality=True,
                outcome="観測不足", end_time=gap["now"], end_line=gap["line"])
            return result
        last_observed = event["now"]
        if side * (event["last"] - level) > 0:
            result["trigger"] = {"time": event["now"], "line": event["line"], "last": event["last"]}
            result.update(request_time=event["now"], request_line=event["line"])
            break
    if result["trigger"] is None:
        result.update(end_time=deadline, end_line=timer_line(index, deadline))
        gap = gap_arrival(index, last_observed, deadline)
        if gap is not None:
            result.update(condition_outcome="観測不足", condition_reason="発動監視の正常価格間隔300秒超", watch_quality=True,
                outcome="観測不足", end_time=gap["now"], end_line=gap["line"])
        elif deadline - last_observed > 300:
            result.update(condition_outcome="観測不足", condition_reason="満了時の発動監視間隔300秒超", watch_quality=True, outcome="観測不足")
        return result
    trigger = result["trigger"]
    ttl = trigger["time"] + 30
    result.update(condition_outcome="発動未約定", condition_reason="要求後の正常約定なし又は次定時取消", outcome="発動未約定",
        end_time=min(ttl, deadline), end_line=timer_line(index, min(ttl, deadline), ttl < deadline))
    first = bisect_left(index["quote_keys"], (trigger["time"] + 1, -math.inf))
    for position in range(first, len(index["quotes"])):
        fill = index["quotes"][position]
        if fill["line"] <= trigger["line"]:
            continue
        if fill["now"] > ttl or fill["now"] >= deadline:
            break
        result.update(condition_outcome="約定", condition_reason="発動後の最初正常BBO", filled=True,
            entry_time=fill["now"], entry_line=fill["line"], entry_price=fill["ask"] if side == 1 else fill["bid"])
        result.update(barrier(index, fill, side, force, end))
        return result
    return result


def entry_stats(rows: list[dict], target_period: str, period) -> dict:
    """新入口key順に非重複を間引き、従来の支持と率を計算する。

    引数: rows(list[dict])は独立条件ラベル、target_period(str)は期、period(Callable[[str],str])は固定期分類。
    返り値: dictはC49互換の入口集計。未発動等の分母と結果も残す。
    """
    chosen = [row for row in rows if period(row["session"]) == target_period]
    filled = sorted((row for row in chosen if row["filled"]), key=lambda row: (row["entry_time"], row["entry_line"], row["slot_id"]))
    thin, last = [], {}
    for row in filled:
        session = row["session"]
        if (row["entry_time"], row["entry_line"]) > last.get(session, (-math.inf, -1)):
            thin.append(row)
            last[session] = row["end_time"], row["end_line"]
    n, nt = len(filled), len(thin)
    wins = sum(row["outcome"] == "250" for row in filled)
    wt = sum(row["outcome"] == "250" for row in thin)
    days = len({row["session"][:10] for row in filled})
    sessions = len({row["session"] for row in filled})
    required = (60, 6, 10, 20) if target_period == "学習" else (20, 3, 5, 10)
    support = all(actual >= minimum for actual, minimum in zip((n, days, sessions, nt), required))
    return {"候補": len(chosen), "約定": n, "250": wins, "結果別": dict(Counter(row["outcome"] for row in chosen)),
        "率": wins / n if n else None, "間引き約定": nt, "間引き250": wt, "間引き率": wt / nt if nt else None,
        "日数": days, "場数": sessions, "支持": support, "70目標": bool(support and n and nt and wins / n >= .7 and wt / nt >= .7)}
