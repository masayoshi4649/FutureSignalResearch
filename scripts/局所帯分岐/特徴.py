"""固定現在15特徴と、反応前に固定する局所帯の文脈・反応旗を作る。

市場・教師・保有・損益を読まない。参照10本と反応5本を混ぜず、
旧51の準備や数値を変更しない。
"""

from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import importlib.util
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "局所帯分岐が固定参照する51特徴",
    Path(__file__).resolve().parents[1] / "技法分岐学習/特徴.py")
F = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(F)
SOURCE_FIELDS = F.SOURCE_FIELDS
BASE_FEATURES = deepcopy(F.FEATURES)
FEATURES = BASE_FEATURES + [
    {"id": "F16", "name": "局所参照帯幅対ATR", "method": "P03", "family": "price", "scale": "m03"},
    {"id": "F17", "name": "実方向の局所帯中央距離", "method": "P06", "family": "price", "scale": "m03"},
    {"id": "F18", "name": "局所帯の自方向継続又は反対端内復帰", "method": "P10", "family": "price", "scale": "m03"},
]


def reaction_state(rows: list[dict], level: float, direction: int) -> dict:
    """帯内アンカーを種とし、反応終値だけの二端遷移を数える。

    引数: rows(list[dict])は検証済み反応5足、level(float)は固定端、
        direction(int)は上端+1又は下端−1。
    返り値: dictはinitial_state/states/events/最終状態・回数・最終経過。
        初期inside−1は参照末終値の帯内という新規約で、neutral種ではない。
    """
    if len(rows) != 5 or direction not in (-1, 1):
        raise ValueError("反応には5足と端方向±1が必要")
    state, out_count, in_count, last_index, last_sign = -1, 0, 0, None, 0
    states, events = [], []
    for row in rows:
        distance = direction * (Fraction(row["close"]) - Fraction(level))
        zone = 1 if distance >= 5 else -1 if distance <= -5 else 0
        after = zone if zone else state
        if after != state:
            events.append({"index": row["index"], "from": state, "to": after,
                           "sign": after, "key": [row["confirm"], row["confirm_line"]]})
            out_count += int(after == 1)
            in_count += int(after == -1)
            last_index, last_sign = row["index"], after
        state = after
        states.append({"index": row["index"], "zone": zone, "state": state})
    age = rows[-1]["index"] - last_index if last_index is not None else None
    return {"direction": direction, "level": level, "initial_state": -1,
            "states": states, "events": events, "final_state": state,
            "out_count": out_count, "in_count": in_count,
            "last_change_sign": last_sign, "last_change_index": last_index,
            "age_bars": age}


def _sources(frames: object, required: set[int]) -> tuple[dict, str]:
    """参照・反応・ORの必要番号を正本から一意に取り出す。

    引数: frames(object)は当場SOURCE13配列、required(set[int])は必要番号。
    返り値: tuple[dict,str]は番号写像と不備理由。窓外の過去・未来は選ばない。
    """
    if not isinstance(frames, list):
        return {}, "正本3分SOURCE配列なし"
    selected = {}
    for row in frames:
        if not isinstance(row, dict) or type(row.get("index")) is not int:
            continue
        index = row["index"]
        if index not in required:
            continue
        if index in selected:
            return {}, "必要な正本3分足番号が重複"
        selected[index] = row
    if set(selected) != required:
        return {}, "局所帯又はORの正本3分出典不足"
    return selected, ""


# ----------------------------------------
# 準備は共通にし、局所幅・位置の対照と反応旗追加の差だけを返す。

def extract(slot: dict, frames3: list[dict]) -> dict:
    """固定15特徴へ局所帯文脈2列と反応旗1列を加える。

    引数: slot(dict)は50保存P0slot、frames3(list[dict])は固定28由来SOURCE13。
    返り値: dictはready/reason/base/control_vectors17/vectors18/atr/D/
        background_direction/history。未知は両方向空配列、Z0は有効値。
    """
    base = F.extract(slot)
    result = {"ready": False, "reason": "", "base": base,
              "control_vectors": {"1": [], "-1": []}, "vectors": {"1": [], "-1": []},
              "atr": base["atr"], "D": base["D"],
              "background_direction": base["background_direction"],
              "history": {"reference_sources": [], "reaction_sources": [], "band": None,
                          "upper": None, "lower": None, "contexts": {"1": None, "-1": None}}}
    if not base["ready"]:
        result["reason"] = "基礎特徴未準備: " + base["reason"]
        return result
    current = base["sources"]["current"]
    j = current["index"]
    if j < 14:
        result["reason"] = "局所参照と反応にはindex14以降が必要"
        return result
    reference_indices = list(range(j - 14, j - 4))
    reaction_indices = list(range(j - 4, j + 1))
    result["history"].update(reference_indices=reference_indices, reaction_indices=reaction_indices)
    required = set(range(10)) | set(reference_indices) | set(reaction_indices)
    selected, reason = _sources(frames3, required)
    if reason:
        result["reason"] = reason
        return result
    limit = slot["time"], slot["line"]
    for index in sorted(required):
        reason = F._source_reason(selected[index], current["session"], 3, slot["scheduled"], limit)
        if reason:
            result["reason"] = "正本3分: " + reason
            return result
    canonical = {index: F.I49.source(row) for index, row in selected.items()}
    if canonical[j] != current:
        result["reason"] = "現3分と正本SOURCE不一致"
        return result
    if any(canonical[index] != F.I49.source(row) for index, row in enumerate(slot["OR"]["sources"])):
        result["reason"] = "OR10本と正本SOURCE不一致"
        return result
    all_rows = [canonical[index] for index in reference_indices + reaction_indices]
    if not all(F.I49.adjacent(p, c) for p, c in zip(all_rows, all_rows[1:])):
        result["reason"] = "局所15本の番号・終了・公開順不連続"
        return result
    reference, reaction = all_rows[:10], all_rows[10:]
    high = max(Fraction(row["high"]) for row in reference)
    low = min(Fraction(row["low"]) for row in reference)
    midpoint, width = (high + low) / 2, high - low
    anchor = Fraction(reference[-1]["close"])
    if not low <= anchor <= high:
        raise ValueError("有効参照足の終値が参照帯外")
    upper = reaction_state(reaction, float(high), 1)
    lower = reaction_state(reaction, float(low), -1)
    contexts, controls, vectors = {}, {}, {}
    for side in (1, -1):
        own, opposite = (upper, lower) if side == 1 else (lower, upper)
        continuation = own["out_count"] > 0 and own["final_state"] == 1
        returned = opposite["in_count"] > 0 and opposite["final_state"] == -1
        contexts[str(side)] = {"own_continuation": continuation, "opposite_return": returned,
                               "z": int(continuation or returned)}
        try:
            control = base["vectors"][str(side)] + [
                float(width / Fraction(base["atr"])),
                float(side * (Fraction(current["close"]) - midpoint) / Fraction(base["atr"])),
            ]
        except OverflowError:
            result["reason"] = "局所帯特徴のfloat表示範囲外"
            return result
        if not all(F.I49.finite(value) for value in control):
            result["reason"] = "局所帯特徴の有限値不成立"
            return result
        controls[str(side)] = control
        vectors[str(side)] = control + [contexts[str(side)]["z"]]
    result["history"].update(reference_sources=deepcopy(reference), reaction_sources=deepcopy(reaction),
        band={"low": float(low), "high": float(high), "mid": float(midpoint), "width": float(width),
              "reference_close": reference[-1]["close"], "initial_inside": True,
              "fixed_at_key": list(F.I49.key(reference[-1])),
              "first_reaction_key": list(F.I49.key(reaction[0]))},
        upper=upper, lower=lower, contexts=contexts)
    result.update(control_vectors=controls, vectors=vectors)
    result.update(ready=True, reason="")
    return result
