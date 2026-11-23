"""68の価格否定だけを、固定67との同値と手書き境界で検査する。"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("条件発動前否定68の人工運用", HERE / "運用.py")
O = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = O
SPEC.loader.exec_module(O)
BOUNDS = {"start": 0, "force": 1000, "end": 1010}


def events(rows: list[tuple]) -> list[dict]:
    """手書き経路へ原行番号と元valid旗を与える。

    引数: rows(list[tuple])はnow/last/bid/askと任意valid。
    返り値: list[dict]は市場を含まない最小6列。
    """
    return [{"now": row[0], "line": index, "last": row[1], "bid": row[2], "ask": row[3],
        "valid": row[4] if len(row) == 5 else True} for index, row in enumerate(rows, 1)]


def slot(now: float = 0, line: int | None = 1, side: int = 1,
        ready: bool = True, slot_id: str = "枠1") -> dict:
    """固定67互換の純判断だけを作る。

    引数: now(float)/line(int|None)は出典、side(int)/ready(bool)は判断、slot_id(str)は識別。
    返り値: dictは未来値なしのslot。
    """
    return {"scheduled": now, "time": now, "line": line, "side": side,
        "role": "順行", "atr": 20, "D": 20, "reason": "人工複合候補", "ready": ready, "slot_id": slot_id}


def condition(item: dict, high: float = 110, low: float = 90) -> dict:
    """元予定+900の固定価格条件を作る。

    引数: item(dict)は元枠、high/low(float)は当時の端。
    返り値: dictは固定4キー条件。出典はエンジンにとって不透明。
    """
    return {"high": high, "low": low, "source": {"出典": "人工"}, "expires": item["scheduled"] + 900}


def run(rows: list[tuple], item: dict | None = None, high: float = 110,
        low: float = 90, legacy: bool = False) -> dict:
    """同じ人工入力で新旧の公開入口を呼ぶ。

    引数: rows(list[tuple])は人工経路、item(dict|None)は純判断、high/low(float)は端、legacy(bool)は固定67を選ぶ旗。
    返り値: dictは一候補の運用。旧モジュールの大域値は変更しない。
    """
    chosen = slot() if item is None else item
    module = O.LEGACY if legacy else O
    return module.replay(events(rows), [chosen], {chosen["slot_id"]: condition(chosen, high, low)},
        "2026-11-06_Day", "人工N0", BOUNDS)


# ----------------------------------------


class OperationTests(unittest.TestCase):
    """否定の発生時点と、発動後に作用しない範囲を確認する。"""

    def test_no_invalidation_exact_legacy_operation(self):
        """否定なしの全operationが固定67と辞書全体で一致する。

        引数: なし。
        返り値: None。
        """
        cases = [
            [(0, 100, 99, 100), (1, 111, 99, 100), (2, 111, 99, 100),
                (3, 115, 115, 116), (4, 100, 100, 101), (5, 95, 95, 96)],
            [(0, 100, 99, 100), (300, 100, 99, 100), (600, 100, 99, 100), (899, 100, 99, 100)],
            [(0, 111, 100, 110), (1, 100, 99, 100)],
            [(0, 100, 99, 100), (301, 100, 99, 100)],
            [(0, None, 99, 100), (1, 111, 99, 100)],
        ]
        for rows in cases:
            self.assertEqual(run(rows), run(rows, legacy=True))

    def test_setting_invalidation_equal_and_beyond(self):
        """買い反対端の等号以下を待ち・未登録へ分類する。

        引数: なし。
        返り値: None。
        """
        for last in (90, 89, 89.9999):
            out = run([(0, last, 89, 90), (1, 111, 100, 110)])
            record = out["conditions"]["枠1"]
            self.assertEqual(out["decisions"][0]["action"], "待ち")
            self.assertEqual(record["condition_outcome"], "設定否定")
            self.assertEqual(record["condition_reason"], "設定時に反対端を否定")
            self.assertFalse(record["registered"])
            self.assertFalse(record["watch_started"])
            self.assertFalse(record["watch_quality"])
            self.assertEqual(out["quality"]["損益注意理由"], [])
            self.assertEqual(out["metrics"]["条件未約定"], 0)
            self.assertEqual(out["metrics"]["主待ち率"], 1)
            self.assertFalse(out["orders"])

    def test_degenerate_range_and_already_outside_priority(self):
        """高安同値等号を設定否定、strict既超過を旧理由のままにする。

        引数: なし。
        返り値: None。
        """
        equal = run([(0, 100, 99, 100)], high=100, low=100)
        self.assertEqual(equal["conditions"]["枠1"]["condition_outcome"], "設定否定")
        for side, last in ((1, 100.01), (-1, 99.99)):
            out = run([(0, last, 99, 100)], slot(side=side), high=100, low=100)
            self.assertEqual(out["conditions"]["枠1"]["condition_outcome"], "既超過")

    def test_setting_old_invalid_ready_side_priorities(self):
        """BBO・ready・sideの旧優先条件を設定否定で覆わない。

        引数: なし。
        返り値: None。
        """
        invalid = run([(0, 90, 89, 90, False)])
        self.assertEqual(invalid["decisions"][0]["action"], "判定不能")
        self.assertEqual(invalid["conditions"]["枠1"]["condition_outcome"], "観測不足")
        unready = run([(0, 90, 89, 90)], slot(ready=False))
        self.assertEqual(unready["decisions"][0]["action"], "判定不能")
        self.assertEqual(unready["decisions"][0]["decision_reason"], "人工複合候補")
        empty = run([(0, 90, 89, 90)], slot(side=0))
        self.assertEqual(empty["conditions"]["枠1"]["condition_outcome"], "未登録")

    def test_setting_last_invalid_not_invalidation(self):
        """Last未知・非正は旧判定不能であり、価格否定と補完しない。

        引数: なし。
        返り値: None。
        """
        for last in (None, float("nan"), 0, -1):
            out = run([(0, last, 89, 90)])
            self.assertEqual(out["conditions"]["枠1"]["condition_outcome"], "観測不足")
            self.assertFalse(out["conditions"]["枠1"]["watch_quality"])
            self.assertEqual(out["quality"]["損益注意理由"], [])

    def test_monitor_invalidation_equal_no_retry_no_reverse(self):
        """登録後の反対端等号で取消し、同枠復活と反対注文を作らない。

        引数: なし。
        返り値: None。
        """
        out = run([(0, 100, 99, 100), (1, 90, 89, 90), (2, 111, 100, 110)])
        record = out["conditions"]["枠1"]
        self.assertEqual(record["condition_outcome"], "前提否定")
        self.assertEqual(record["condition_reason"], "発動前に反対端を否定")
        self.assertEqual((record["last_observation_time"], record["end_time"], record["end_line"]), (1, 1, 2))
        self.assertTrue(record["registered"])
        self.assertFalse(record["entry_filled"])
        self.assertFalse(record["watch_quality"])
        self.assertEqual(out["quality"]["損益注意理由"], [])
        self.assertEqual((out["metrics"]["条件登録数"], out["metrics"]["条件未約定"]), (1, 1))
        self.assertEqual((out["metrics"]["主待ち率"], out["metrics"]["保守待ち率上限"]), (0, 1))
        self.assertEqual(out["condition_trace"][-1]["action"], "条件取消")
        self.assertFalse(out["orders"])

    def test_same_second_after_line_invalidation(self):
        """設定より後の同秒原行は否定に使うが、設定行へ遡らない。

        引数: なし。
        返り値: None。
        """
        out = run([(0, 100, 99, 100), (0, 90, 89, 90)])
        self.assertEqual(out["conditions"]["枠1"]["condition_outcome"], "前提否定")
        self.assertEqual(out["conditions"]["枠1"]["end_line"], 2)
        self.assertEqual(out["metrics"]["条件登録数"], 1)

    def test_gap_priority_strict_and_equal(self):
        """300秒超は不足が否定より先、300秒等号は正常な価格否定となる。

        引数: なし。
        返り値: None。
        """
        equal = run([(0, 100, 99, 100), (300, 90, 89, 90)])
        self.assertEqual(equal["conditions"]["枠1"]["condition_outcome"], "前提否定")
        self.assertTrue(equal["quality"]["損益確定可能"])
        over = run([(0, 100, 99, 100), (300.01, 90, 89, 90)])
        self.assertEqual(over["conditions"]["枠1"]["condition_outcome"], "観測不足")
        self.assertTrue(over["conditions"]["枠1"]["watch_quality"])
        self.assertIsNone(over["metrics"]["全体確定対象円"]["5"])

    def test_invalid_quote_or_last_not_a_denial(self):
        """非正常数量旗とLast不正を否定根拠にせず、次の正常突破を許す。

        引数: なし。
        返り値: None。
        """
        out = run([(0, 100, 99, 100), (1, 90, 89, 90, False),
            (2, None, 89, 90), (3, 111, 100, 110), (4, None, 100, 110)])
        record = out["conditions"]["枠1"]
        self.assertEqual(record["trigger"]["time"], 3)
        self.assertEqual(record["entry_time"], 4)
        self.assertEqual(record["condition_outcome"], "約定")
        self.assertEqual(record["last_observation_time"], 3)

    def test_triggered_pending_not_cancelled_by_new_denial(self):
        """発動済entrypendingへ反対端否定を適用せず、正常BBOでfillする。

        引数: なし。
        返り値: None。
        """
        rows = [(0, 100, 99, 100), (1, 111, 100, 110),
            (1.5, 90, 99, 100), (2, 90, 99, 100), (3, 90, 99, 100)]
        new, old = run(rows), run(rows, legacy=True)
        self.assertEqual(new, old)
        self.assertEqual(new["conditions"]["枠1"]["entry_time"], 2)
        self.assertEqual(new["conditions"]["枠1"]["condition_outcome"], "約定")

    def test_holding_not_exited_by_new_denial(self):
        """保有後はLast否定で返済せず、固定保護と独立強制だけを使う。

        引数: なし。
        返り値: None。
        """
        rows = [(0, 100, 99, 100), (1, 111, 99, 100), (2, 111, 99, 100),
            (3, 89, 99, 100), (1001, 89, 99, 100)]
        new = run(rows)
        self.assertEqual(new, run(rows, legacy=True))
        self.assertEqual(new["closed"][0]["exit_request_time"], 1000)
        self.assertEqual(new["closed"][0]["exit_reason"], "場末強制")

    def test_pending_and_holding_slot_priorities(self):
        """定時が否定価格でも注文処理中と保有継続を先に分類する。

        引数: なし。
        返り値: None。
        """
        for second, rows, action in (
            (slot(1.5, 3, slot_id="枠2"), [(0, 100, 99, 100), (1, 111, 99, 100),
                (1.5, 90, 99, 100), (2, 111, 99, 100)], "処理中"),
            (slot(10, 4, ready=False, slot_id="枠2"), [(0, 100, 99, 100), (1, 111, 99, 100),
                (2, 111, 99, 100), (10, 90, 99, 100)], "保有継続")):
            first = slot()
            fixed = {"枠1": condition(first), "枠2": condition(second)}
            out = O.replay(events(rows), [first, second], fixed, "2026-11-06_Day", "人工N0", BOUNDS)
            self.assertEqual(out["decisions"][1]["action"], action)
            self.assertEqual(out["conditions"]["枠2"]["condition_outcome"], "未登録")

    def test_expiry_equal_before_price_invalidation(self):
        """次定時等号は新しい価格否定でなく、旧満了を先に記録する。

        引数: なし。
        返り値: None。
        """
        out = run([(0, 100, 99, 100), (300, 100, 99, 100),
            (600, 100, 99, 100), (900, 90, 89, 90)])
        self.assertEqual(out["conditions"]["枠1"]["condition_outcome"], "未発動")
        self.assertEqual(out["conditions"]["枠1"]["condition_reason"], "次定時まで未発動")
        self.assertEqual(out["conditions"]["枠1"]["end_line"], 3)

    def test_triggered_ttl_equal_and_end_preserved(self):
        """発動後否定があってもTTL等号と終了半開の旧規約を維持する。

        引数: なし。
        返り値: None。
        """
        ttl = [(0, 100, 99, 100), (1, 111, 99, 100),
            (2, 90, 99, 100, False), (31, 90, 99, 100)]
        self.assertEqual(run(ttl), run(ttl, legacy=True))
        self.assertEqual(run(ttl)["conditions"]["枠1"]["entry_time"], 31)
        end = [(0, 100, 99, 100), (1, 111, 99, 100),
            (2, 111, 99, 100), (1010, 90, 99, 100)]
        out = run(end)
        self.assertEqual(out, run(end, legacy=True))
        self.assertFalse(out["closed"])
        self.assertEqual(out["metrics"]["約定台帳観測確定円"]["5"], -61)

    def test_mirror_setting_and_monitor_invalidation(self):
        """上下反射とside反転で設定・監視の否定境界を一致させる。

        引数: なし。
        返り値: None。
        """
        for rows in ([(0, 90, 89, 90)], [(0, 100, 99, 100), (1, 90, 89, 90)]):
            mirror = [(row[0], 2000-row[1], 2000-row[3], 2000-row[2]) for row in rows]
            long, short = run(rows), run(mirror, slot(side=-1), high=1910, low=1890)
            for key in ("registered", "condition_outcome", "condition_reason", "watch_quality", "last_observation_time", "end_time", "end_line"):
                self.assertEqual(long["conditions"]["枠1"][key], short["conditions"]["枠1"][key], key)
            self.assertEqual(long["metrics"], short["metrics"])

    def test_next_slot_new_judgment_after_invalidation(self):
        """否定した同枠は復活させず、次定時では新候補を判断できる。

        引数: なし。
        返り値: None。
        """
        first, second = slot(), slot(900, 3, slot_id="枠2")
        out = O.replay(events([(0, 100, 99, 100), (1, 90, 89, 90),
            (900, 100, 99, 100), (901, 111, 99, 100), (902, 111, 99, 100)]),
            [first, second], {"枠1": condition(first), "枠2": condition(second)},
            "2026-11-06_Day", "人工N0", {"start": 0, "force": 2000, "end": 2010})
        self.assertEqual(out["conditions"]["枠1"]["condition_outcome"], "前提否定")
        self.assertEqual(out["conditions"]["枠2"]["condition_outcome"], "約定")
        self.assertEqual(out["conditions"]["枠2"]["entry_time"], 902)

    def test_invalid_clock_not_used_for_denial(self):
        """後退時計の反対端を無視し、後の正常発動を旧通り処理する。

        引数: なし。
        返り値: None。
        """
        rows = [(0, 100, 99, 100), (1, 100, 99, 100),
            (0.5, 90, 89, 90), (2, 111, 99, 100), (3, 111, 99, 100)]
        out = run(rows)
        self.assertEqual(out, run(rows, legacy=True))
        self.assertEqual(out["quality"]["時計後退行数"], 1)

    def test_original_inputs_and_old_contracts_immutable(self):
        """入力の深い不変性と旧価格・寿命検査の継承を確認する。

        引数: なし。
        返り値: None。
        """
        tape, item = events([(0, 100, 99, 100), (1, 90, 89, 90)]), slot()
        fixed = {"枠1": condition(item)}
        saved = deepcopy((tape, item, fixed))
        out = O.replay(tape, [item], fixed, "2026-11-06_Day", "人工N0", BOUNDS)
        self.assertEqual((tape, item, fixed), saved)
        out["conditions"]["枠1"]["condition"]["source"]["出典"] = "変更"
        self.assertEqual(fixed["枠1"]["source"]["出典"], "人工")
        for change in ({"high": 89}, {"expires": 899}, {"expires": 1000}):
            with self.assertRaises(ValueError):
                O.replay([], [item], {"枠1": {**condition(item), **change}}, "2026-11-06_Day", "人工N0", BOUNDS)
        with self.assertRaises(ValueError):
            run([(0, 90, 89, 90)], {**item, "D": 0})


# ----------------------------------------


def self_test() -> dict:
    """固定前runnerへ同型の人工結果と旧ソース不変を返す。

    引数: なし。
    返り値: dictは全件一致・人工件数・失敗詳細・旧コード不変・市場未読。
    """
    paths = [O.LEGACY_PATH, O.LEGACY.LEGACY_PATH]
    before = {path.as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(OperationTests)
    result = unittest.TestResult()
    suite.run(result)
    failures = [{"検査": test.id(), "詳細": message} for test, message in result.failures + result.errors]
    after = {path.as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    unchanged = before == after
    return {"全件一致": result.wasSuccessful() and unchanged, "人工件数": result.testsRun,
        "詳細": failures,
        "旧67コード不変": before[paths[0].as_posix()] == after[paths[0].as_posix()],
        "旧49コード不変": before[paths[1].as_posix()] == after[paths[1].as_posix()],
        "旧67コードSHA256": before[paths[0].as_posix()],
        "旧49コードSHA256": before[paths[1].as_posix()], "市場入力読取": False}


if __name__ == "__main__":
    report = self_test()
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    raise SystemExit(0 if report["全件一致"] else 1)
