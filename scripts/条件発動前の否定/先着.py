"""固定67の独立先着へ、発動前の反対端否定二種類だけを追加する。"""

from bisect import bisect_left, bisect_right
from copy import deepcopy
import importlib.util
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def load(path: Path, name: str):
    """固定67の純算術を固有名で読む。

    引数: path(Path)はPython、name(str)は固有名。
    返り値: ModuleTypeは読込結果。旧大域値を変更しない。
    """
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LEGACY=load(ROOT/'scripts/定時候補の価格発動/先着.py','発動前否定68の固定67先着')
prepare_events,validate_condition=LEGACY.prepare_events,LEGACY.validate_condition
normal,trigger_normal,timer_line,gap_arrival,barrier=LEGACY.normal,LEGACY.trigger_normal,LEGACY.timer_line,LEGACY.gap_arrival,LEGACY.barrier
BINDING,SOURCE_FIELDS=LEGACY.BINDING,LEGACY.SOURCE_FIELDS
entry_stats=LEGACY.entry_stats

# ----------------------------------------
# 設定と監視の否定だけを追加し、発動後の約定と障壁を変更しない。

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
    opposite = condition["low"] if side == 1 else condition["high"]
    if side * (setting["last"] - opposite) <= 0:
        result.update(condition_outcome="設定否定", condition_reason="設定時に反対端を否定", outcome="設定否定", end_time=slot["time"], end_line=slot["line"])
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
        if side * (event["last"] - opposite) <= 0:
            result.update(condition_outcome="前提否定", condition_reason="発動前に反対端を否定", outcome="前提否定", end_time=event["now"], end_line=event["line"])
            return result
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

