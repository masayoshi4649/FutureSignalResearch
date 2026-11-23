"""固定51の現在特徴に、既知OR二端の局所公開履歴を加える。

教師・運用・市場ファイルは読まない。価格窓は最大10本に限定し、
窓の外から状態や回数を持ち越さない。
"""

from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import importlib.util
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "定時履歴が固定参照する51特徴",
    Path(__file__).resolve().parents[1] / "技法分岐学習/特徴.py",
)
F = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(F)
SOURCE_FIELDS = F.SOURCE_FIELDS
BASE_FEATURES = deepcopy(F.FEATURES)
FEATURES = BASE_FEATURES + [
    {"id": f"F{16 + offset + index:02d}", "name": prefix + name,
     "method": method, "family": "price", "scale": "m03+m30"}
    for offset, prefix in ((0, "自方向端の"), (5, "反対方向端の"))
    for index, (name, method) in enumerate((
        ("最終内外状態", "P06"), ("外切替回数", "P03"), ("内切替回数", "P09"),
        ("最終切替符号", "P10"), ("最終切替後足数対10", "P10")))
]


def endpoint_history(window: list[dict], level: float, direction: int) -> dict:
    """検証済みの窓内終値から、一端の内外状態と切替を精密に数える。

    引数: window(list[dict])は順序検証済みの完全公開窓、level(float)は固定OR端、
        direction(int)は上端+1又は下端−1。
    返り値: dictは種・最終状態・切替数・最終経過と5特徴。
        初めて明瞭な側へ入る観測は種とし、切替へ含めない。
    """
    if not window or direction not in (-1, 1):
        raise ValueError("履歴には空でない窓と端方向±1が必要")
    state, initial, seed_index, seed_state = 0, 0, None, 0
    out_count, in_count, last_sign, last_index = 0, 0, 0, None
    boundary = Fraction(level)
    for position, row in enumerate(window):
        value = direction * (Fraction(row["close"]) - boundary)
        clear = 1 if value >= 5 else -1 if value <= -5 else 0
        if position == 0:
            initial = clear
        if clear:
            if state == 0:
                seed_index, seed_state = row["index"], clear
            elif clear != state:
                out_count += int(clear == 1)
                in_count += int(clear == -1)
                last_sign, last_index = clear, row["index"]
            state = clear
    age = window[-1]["index"] - last_index if last_index is not None else None
    scaled = float(Fraction(age, 10)) if age is not None else -1.0
    return {"direction": direction, "level": level, "initial_state": initial,
            "seed_index": seed_index, "seed_state": seed_state, "final_state": state,
            "out_count": out_count, "in_count": in_count,
            "last_change_sign": last_sign, "last_change_index": last_index,
            "age_bars": age, "age_scaled": scaled,
            "values": [state, out_count, in_count, last_sign, scaled]}


def _required_sources(frames3: object, required: set[int]) -> tuple[dict, str]:
    """必要な番号だけを正本SOURCEから一意に取り出す。

    引数: frames3(object)は当場SOURCE配列、required(set[int])はORと現在窓の番号。
    返り値: tuple[dict,str]は番号から元行への写像と不正理由。
        窓外・未来番号の有無を現在の特徴へ反映しない。
    """
    if not isinstance(frames3, list):
        return {}, "正本3分SOURCE配列なし"
    selected = {}
    for row in frames3:
        if not isinstance(row, dict):
            continue
        index = row.get("index")
        if type(index) is not int or index not in required:
            continue
        if index in selected:
            return {}, "必要な正本3分足番号が重複"
        selected[index] = row
    if set(selected) != required:
        return {}, "OR又は履歴窓の正本3分出典不足"
    return selected, ""


# ----------------------------------------
# 旧51の現在特徴と履歴の準備を分け、対照も同じ履歴準備へ限定する。

def extract(slot: dict, frames3: list[dict]) -> dict:
    """固定現在15特徴と二端履歴10特徴を同じ時点で返す。

    引数: slot(dict)は50保存P0slot、frames3(list[dict])は固定28由来の当場SOURCE13。
    返り値: dictはready/reason/base/vectors/control_vectors/atr/D/
        background_direction/history。未準備は両方の方向配列を空にする。
    """
    base = F.extract(slot)
    result = {"ready": False, "reason": "", "base": base,
              "vectors": {"1": [], "-1": []}, "control_vectors": {"1": [], "-1": []},
              "atr": base["atr"], "D": base["D"],
              "background_direction": base["background_direction"],
              "history": {"window_sources": [], "upper": None, "lower": None,
                          "start_index": None, "end_index": None, "source_count": 0}}
    if not base["ready"]:
        result["reason"] = "基礎特徴未準備: " + base["reason"]
        return result
    current = base["sources"]["current"]
    end_index, session = current["index"], current["session"]
    start_index = max(9, end_index - 9)
    result["history"].update(start_index=start_index, end_index=end_index)
    if end_index < 9:
        result["reason"] = "現3分足がOR最終足より前"
        return result
    required = set(range(10)) | set(range(start_index, end_index + 1))
    selected, reason = _required_sources(frames3, required)
    if reason:
        result["reason"] = reason
        return result
    limit = (slot["time"], slot["line"])
    for index in sorted(required):
        reason = F._source_reason(selected[index], session, 3, slot["scheduled"], limit)
        if reason:
            result["reason"] = "正本3分: " + reason
            return result
    canonical = {index: F.I49.source(row) for index, row in selected.items()}
    if canonical[end_index] != current:
        result["reason"] = "現3分と正本SOURCE不一致"
        return result
    for index, source in enumerate(slot["OR"]["sources"]):
        if canonical[index] != F.I49.source(source):
            result["reason"] = "OR10本と正本SOURCE不一致"
            return result
    window = [canonical[index] for index in range(start_index, end_index + 1)]
    if not all(F.I49.adjacent(p, c) for p, c in zip(window, window[1:])):
        result["reason"] = "履歴3分窓の番号・終了・公開順不連続"
        return result
    upper = endpoint_history(window, slot["OR"]["high"], 1)
    lower = endpoint_history(window, slot["OR"]["low"], -1)
    result["history"].update(window_sources=deepcopy(window), upper=upper, lower=lower,
                             source_count=len(window),
                             opening_range_latest_key=deepcopy(base["sources"]["OR"]["latest_key"]))
    result["control_vectors"] = deepcopy(base["vectors"])
    result["vectors"] = {
        "1": base["vectors"]["1"] + upper["values"] + lower["values"],
        "-1": base["vectors"]["-1"] + lower["values"] + upper["values"],
    }
    result.update(ready=True, reason="")
    return result
