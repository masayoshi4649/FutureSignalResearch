"""69の教師分類と共通可知pairを、実入力を使わず独立人工で検査する。"""

from copy import deepcopy
import importlib.util
import json
import math
from pathlib import Path
import sys
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("条件入口69の独立人工対象教師", HERE / "教師.py")
T = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = T
SPEC.loader.exec_module(T)


def sample_inputs() -> tuple:
    """教師に必要な最小の当時情報を、保存物を読まず作る。

    引数: なし。
    返り値: tuple[dict,dict]は判断と60特徴。方向ごとの値を意図的に変える。
    """
    slot = {"session": "2026-10-01Day", "slot_id": "人工69_000", "scheduled": 100.0, "time": 100.0, "line": 10}
    feature = {"ready": True, "vectors": {"1": [i / 100 for i in range(60)], "-1": [-i / 100 for i in range(60)]}}
    return slot, feature


def measurement(slot: dict, filled: bool = False, outcome: str = "未発動") -> dict:
    """先着と独立回収の人工辞書を明示値で作る。

    引数: slot(dict)は判断、filled(bool)は仮約定、outcome(str)は先着結果。
    返り値: dictはbarrierとoperation。戦略・教師本体の計算を呼ばない。
    """
    barrier = {"filled": filled, "outcome": outcome, "condition_outcome": "約定" if filled else outcome,
        "watch_quality": False, "end_time": 200.0, "end_line": 30,
        "entry_time": 110.0 if filled else None, "entry_line": 11 if filled else None, "entry_price": 1000.0 if filled else None}
    operation = {"final_state": {"position": None, "pending": None, "watch": None},
        "quality": {"損益確定可能": True},
        "orders": [{"kind": "entry", "status": "filled", "fill_time": 110.0, "fill_line": 11, "fill_price": 1000.0}] if filled else [],
        "closed": [{"exit_time": 190.0, "pnl0": 300.0, "pnl5": 178.0, "pnl10": 78.0}] if filled else [],
        "trades": [{"type": "LongN"}] if filled else [],
        "conditions": {slot["slot_id"]: {"status": "終了", "condition_outcome": "約定" if filled else outcome}}}
    return {"barrier": barrier, "operation": operation}


def common_inputs(count: int = 1) -> tuple:
    """任意個数の両無取引pairを、順序を固定して用意する。

    引数: count(int)は全予定枠数。
    返り値: tupleはphase/blocks/prepared/immediate/conditionalの五辞書。
    """
    slot, feature = sample_inputs()
    phase = {"id": "人工W20", "train": [{"session": slot["session"]}], "evaluation_start": 1000.0}
    blocks = {slot["session"]: {"slots": []}}
    prepared, immediate, conditional = {}, {}, {}
    for index in range(count):
        current = {**slot, "slot_id": f"人工69_{index:03d}", "time": 100.0 + index}
        blocks[slot["session"]]["slots"].append(current)
        prepared[current["slot_id"]] = deepcopy(feature)
        for side in (1, -1):
            immediate[current["slot_id"], side] = measurement(current, outcome="未約定")
            conditional[current["slot_id"], side] = measurement(current, outcome="設定否定")
    return phase, blocks, prepared, immediate, conditional


# ----------------------------------------
# 自己完結の測定辞書から、分類と共通可知集合だけを検査する。


class TeacherTests(unittest.TestCase):
    """即時と条件の分類・時点・pair除外を独立した期待値で検査する。"""

    def test_finite(self) -> None:
        """有限の実数とbool・NaN・無限・欠測を区別する。

        引数: self(TeacherTests)は検査器。
        返り値: None。
        """
        for value in (0, -1, 1.5):
            self.assertTrue(T.finite(value))
        for value in (True, False, None, "1", math.nan, math.inf, -math.inf):
            self.assertFalse(T.finite(value))

    def test_known_no_trade_zero(self) -> None:
        """新五終端と旧即時未約定を確定0にするが障壁勝敗にしない。

        引数: self(TeacherTests)は検査器。
        返り値: None。
        """
        slot, feature = sample_inputs()
        cases = [("即時", "未約定"), *(('条件', x) for x in ("既超過", "設定否定", "前提否定", "未発動", "発動未約定"))]
        for source, outcome in cases:
            data = measurement(slot, outcome=outcome)
            snapshot = deepcopy(data)
            result = T.describe(slot, feature, -1, **data, source=source)
            self.assertEqual(result["status"], "確定無取引")
            self.assertEqual(result["known_end_time"], 200.0)
            self.assertEqual(result["row"], {"session": slot["session"], "slot_id": slot["slot_id"], "side": -1,
                "features": feature["vectors"]["-1"], "filled": False, "outcome": "無取引", "end_time": 200.0,
                "recovery_end_time": 200.0, "pnl0": 0.0, "pnl5": 0.0, "pnl10": 0.0})
            self.assertEqual(data, snapshot)

    def test_filled_canonical_and_latest_end(self) -> None:
        """約定既知の回収と先着の遅い方を可知終端にする。

        引数: self(TeacherTests)は検査器。
        返り値: None。
        """
        slot, feature = sample_inputs()
        for source in ("即時", "条件"):
            for outcome in ("250", "125", "期限"):
                data = measurement(slot, True, outcome)
                data["operation"]["closed"][0]["exit_time"] = 250.0
                result = T.describe(slot, feature, 1, **data, source=source)
                self.assertEqual(result["status"], "確定約定")
                self.assertEqual(result["known_end_time"], 250.0)
                self.assertEqual(result["row"]["end_time"], 200.0)
                self.assertEqual(result["row"]["recovery_end_time"], 250.0)
                self.assertEqual([result["row"][k] for k in ("pnl0", "pnl5", "pnl10")], [300.0, 178.0, 78.0])
                result["row"]["features"][1] = 999
                self.assertEqual(feature["vectors"]["1"][1], 0.01)

    def test_unknown_is_not_zero(self) -> None:
        """不足・品質・未解消・未終了を未知としてrowなしにする。

        引数: self(TeacherTests)は検査器。
        返り値: None。
        """
        slot, feature = sample_inputs()
        variants = []
        data = measurement(slot)
        data["barrier"]["outcome"] = "不足"
        variants.append(data)
        data = measurement(slot)
        data["barrier"]["watch_quality"] = True
        variants.append(data)
        data = measurement(slot)
        data["operation"]["quality"]["損益確定可能"] = False
        variants.append(data)
        for key in ("position", "pending", "watch"):
            data = measurement(slot)
            data["operation"]["final_state"][key] = {"未解消": True}
            variants.append(data)
        for status in ("監視", "新規pending"):
            data = measurement(slot)
            data["operation"]["conditions"][slot["slot_id"]]["status"] = status
            variants.append(data)
        data = measurement(slot, True, "250")
        data["operation"]["closed"] = []
        variants.append(data)
        for data in variants:
            result = T.describe(slot, feature, 1, **data, source="条件")
            self.assertEqual((result["status"], result["row"], result["known_end_time"]), ("未知", None, None))

    def test_unready_requires_no_measurement(self) -> None:
        """未準備時は入力欠落を補完せず未知のまま返す。

        引数: self(TeacherTests)は検査器。
        返り値: None。
        """
        slot, feature = sample_inputs()
        feature["ready"] = False
        result = T.describe(slot, feature, 1, None, None, "条件")
        self.assertEqual((result["status"], result["reason"], result["row"]), ("未知", "技法未準備", None))
        feature["ready"] = True
        with self.assertRaises(ValueError):
            T.describe(slot, feature, 1, None, None, "条件")

    def test_price_clock_binding(self) -> None:
        """入口時刻・同秒原行・価格のいずれの差も拒否する。

        引数: self(TeacherTests)は検査器。
        返り値: None。
        """
        slot, feature = sample_inputs()
        for key in ("time", "line", "price"):
            data = measurement(slot, True, "250")
            data["operation"]["orders"][0]["fill_" + key] += 1
            with self.assertRaises(ValueError):
                T.describe(slot, feature, 1, **data, source="条件")
        data = measurement(slot)
        data["operation"]["conditions"][slot["slot_id"]]["condition_outcome"] = "前提否定"
        with self.assertRaises(ValueError):
            T.describe(slot, feature, 1, **data, source="条件")

    def test_measurement_contradictions(self) -> None:
        """約定有無・複数entry・無取引への実取引混入を拒否する。

        引数: self(TeacherTests)は検査器。
        返り値: None。
        """
        slot, feature = sample_inputs()
        data = measurement(slot, True, "250")
        data["barrier"]["filled"] = 1
        with self.assertRaises(ValueError):
            T.describe(slot, feature, 1, **data, source="条件")
        for key in ("orders", "closed", "trades"):
            data = measurement(slot)
            data["operation"][key] = deepcopy(measurement(slot, True, "250")["operation"][key])
            with self.assertRaises(ValueError):
                T.describe(slot, feature, 1, **data, source="条件")
        data = measurement(slot, True, "250")
        data["operation"]["orders"] *= 2
        with self.assertRaises(ValueError):
            T.describe(slot, feature, 1, **data, source="条件")

    def test_original_binding_and_line_type(self) -> None:
        """存在する元判断項目と方向を結合し原行の型も守る。

        引数: self(TeacherTests)は検査器。
        返り値: None。旧形式で省略されている項目は要求しない。
        """
        slot, feature = sample_inputs()
        for key in ("session", "slot_id", "scheduled", "time", "line", "side"):
            data = measurement(slot)
            data["barrier"].update(slot, side=1)
            if key in ("session", "slot_id"):
                data["barrier"][key] += "別"
            elif key == "side":
                data["barrier"][key] = -1
            else:
                data["barrier"][key] += 1
            with self.assertRaises(ValueError):
                T.describe(slot, feature, 1, **data, source="条件")
        for value in (None, True, 0, -1, 10.0, "10"):
            with self.assertRaises(ValueError):
                T.describe({**slot, "line": value}, feature, 1, **measurement(slot), source="条件")
        old_slot = {k: v for k, v in slot.items() if k != "line"}
        self.assertEqual(T.describe(old_slot, feature, 1, **measurement(slot), source="即時")["status"], "確定無取引")

    def test_entry_after_judgment_and_before_ends(self) -> None:
        """新規は判断後・後行、両終端は新規以後を要求する。

        引数: self(TeacherTests)は検査器。
        返り値: None。
        """
        slot, feature = sample_inputs()
        for key, value in (("time", 100.0), ("time", 99.0), ("line", 10), ("line", 9),
                           ("line", True), ("line", 11.0), ("price", 0), ("price", -1)):
            data = measurement(slot, True, "250")
            data["barrier"]["entry_" + key] = value
            data["operation"]["orders"][0]["fill_" + key] = value
            with self.assertRaises(ValueError):
                T.describe(slot, feature, 1, **data, source="条件")
        for endpoint in ("barrier", "recovery"):
            data = measurement(slot, True, "250")
            if endpoint == "barrier":
                data["barrier"]["end_time"] = 109.0
            else:
                data["operation"]["closed"][0]["exit_time"] = 109.0
            with self.assertRaises(ValueError):
                T.describe(slot, feature, 1, **data, source="条件")
        data = measurement(slot, True, "期限")
        data["barrier"]["end_time"] = data["operation"]["closed"][0]["exit_time"] = 110.0
        self.assertEqual(T.describe(slot, feature, 1, **data, source="条件")["known_end_time"], 110.0)

    def test_nonfinite_and_predecision_end(self) -> None:
        """時計・回収の非有限と原判断より前の終端を拒否する。

        引数: self(TeacherTests)は検査器。
        返り値: None。
        """
        slot, feature = sample_inputs()
        for value in (math.nan, math.inf, -math.inf, True, None):
            for key in ("pnl0", "pnl5", "pnl10", "exit_time"):
                data = measurement(slot, True, "250")
                data["operation"]["closed"][0][key] = value
                with self.assertRaises(ValueError):
                    T.describe(slot, feature, 1, **data, source="条件")
            data = measurement(slot)
            data["barrier"]["end_time"] = value
            with self.assertRaises(ValueError):
                T.describe(slot, feature, 1, **data, source="条件")
        for key in ("barrier", "recovery"):
            data = measurement(slot, True, "250")
            if key == "barrier":
                data["barrier"]["end_time"] = 99.0
            else:
                data["operation"]["closed"][0]["exit_time"] = 99.0
            with self.assertRaises(ValueError):
                T.describe(slot, feature, 1, **data, source="条件")
        data = measurement(slot)
        data["barrier"]["end_time"] = slot["time"]
        self.assertEqual(T.describe(slot, feature, 1, **data, source="条件")["status"], "確定無取引")

    def test_nonfinite_judgment_and_entry(self) -> None:
        """同じ非有限入口が両測定にあっても同値として通さない。

        引数: self(TeacherTests)は検査器。
        返り値: None。
        """
        slot, feature = sample_inputs()
        for value in (math.nan, math.inf, -math.inf, True, None):
            with self.subTest(判断時計=value):
                current = {**slot, "time": value}
                with self.assertRaises(ValueError):
                    T.describe(current, feature, 1, **measurement(slot), source="条件")
            for key in ("time", "price"):
                with self.subTest(入口=key, 値=value):
                    data = measurement(slot, True, "250")
                    data["barrier"]["entry_" + key] = value
                    data["operation"]["orders"][0]["fill_" + key] = value
                    with self.assertRaises(ValueError):
                        T.describe(slot, feature, 1, **data, source="条件")

    def test_invalid_source_and_side(self) -> None:
        """方向のboolや文字列と未定義の教師出典を拒否する。

        引数: self(TeacherTests)は検査器。
        返り値: None。
        """
        slot, feature = sample_inputs()
        for side in (0, 2, True, "1", None):
            with self.assertRaises(ValueError):
                T.describe(slot, feature, side, **measurement(slot), source="条件")
        with self.assertRaises(ValueError):
            T.describe(slot, feature, 1, **measurement(slot), source="未知出典")

    def test_both_no_trade_pair_retained(self) -> None:
        """旧新・両方向が無取引でも四行と共通一枠を保持する。

        引数: self(TeacherTests)は検査器。
        返り値: None。
        """
        inputs = common_inputs()
        before = deepcopy(inputs)
        rows, summary = T.prepare_common_pairs(*inputs)
        self.assertEqual(inputs, before)
        self.assertEqual((summary["全予定枠"], summary["共通可知枠"], summary["共通方向行"], summary["除外枠数"]), (1, 1, 2, 0))
        self.assertEqual(summary["方向重み"], 0.5)
        self.assertEqual(summary["使用分類"], {"I0": {"無取引": 2}, "C0": {"無取引": 2}})
        for policy in ("I0", "C0"):
            self.assertEqual([r["side"] for r in rows[policy]], [1, -1])
            self.assertEqual([r["pnl5"] for r in rows[policy]], [0.0, 0.0])
            self.assertEqual(sum(r["filled"] for r in rows[policy]), 0)
            self.assertFalse(any(r["outcome"] == "125" for r in rows[policy]))

    def test_one_unknown_excludes_all_four(self) -> None:
        """即時又は条件の一側が未知なら両対照のpair全体を除外する。

        引数: self(TeacherTests)は検査器。
        返り値: None。
        """
        for source in ("即時", "条件"):
            for side in (1, -1):
                inputs = common_inputs()
                selected = inputs[3] if source == "即時" else inputs[4]
                selected["人工69_000", side]["barrier"]["outcome"] = "不足"
                rows, summary = T.prepare_common_pairs(*inputs)
                self.assertEqual(rows, {"I0": [], "C0": []})
                self.assertEqual((summary["全予定枠"], summary["共通可知枠"], summary["除外枠数"]), (1, 0, 1))
                self.assertIn(source + str(side), summary["除外"][0]["理由"])

    def test_evaluation_start_strict_both_clocks(self) -> None:
        """障壁と回収の双方に評価開始strict前を要求し同秒を拒否する。

        引数: self(TeacherTests)は検査器。
        返り値: None。
        """
        for source_index in (3, 4):
            for side in (1, -1):
                for end_kind in ("barrier", "recovery"):
                    for value, expected in ((999.999, 1), (1000.0, 0), (1000.001, 0)):
                        inputs = common_inputs()
                        slot = inputs[1]["2026-10-01Day"]["slots"][0]
                        data = measurement(slot, True, "250")
                        if end_kind == "barrier":
                            data["barrier"]["end_time"] = value
                        else:
                            data["operation"]["closed"][0]["exit_time"] = value
                        inputs[source_index]["人工69_000", side] = data
                        rows, summary = T.prepare_common_pairs(*inputs)
                        self.assertEqual(summary["共通可知枠"], expected)
                        self.assertEqual(len(rows["I0"]), expected * 2)
                        self.assertEqual(len(rows["C0"]), expected * 2)

    def test_unready_not_rescued(self) -> None:
        """技法未準備を測定有りでも復帰させず共通pairから除く。

        引数: self(TeacherTests)は検査器。
        返り値: None。
        """
        inputs = common_inputs()
        inputs[2]["人工69_000"]["ready"] = False
        inputs[4].clear()
        rows, summary = T.prepare_common_pairs(*inputs)
        self.assertEqual(rows, {"I0": [], "C0": []})
        self.assertEqual(summary["全測定分類"], {"即時": {"未知": 2}, "条件": {"未知": 2}})
        self.assertEqual(summary["除外枠数"], 1)

    def test_ready_measurement_missing_rejected(self) -> None:
        """準備済み方向の新測定欠落は無取引に補完しない。

        引数: self(TeacherTests)は検査器。
        返り値: None。
        """
        inputs = common_inputs()
        del inputs[4]["人工69_000", -1]
        with self.assertRaises(ValueError):
            T.prepare_common_pairs(*inputs)

    def test_common_known_set_and_order(self) -> None:
        """教師結果は異なっても使用ID・順序・当時特徴は同一にする。

        引数: self(TeacherTests)は検査器。
        返り値: None。
        """
        inputs = common_inputs(3)
        slots = inputs[1]["2026-10-01Day"]["slots"]
        inputs[3]["人工69_000", 1] = measurement(slots[0], True, "250")
        inputs[4]["人工69_000", 1] = measurement(slots[0], True, "125")
        inputs[3]["人工69_001", -1]["operation"]["quality"]["損益確定可能"] = False
        rows, summary = T.prepare_common_pairs(*inputs)
        expected = [("人工69_000", 1), ("人工69_000", -1), ("人工69_002", 1), ("人工69_002", -1)]
        for policy in ("I0", "C0"):
            self.assertEqual([(r["slot_id"], r["side"]) for r in rows[policy]], expected)
        self.assertEqual([r["features"] for r in rows["I0"]], [r["features"] for r in rows["C0"]])
        self.assertEqual((rows["I0"][0]["outcome"], rows["C0"][0]["outcome"]), ("250", "125"))
        self.assertEqual((summary["全予定枠"], summary["共通可知枠"], summary["除外枠数"]), (3, 2, 1))

    def test_no_trade_excluded_from_barrier_denominator(self) -> None:
        """回帰四行のうち無取引二行を障壁二行の分母へ加えない。

        引数: self(TeacherTests)は検査器。
        返り値: None。独立した期待計数でfilled/outcome契約を確認する。
        """
        slot, feature = sample_inputs()
        rows = [T.describe(slot, feature, side, **measurement(slot, filled, outcome), source="条件")["row"]
            for side, filled, outcome in ((1, True, "250"), (-1, True, "125"), (1, False, "未発動"), (-1, False, "前提否定"))]
        self.assertEqual(sum(r["pnl5"] for r in rows) / len(rows), 89.0)
        barrier_rows = [r for r in rows if r["filled"]]
        self.assertEqual(len(barrier_rows), 2)
        self.assertEqual(sum(r["outcome"] == "250" for r in barrier_rows) / len(barrier_rows), 0.5)
        self.assertNotEqual(0.5, sum(r["outcome"] == "250" for r in rows) / len(rows))


# ----------------------------------------
# 正式人工レコーダーへ成功とテスト件数だけを返す。


def self_test() -> dict:
    """全人工を実行し正式レコーダー用の成功と件数を返す。

    引数: なし。
    返り値: dictは成功(bool)・テスト件数(int)。失敗時は終了1。
    """
    outcome = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(TeacherTests))
    if not outcome.wasSuccessful():
        raise SystemExit(1)
    return {"成功": True, "テスト件数": outcome.testsRun}


if __name__ == "__main__":
    print(json.dumps(self_test(), ensure_ascii=False))
