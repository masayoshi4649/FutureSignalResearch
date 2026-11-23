"""凍結価格の当時可視性と新旧候補接続を人工入力で確認する。"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("条件発動67接続人工", HERE / "検証.py")
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
    返り値: dictは6件の結果。市場・教師・fitなし。
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
    return {"成功": True, "テスト件数": 6, "実入力読取": False, "市場再生": False, "fit": 0}


if __name__ == "__main__":
    print(json.dumps(self_test(), ensure_ascii=False))
