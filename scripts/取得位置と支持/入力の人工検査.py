"""取得位置の時計・鏡像・未知と既存特徴の不変を人工で検査する。"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("取得位置71の人工入力", HERE / "入力.py")
I = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = I
SPEC.loader.exec_module(I)


def fixture() -> tuple:
    """市場と無関係な完全足・判断気配を用意する。

    引数: なし。
    返り値: tuple[dict,dict,dict]は判断/旧60/BBO。
    """
    slot = {"session": "人工Day", "slot_id": "人工Day_900", "scheduled": 900.0, "time": 901.0, "line": 10}
    upper = {"session": "人工Day", "index": 0, "minutes": 15, "start": 0.0, "end": 900.0,
        "confirm": 900.0, "confirm_line": 9, "publish": True, "missing": 0,
        "open": 109.0, "high": 120.0, "low": 100.0, "close": 110.0}
    feature = {"ready": True, "reason": "人工", "atr": 10.0, "D": 10.0,
        "vectors": {"1": [0.0] * 60, "-1": [0.0] * 60},
        "base": {"base": {"sources": {"upper": upper, "current": {"end": 900.0, "close": 110.0}}}}}
    quote = {"now": 901.0, "line": 10, "valid": True, "bid": 110.0, "ask": 115.0, "last": None}
    return slot, feature, quote


def rejected(slot: dict, feature: dict, quote: dict | None) -> None:
    """不正な入力を既知0へ変えず拒否することを確認する。

    引数: slot/feature(dict)とquote(dict|None)は不正に変更した入力。
    返り値: None。受理した場合はAssertionError。
    """
    try:
        I.extend_position(slot, feature, quote)
    except ValueError:
        return
    raise AssertionError("不正入力を受理")


def self_test() -> dict:
    """価格反射・公開同秒・未知・代数関係を独立した人工値で確かめる。

    引数: なし。
    返り値: dictは成功とテスト群数。実入力・学習・市場は読まない。
    """
    slot, feature, quote = fixture()
    before = deepcopy((slot, feature, quote))
    result = I.extend_position(slot, feature, quote)
    assert result["vectors"]["1"][-1] == 0.5 and result["vectors"]["-1"][-1] == 1.0
    assert I.base_projection(result) == feature and (slot, feature, quote) == before
    assert result["position"]["same_end"] and result["position"]["same_close"]
    # ----------------------------------------
    # 価格反射で方向を交換すると値が一致する。同じ枠の売買は互いの負ではない。
    mirror = deepcopy(feature)
    upper = mirror["base"]["base"]["sources"]["upper"]
    high, low = upper["high"], upper["low"]
    upper.update(open=300-upper["open"], close=300-upper["close"], high=300-low, low=300-high)
    mirror["base"]["base"]["sources"]["current"]["close"] = 190.0
    mirrored = I.extend_position(slot, mirror, {**quote, "bid": 185.0, "ask": 190.0})
    assert mirrored["vectors"]["1"][-1] == result["vectors"]["-1"][-1]
    assert mirrored["vectors"]["-1"][-1] == result["vectors"]["1"][-1]
    assert sum(result["vectors"][s][-1] for s in ("1", "-1")) == 1.5
    # ----------------------------------------
    # 零・負・端の外を保持し、Lastは不要な条件にしない。
    zero = I.extend_position(slot, feature, {**quote, "ask": 120.0})
    negative = I.extend_position(slot, feature, {**quote, "bid": 120.0, "ask": 125.0})
    assert zero["vectors"]["1"][-1] == 0.0 and negative["vectors"]["1"][-1] == -0.5
    assert negative["position"]["values"]["1"]["exact"] == "-1/2"
    absent = {"ready": False, "vectors": {"1": [], "-1": []}, "reason": "人工未準備"}
    assert I.extend_position(slot, absent, None) == absent
    rejected(slot, feature, None)
    # ----------------------------------------
    # 公開同秒の後行、未来足、未公開・欠測・古すぎる足を拒否する。
    for changes in ({"confirm": 901.0, "confirm_line": 11}, {"start": 900.0, "end": 1800.0, "confirm": 1800.0},
                    {"publish": False}, {"missing": 1}, {"start": -901.0, "end": -1.0, "confirm": -1.0}):
        bad = deepcopy(feature)
        bad["base"]["base"]["sources"]["upper"].update(changes)
        rejected(slot, bad, quote)
    equal = deepcopy(feature)
    equal["base"]["base"]["sources"]["upper"].update(confirm=901.0, confirm_line=10)
    assert I.extend_position(slot, equal, quote)["vectors"]["1"][-1] == 0.5
    for changes in ({"valid": False}, {"ask": 110.0}, {"ask": float("inf")}, {"bid": True},
                    {"now": 902.0}, {"line": 11}, {"line": True}):
        rejected(slot, feature, {**quote, **changes})
    # ----------------------------------------
    # 判断の5項目と両方向気配を結合し、将来ラベルを出力に持ち込まない。
    immediate = {(slot["slot_id"], s): {**slot, "side": s, "decision_bbo": deepcopy(quote), "未来値": 999} for s in (1, -1)}
    assert I.quote_for(slot, immediate) == quote
    bad = deepcopy(immediate)
    bad[slot["slot_id"], -1]["decision_bbo"]["ask"] = 116.0
    try:
        I.quote_for(slot, bad)
    except ValueError:
        pass
    else:
        raise AssertionError("両方向の異なる気配を受理")
    bad = deepcopy(immediate)
    bad[slot["slot_id"], -1]["scheduled"] = 899.0
    try:
        I.quote_for(slot, bad)
    except ValueError:
        pass
    else:
        raise AssertionError("5項目の結合差を受理")
    return {"成功": True, "テスト件数": 6, "実入力読取": False, "本物fit": False, "市場再生": False}


if __name__ == "__main__":
    print(json.dumps(self_test(), ensure_ascii=False))
