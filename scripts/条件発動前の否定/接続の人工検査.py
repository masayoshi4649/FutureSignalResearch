"""凍結価格の当時可視性と新旧候補接続を人工入力で確認する。"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("条件発動68接続人工", HERE / "検証.py")
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)


def fixture() -> tuple:
    """判断と同じ公開keyを持つ完全3分足の人工入力を作る。

    引数: なし。
    返り値: tuple[dict,list[dict]]はslotと当場足。市場データを読まない。
    """
    session = "2026-10-05_Day"
    now = P.O.scheduled_times(session)[0]
    row = {"index": 9, "minutes": 3, "start": now - 180, "end": now,
        "confirm": now, "confirm_line": 10, "publish": True, "missing": 0,
        "open": 100.0, "high": 110.0, "low": 90.0, "close": 102.0}
    source = {**row, "session": session}
    slot = {"session": session, "slot_id": "人工", "scheduled": now, "time": now, "line": 10,
        "side": 1, "role": "順行", "ready": True, "atr": 25.0, "D": 25.0,
        "feature": {"base": {"base": {"sources": {"current": source}}}}}
    return slot, [row]


def rejected(slot: dict, rows: list[dict]) -> bool:
    """不正な価格出典が条件化を拒否されるか調べる。

    引数: slot(dict)とrows(list[dict])は人工出典。
    返り値: boolはValueErrorならTrue。
    """
    try:
        P.condition_for(slot, rows)
    except ValueError:
        return True
    return False


def self_test() -> dict:
    """公開境界、未来足、最新足、欠測と売買鏡像を検査する。

    引数: なし。
    返り値: dictは8件の結果。市場・教師・fitなし。
    """
    slot, rows = fixture()
    before = deepcopy((slot, rows))
    condition = P.condition_for(slot, rows)
    assert condition["high"] == 110 and condition["low"] == 90
    assert condition["expires"] == slot["scheduled"] + 900 and (slot, rows) == before
    future_slot = deepcopy(slot)
    future_slot["feature"]["base"]["base"]["sources"]["current"]["confirm_line"] = 11
    assert rejected(future_slot, [{**rows[0], "confirm_line": 11}])
    future = {**rows[0], "index": 10, "start": slot["time"], "end": slot["time"] + 180,
        "confirm": slot["time"] + 180, "confirm_line": 20, "high": 999}
    assert P.condition_for(slot, rows + [future]) == condition
    older = {**rows[0], "index": 8, "start": rows[0]["start"] - 180, "end": rows[0]["end"] - 180,
        "confirm": rows[0]["confirm"] - 180, "confirm_line": 8}
    older_slot = deepcopy(slot)
    older_slot["feature"]["base"]["base"]["sources"]["current"] = {**older, "session": slot["session"]}
    assert rejected(older_slot, [older, *rows])
    missing_slot = deepcopy(slot)
    missing_slot["feature"]["base"]["base"]["sources"]["current"]["missing"] = 1
    assert rejected(missing_slot, [{**rows[0], "missing": 1}])
    mirrored = deepcopy(slot)
    mirrored["side"] = -1
    assert P.condition_for(mirrored, rows) == condition
    # ----------------------------------------
    # 非否定の保存同値と、否定で失う旧成功も全候補へ残す。
    before = {"session": slot["session"], "slot_id": "残る", "policy": "G0", "side": 1,
        "filled": True, "condition_outcome": "約定", "outcome": "250", "trigger": {"time": 10, "line": 2, "last": 100},
        "entry_time": 11, "entry_line": 3, "entry_price": 101, "end_time": 20, "end_line": 4, "mfe": 250, "mae": -5,
        "watch_quality": False}
    denied_old = {**deepcopy(before), "slot_id": "除外"}
    kept = {**deepcopy(before), "policy": "N0"}
    denied = {**deepcopy(denied_old), "policy": "N0", "filled": False, "trigger": None,
        "condition_outcome": "前提否定", "outcome": "前提否定"}
    result = P.denial_stats([kept, denied], [before, denied_old], "学習")
    assert result == {"同じ純候補": 2, "設定否定": 0, "前提否定": 1, "非否定の全属性一致": 1,
        "否定群の旧結果": {"約定/250": 1}, "旧仮約定の除外": 1, "旧250の除外": 1, "旧125の除外": 0,
        "両約定の時刻価格結果一致": 1, "新のみ仮約定": 0}
    changed = {**kept, "entry_price": 102}
    try:
        P.denial_stats([changed], [before], "学習")
    except ValueError:
        pass
    else:
        raise AssertionError("非否定の取得変化を見逃した")
    return {"成功": True, "テスト件数": 8, "実入力読取": False, "市場再生": False, "fit": 0}


if __name__ == "__main__":
    print(json.dumps(self_test(), ensure_ascii=False))
