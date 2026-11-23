"""実市場入力を開かず、同時刻量と価格段階の因果境界を確認する。"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path


SPEC = importlib.util.spec_from_file_location("数量特徴の人工専用", Path(__file__).with_name("特徴.py"))
F = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(F)


def sample(number: int, q: float, kind: str = "Day", contract: str = "A") -> tuple:
    """3本の価格足と完全性付き観測量を人工生成する。

    引数: number(int)は時系列番号、q(float)は各足量、kind/contract(str)は場種/限月。
    返り値: tuple[dict,list[dict]]は場メタデータと数量出典。
    """
    begin = 1_000_000.0 + number * 86400
    name = f"2026-01-{number + 1:02d}_{kind}"
    rows = []
    for i in range(3):
        start, close = begin + 180 * i, 100.0 + 5 * i
        row = {"session": name, "index": i, "minutes": 3, "start": start, "end": start + 180,
            "confirm": start + 181, "confirm_line": i * 20 + 19, "publish": True, "missing": 0,
            "open": close - 1, "high": close + 2, "low": close - 2, "close": close}
        quantity = {"観測差分量": q, "数量基準完全": i > 0, "直前数量足数": 0,
            "直前数量合計": 0.0, "直前数量平均": None, "RVOL": None, "数量準備済": False,
            "最終採用数量時計": start + 90, "最終採用価格時計": start + 90,
            "最終採用原行": i * 20 + 9, "数量不完全理由": [] if i else ["セッション最初の数量足"]}
        rows.append({**row, "quantity": quantity})
    return {"session": name, "begin": begin, "end": begin + 600, "contract": (contract,),
        "frames3": [F.source(r) for r in rows], "frames15": []}, rows


def inputs(count: int = 6) -> tuple:
    """同種・同限月の時系列と量行を作る。

    引数: count(int)は人工場数。
    返り値: tuple[list[dict],dict]はモデルや損益を含まない入力。
    """
    made = [sample(i, float(10 * (i + 1))) for i in range(count)]
    return [s for s, _ in made], {s["session"]: rows for s, rows in made}


def feature(session: dict, rows: list[dict]) -> tuple:
    """旧54の準備済み枠と保持b/rだけを作る。

    引数: session(dict)は場、rows(list[dict])は出典。
    返り値: tuple[dict,dict]は判断枠と旧特徴。旧数値の学習検査は別責務。
    """
    refs = {name: {"index": i, "key": [rows[i]["confirm"], rows[i]["confirm_line"]]}
        for name, i in (("b", 1), ("r", 2))}
    slot = {"session": session["session"], "scheduled": session["begin"] + 540,
        "time": session["begin"] + 541, "line": 100, "slot_id": "人工"}
    old = {"ready": True, "reason": "人工準備", "atr": 20.0, "D": 20.0,
        "vectors": {"1": [0.4] + [0.0] * 53, "-1": [-0.4] + [0.0] * 53},
        "paths": {s: {r: deepcopy(refs) for r in ("T", "R")} for s in ("1", "-1")}}
    return slot, old


def rejects(callable_value) -> None:
    """不正入力がValueErrorで拒否されることを確認する。

    引数: callable_value(callable)は引数なしの人工操作。
    返り値: None。拒否されない場合AssertionError。
    """
    try:
        callable_value()
    except ValueError:
        return
    raise AssertionError("不正入力を受理")


def self_test() -> dict:
    """量・価格・公開時刻・役割投影の独立境界を人工確認する。

    引数: なし。
    返り値: dictは成功とケース名。本物データ・教師・モデルを開かない。
    """
    tests = []
    sessions, quantity = inputs()
    before = deepcopy((sessions, quantity))
    context = F.build_context(sessions, quantity)
    name = sessions[-1]["session"]
    assert context[name][1]["baseline"]["mean"] == 30.0 and context[name][1]["rvol"] == 2.0
    slot, old = feature(sessions[-1], context[name])
    new = F.extend(slot, old, context[name])
    assert new["vectors"]["1"][-6:] == [2.0, 0.25, 2.0, 0.25, 1, 1]
    assert new["vectors"]["-1"][-6:] == [2.0, -0.25, 2.0, -0.25, 1, 1]
    assert F.control_projection(new) == old and (sessions, quantity) == before
    tests.append("同時刻平均と量価格分離・射影・非破壊")

    # ----------------------------------------
    # 最低基準・既知0・時間窓は別の境界とする。
    short = F.build_context(sessions[:5], {s["session"]: quantity[s["session"]] for s in sessions[:5]})
    assert short[sessions[4]["session"]][1]["rvol"] is None
    zeros = deepcopy(quantity)
    zeros[name][1]["quantity"]["観測差分量"] = 0.0
    known = F.extend(slot, old, F.build_context(sessions, zeros)[name])
    assert known["vectors"]["1"][54] == 0 and known["vectors"]["1"][58] == 1
    for s in sessions[:-1]:
        zeros[s["session"]][1]["quantity"]["観測差分量"] = 0.0
    absent = F.extend(slot, old, F.build_context(sessions, zeros)[name])
    assert absent["vectors"]["1"][54:56] == [0.0, 0.0] and absent["vectors"]["1"][58] == 0
    assert absent["quantity"]["1"]["b"]["progress"] == 0.25
    tests.append("5場準備と既知0と平均0")

    many, qmany = inputs(12)
    for s in many[1:7]:
        qmany[s["session"]][1]["quantity"]["数量基準完全"] = False
    last = F.build_context(many, qmany)[many[-1]["session"]][1]
    assert last["baseline"]["window_sessions"] == [s["session"] for s in many[1:11]]
    assert last["baseline"]["count"] == 4 and last["rvol"] is None
    tests.append("直近10場固定・欠測で窓を延長しない")

    extra, erows = sample(6, 999.0, "Night")
    changed, crows = sample(7, 999.0, "Day", "B")
    combined = F.build_context(sessions + [extra, changed], {**quantity, extra["session"]: erows, changed["session"]: crows})
    assert combined[extra["session"]][1]["baseline"]["count"] == 0
    assert combined[changed["session"]][1]["baseline"]["count"] == 0 and combined[name] == context[name]
    tests.append("場種限月分離・未来追加不変")

    bad_sessions = deepcopy(sessions)
    bad_sessions[-2]["end"] = bad_sessions[-1]["begin"]
    rejects(lambda: F.build_context(bad_sessions, quantity))
    bad = deepcopy(quantity)
    bad[sessions[0]["session"]][1]["confirm"] = sessions[-1]["begin"]
    linked = deepcopy(sessions)
    linked[0]["frames3"][1]["confirm"] = sessions[-1]["begin"]
    rejects(lambda: F.build_context(linked, bad))
    tests.append("完了時刻と公開時刻の開始同秒を拒否")

    # ----------------------------------------
    # 原出典と公開順が正しいことを量の大きさより先に確認する。
    bad = deepcopy(quantity)
    bad[name][1]["quantity"]["最終採用数量時計"] += 1
    rejects(lambda: F.build_context(sessions, bad))
    bad = deepcopy(quantity)
    bad[name][1]["quantity"]["最終採用原行"] = bad[name][1]["confirm_line"]
    rejects(lambda: F.build_context(sessions, bad))
    bad = deepcopy(quantity)
    bad[name][1]["close"] += 1
    rejects(lambda: F.build_context(sessions, bad))
    tests.append("量時計先行・確認行量混入・SOURCE改竄拒否")

    missing = deepcopy(quantity)
    missing[name][1]["quantity"]["数量基準完全"] = False
    unavailable = F.extend(slot, old, F.build_context(sessions, missing)[name])
    assert unavailable["vectors"]["1"][54:56] == [0.0, 0.0] and unavailable["ready"]
    no_stage = deepcopy(old)
    no_stage["paths"]["1"]["T"]["r"] = None
    no_r = F.extend(slot, no_stage, context[name])
    assert no_r["quantity"]["1"]["r"]["reason"] == "段階なし"
    early = {**slot, "scheduled": slot["scheduled"] - 180, "time": slot["time"] - 180, "line": 39}
    rejects(lambda: F.extend(early, old, context[name]))
    tests.append("数量未知と段階なしを分離・未来イベント拒否")

    missing_prev = deepcopy(context[name])
    missing_prev[0]["publish"] = False
    np = F.extend(slot, old, missing_prev)
    assert np["quantity"]["1"]["b"]["previous_source"] is None
    assert np["vectors"]["1"][58] == 0 and np["vectors"]["1"][59] == 1
    tests.append("非公開前足を診断からも除外")

    # ----------------------------------------
    # 反射後の逆sideが同じ量価格情報を持つことと微小DIの枝を確認する。
    mirror_sessions, mirror_q = deepcopy((sessions, quantity))
    for s in mirror_sessions:
        for r in mirror_q[s["session"]]:
            o, h, l, c = (r[k] for k in ("open", "high", "low", "close"))
            r.update(open=1000-o, high=1000-l, low=1000-h, close=1000-c)
        s["frames3"] = [F.source(r) for r in mirror_q[s["session"]]]
    reflected = F.build_context(mirror_sessions, mirror_q)
    other = deepcopy(old)
    other["vectors"] = {s: deepcopy(old["vectors"][str(-int(s))]) for s in ("1", "-1")}
    swapped = F.extend(slot, other, reflected[name])
    assert swapped["vectors"]["-1"] == new["vectors"]["1"]
    assert swapped["vectors"]["1"] == new["vectors"]["-1"]
    assert F.branch_role(1e-50) == "R" and F.branch_role(0.4) == "T"
    tests.append("売買鏡像・float32微小正の零化")

    unready = {"ready": False, "vectors": {"1": [], "-1": []}}
    extended = F.extend(slot, unready, [])
    assert extended["quantity"] == {} and F.control_projection(extended) == unready
    tests.append("旧未準備を変更しない")
    return {"成功": True, "テスト件数": len(tests), "ケース": tests, "本物入力読取": False}


if __name__ == "__main__":
    print(json.dumps(self_test(), ensure_ascii=False))
