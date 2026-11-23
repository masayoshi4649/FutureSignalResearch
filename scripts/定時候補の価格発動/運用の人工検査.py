"""定時条件・将来発動・固定49保護の境界を、手書き経路だけで検査する。"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("条件価格発動67の人工運用", HERE / "運用.py")
O = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = O
SPEC.loader.exec_module(O)
BOUNDS = {"start": 0, "force": 1000, "end": 1010}


def events(rows: list[tuple]) -> list[dict]:
    """手書きの時計・Last・気配へ原行番号を添える。

    引数: rows(list[tuple])はnow/last/bid/askと任意valid。
    返り値: list[dict]は最小6フィールドの人工原行。
    """
    return [{"now": row[0], "line": index, "last": row[1], "bid": row[2], "ask": row[3],
        "valid": row[4] if len(row) == 5 else True} for index, row in enumerate(rows, 1)]


def slot(now: float = 0, line: int | None = 1, side: int = 1,
        ready: bool = True, D: float = 20, scheduled: float | None = None,
        slot_id: str = "枠1") -> dict:
    """未来値を持たない純判断を作る。

    引数: now(float)/line(int|None)は判断出典、side(int)/ready(bool)/D(float)は条件、scheduled(float|None)は予定、slot_id(str)は識別。
    返り値: dictは固定49のSLOT_FIELDSだけを持つ。
    """
    return {"scheduled": now if scheduled is None else scheduled, "time": now, "line": line,
        "side": side, "role": "順行", "atr": 20, "D": D,
        "reason": "人工複合候補", "ready": ready, "slot_id": slot_id}


def condition(item: dict, high: float = 110, low: float = 90) -> dict:
    """出典を不透明辞書とする人工の固定価格条件を作る。

    引数: item(dict)は元枠、high/low(float)は当時の端。
    返り値: dictはhigh/low/source/expiresの4キー。
    """
    return {"high": high, "low": low, "source": {"出典": "人工の公開完全足"},
        "expires": item["scheduled"] + 900}


def run(rows: list[tuple], item: dict | None = None, high: float = 110,
        low: float = 90, bounds: dict | None = None) -> dict:
    """一枠の手書き経路を公開APIへ渡す。

    引数: rows(list[tuple])は人工原行、item(dict|None)は純判断、high/low(float)は線、bounds(dict|None)は時計。
    返り値: dictは条件運用。市場・教師・モデルを読まない。
    """
    chosen = slot() if item is None else item
    return O.replay(events(rows), [chosen], {chosen["slot_id"]: condition(chosen, high, low)},
        "2026-11-06_Day", "人工G0", BOUNDS if bounds is None else bounds)


def project_order(order: dict) -> dict:
    """元判断時計の違いだけを除き、要求と約定を比較する。

    引数: order(dict)は新旧いずれかの注文。
    返り値: dictは元slotのscheduled/time/line以外を保持する比較用複製。
    """
    result = deepcopy(order)
    if "slot" in result:
        for key in ("scheduled", "time", "line"):
            result["slot"].pop(key)
    return result


# ----------------------------------------


class OperationTests(unittest.TestCase):
    """将来線約定を作らず、期待する異なる結果を明示して検査する。"""

    def test_schedule(self):
        """定時25/49枠と最終枠寿命が強制より前であることを確認する。

        引数: なし。
        返り値: None。
        """
        for name, count in (("Day", 25), ("Night", 49)):
            session = "2026-11-06_" + name
            times = O.scheduled_times(session)
            self.assertEqual(len(times), count)
            self.assertLess(times[-1] + 900, O.session_bounds(session)["force"])

    def test_setting_equal_same_second_after_line_and_actual_bbo(self):
        """設定等号・同秒後行発動・次秒実BBO約定を確認する。

        引数: なし。
        返り値: None。
        """
        out = run([(0, 110, 100, 110), (0, 111, 150, 160),
            (0.5, 120, 170, 180), (1, 125, 190, 200), (2, 125, 195, 205)])
        record = out["conditions"]["枠1"]
        self.assertEqual(out["decisions"][0]["action"], "条件登録")
        self.assertEqual(record["trigger"], {"time": 0.0, "line": 2, "last": 111})
        self.assertEqual((record["entry_time"], record["entry_line"], record["entry_price"]), (1, 4, 200))
        self.assertEqual(out["orders"][0]["slot"], slot())
        self.assertNotEqual(record["entry_price"], 110)

    def test_direction_mirror(self):
        """価格反射とside反転で発動・保護・費用を一致させる。

        引数: なし。
        返り値: None。
        """
        rows = [(0, 100, 99, 100), (1, 111, 99, 100), (2, 111, 99, 100),
            (3, 115, 115, 116), (4, 100, 100, 101), (5, 95, 95, 96)]
        long = run(rows)
        reflected = [(row[0], 2000-row[1], 2000-row[3], 2000-row[2]) for row in rows]
        short = run(reflected, slot(side=-1), high=1910, low=1890)
        for key in ("entry_time", "exit_time", "h", "L", "arm", "mfe", "mae", "pnl0", "pnl5", "pnl10"):
            self.assertEqual(long["closed"][0][key], short["closed"][0][key], key)

    def test_legacy_protection_and_cash_equal_after_trigger(self):
        """要求後の全注文・約定・完結が固定49の同要求経路と一致する。

        引数: なし。
        返り値: None。
        """
        rows = [(0, 100, 99, 100), (1, 111, 99, 100), (2, 111, 99, 100),
            (3, 115, 115, 116), (4, 100, 100, 101), (5, 95, 95, 96)]
        fresh = run(rows)
        prior = O.LEGACY.replay(events(rows), [slot(1, 2)], "2026-11-06_Day", "人工G0", BOUNDS)
        self.assertEqual(fresh["closed"], prior["closed"])
        self.assertEqual(fresh["trades"], prior["trades"])
        self.assertEqual([project_order(row) for row in fresh["orders"]], [project_order(row) for row in prior["orders"]])
        for key in ("完結取引観測純額円", "約定台帳観測確定円", "全体確定対象円"):
            self.assertEqual(fresh["metrics"][key], prior["metrics"][key])

    def test_already_outside_and_equality_not_trigger(self):
        """設定既超過は拒否し、等号が続くだけなら新規を出さない。

        引数: なし。
        返り値: None。
        """
        rejected = run([(0, 111, 100, 110), (1, 109, 100, 110)])
        self.assertEqual(rejected["conditions"]["枠1"]["condition_outcome"], "既超過")
        self.assertFalse(rejected["conditions"]["枠1"]["registered"])
        self.assertEqual(rejected["decisions"][0]["action"], "待ち")
        equal = run([(0, 110, 100, 110), (300, 110, 100, 110),
            (600, 110, 100, 110), (899, 110, 100, 110)])
        self.assertEqual(equal["conditions"]["枠1"]["condition_outcome"], "未発動")
        self.assertEqual(equal["metrics"]["条件未約定"], 1)
        self.assertEqual(equal["metrics"]["主待ち率"], 0)
        self.assertEqual(equal["metrics"]["保守待ち率上限"], 1)
        self.assertFalse(equal["orders"])

    def test_degenerate_range_valid(self):
        """高安同値でも設定等号を許し、後のstrict突破だけで発動する。

        引数: なし。
        返り値: None。
        """
        out = run([(0, 100, 99, 100), (1, 100, 99, 100),
            (2, 100.01, 99, 100), (3, 100, 99, 100)], high=100, low=100)
        self.assertEqual(out["conditions"]["枠1"]["trigger"]["time"], 2)

    def test_setting_last_invalid_not_pnl_quality(self):
        """設定時Last不正は判定不能かつ未登録で、PnL注意を作らない。

        引数: なし。
        返り値: None。
        """
        for last in (None, float("nan"), 0, -1):
            out = run([(0, last, 99, 100), (1, 111, 99, 100)])
            self.assertEqual(out["decisions"][0]["action"], "判定不能")
            self.assertEqual(out["conditions"]["枠1"]["condition_outcome"], "観測不足")
            self.assertFalse(out["conditions"]["枠1"]["watch_started"])
            self.assertFalse(out["conditions"]["枠1"]["watch_quality"])
            self.assertEqual(out["quality"]["損益注意理由"], [])
            self.assertEqual(out["metrics"]["全体確定対象円"]["5"], 0)

    def test_valid_quantity_flag_not_ignored(self):
        """元数量validがFalseの設定・突破・fillを正常扱いしない。

        引数: なし。
        返り値: None。
        """
        invalid_setting = run([(0, 100, 99, 100, False), (1, 111, 99, 100)])
        self.assertFalse(invalid_setting["conditions"]["枠1"]["registered"])
        out = run([(0, 100, 99, 100), (1, 111, 99, 100, False),
            (2, 111, 99, 100), (3, 111, 99, 100, False), (4, None, 99, 100)])
        self.assertEqual(out["conditions"]["枠1"]["trigger"]["time"], 2)
        self.assertEqual(out["conditions"]["枠1"]["entry_time"], 4)

    def test_last_invalid_during_watch_does_not_refresh(self):
        """正常BBOでもLast不正の行は監視時計を更新しない。

        引数: なし。
        返り値: None。
        """
        out = run([(0, 100, 99, 100), (200, None, 99, 100), (301, None, 99, 100)])
        record = out["conditions"]["枠1"]
        self.assertEqual((record["condition_outcome"], record["end_time"], record["end_line"]), ("観測不足", 301, 3))
        self.assertEqual(record["last_observation_time"], 0)

    def test_watch_gap_strict_300_and_trigger_priority(self):
        """300秒等号は発動可、超過は突破しても観測不足が先になる。

        引数: なし。
        返り値: None。
        """
        equal = run([(0, 100, 99, 100), (300, 111, 99, 100), (301, 111, 99, 100)])
        self.assertTrue(equal["conditions"]["枠1"]["entry_filled"])
        over = run([(0, 100, 99, 100), (300.1, 111, 99, 100)])
        self.assertFalse(over["orders"])
        self.assertTrue(over["conditions"]["枠1"]["watch_quality"])
        self.assertIsNone(over["metrics"]["全体確定対象円"]["5"])

    def test_invalid_raw_gap_detection(self):
        """監視間隔超過の最初の不正行でも、到着keyを不足根拠へ残す。

        引数: なし。
        返り値: None。
        """
        out = run([(0, 100, 99, 100), (301, 111, 99, 100, False), (302, 111, 99, 100)])
        record = out["conditions"]["枠1"]
        self.assertEqual((record["end_time"], record["end_line"]), (301, 2))
        self.assertEqual(out["quality"]["条件監視観測不足取消数"], 1)
        self.assertFalse(out["orders"])

    def test_expiry_timer_gap_without_future_event(self):
        """後続行がなくても満了時の観測不足を未発動と分ける。

        引数: なし。
        返り値: None。
        """
        out = run([(0, 100, 99, 100), (300, 100, 99, 100)])
        record = out["conditions"]["枠1"]
        self.assertEqual((record["condition_outcome"], record["end_time"], record["end_line"]), ("観測不足", 900, 2))
        at300 = run([(0, 100, 99, 100), (300, 100, 99, 100), (600, 100, 99, 100)])
        self.assertEqual(at300["conditions"]["枠1"]["condition_outcome"], "未発動")
        self.assertTrue(at300["quality"]["損益確定可能"])

    def test_expiry_before_trigger_and_fill_equal(self):
        """次定時等号では突破・新規fillのいずれにも先に満了する。

        引数: なし。
        返り値: None。
        """
        before = [(0, 100, 99, 100), (300, 100, 99, 100), (600, 100, 99, 100)]
        watch = run(before + [(900, 111, 99, 100)])
        self.assertIsNone(watch["conditions"]["枠1"]["trigger"])
        pending = run(before + [(899, 111, 99, 100), (900, 111, 99, 100)])
        self.assertEqual(pending["conditions"]["枠1"]["condition_outcome"], "発動未約定")
        self.assertEqual(pending["orders"][0]["cancel_reason"], "次定時満了")
        self.assertFalse(pending["trades"])

    def test_ttl_equal_allowed_before_next_slot(self):
        """発動後TTL30秒等号のfillを許し、30秒超を取消す。

        引数: なし。
        返り値: None。
        """
        equal = run([(0, 100, 99, 100), (1, 111, 99, 100), (31, None, 99, 100)])
        self.assertEqual(equal["conditions"]["枠1"]["entry_time"], 31)
        over = run([(0, 100, 99, 100), (1, 111, 99, 100), (31.1, 111, 99, 100)])
        self.assertFalse(over["trades"])
        self.assertEqual(over["conditions"]["枠1"]["condition_reason"], "新規TTL30秒")

    def test_next_slot_priority_and_placeholder(self):
        """次枠の欠測placeholderより前に旧watchを満了させる。

        引数: なし。
        返り値: None。
        """
        first, missing = slot(), slot(900, None, ready=False, side=0, slot_id="枠2")
        out = O.replay(events([(0, 100, 99, 100), (300, 100, 99, 100), (600, 100, 99, 100)]),
            [first, missing], {"枠1": condition(first)}, "2026-11-06_Day", "人工G0", BOUNDS)
        self.assertEqual([row["action"] for row in out["decisions"]], ["条件登録", "判定不能"])
        self.assertFalse(out["decisions"][1]["watching"])
        self.assertEqual(out["metrics"]["保守待ち率上限"], 1)

    def test_holding_unready_or_last_invalid_still_nonwait(self):
        """保有時はLastと特徴readyを課さず、BBO無効だけを優先する。

        引数: なし。
        返り値: None。
        """
        first, second = slot(), slot(10, 4, side=0, ready=False, slot_id="枠2")
        out = O.replay(events([(0, 100, 99, 100), (1, 111, 99, 100), (2, 111, 99, 100),
            (10, None, 99, 100)]), [first, second], {"枠1": condition(first)},
            "2026-11-06_Day", "人工G0", BOUNDS)
        self.assertEqual(out["decisions"][1]["action"], "保有継続")
        self.assertEqual(out["metrics"]["保守待ち率上限"], 0)

    def test_force_independent_and_end_halfopen(self):
        """返済要求は強制timer、fillは次秒から終了未満だけとする。

        引数: なし。
        返り値: None。
        """
        out = run([(0, 100, 99, 100), (1, 111, 99, 100), (2, 111, 99, 100),
            (1000, 100, 99, 100), (1001, 100, 99, 100)])
        self.assertEqual((out["closed"][0]["exit_request_time"], out["closed"][0]["exit_time"]), (1000, 1001))
        excluded = run([(0, 100, 99, 100), (1, 111, 99, 100), (2, 111, 99, 100), (1010, 100, 99, 100)])
        self.assertFalse(excluded["closed"])
        self.assertIsNone(excluded["metrics"]["全体確定対象円"]["5"])
        self.assertEqual(excluded["metrics"]["約定台帳観測確定円"]["5"], -61)

    def test_exit_pending_preserved_at_condition_expiry(self):
        """次定時満了は返済pendingを取消さず、保護状態も更新しない。

        引数: なし。
        返り値: None。
        """
        out = run([(0, 100, 99, 100), (1, 111, 99, 100), (2, 111, 99, 100),
            (899, 80, 80, 81), (900, 80, 80, 81)])
        self.assertEqual((out["closed"][0]["exit_request_time"], out["closed"][0]["exit_time"]), (899, 900))
        self.assertEqual(out["orders"][-1]["status"], "filled")

    def test_current_profit_strict_and_pending_freeze(self):
        """現在122円等号不起動とpending中の保護凍結を固定49と同じにする。

        引数: なし。
        返り値: None。
        """
        out = run([(0, 100, 99, 100), (1, 111, 99, 100), (2, 111, 99, 100),
            (3, 112.2, 112.2, 113.2), (4, 112.2001, 112.2001, 113.2001),
            (5, 100, 100, 101), (5.5, 150, 150, 151), (6, 150, 150, 151)])
        updates = [row for row in out["trail"] if row["action"] == "保護更新"]
        self.assertFalse(next(row for row in updates if row["time"] == 3)["state"]["position"]["arm"])
        closed = out["closed"][0]
        self.assertEqual(closed["arm_time"], 4)
        self.assertEqual(closed["h"], 12.2001)
        self.assertEqual(closed["mfe"], 50)
        self.assertEqual(closed["L"], 0)

    def test_schema_no_future_and_condition_validation(self):
        """未来label・不正線・寿命違反・未知slotを入力段階で拒否する。

        引数: なし。
        返り値: None。
        """
        item = slot()
        for change in ({"high": 89}, {"low": 0}, {"high": float("nan")},
                {"expires": 899}, {"expires": 1000}, {"source": []}, {"outcome": "250"}):
            with self.assertRaises(ValueError):
                O.replay([], [item], {"枠1": {**condition(item), **change}}, "2026-11-06_Day", "人工G0", BOUNDS)
        with self.assertRaises(ValueError):
            O.replay([], [{**item, "outcome": "250"}], {}, "2026-11-06_Day", "人工G0", BOUNDS)
        with self.assertRaises(ValueError):
            O.replay([], [item], {"不明": condition(item)}, "2026-11-06_Day", "人工G0", BOUNDS)

    def test_monotonic_clock_and_input_immutable(self):
        """時計後退を監視へ使わず、原入力と固定49コードを変更しない。

        引数: なし。
        返り値: None。
        """
        tape = events([(0, 100, 99, 100), (1, 100, 99, 100),
            (0.5, 111, 99, 100), (2, 111, 99, 100), (3, 111, 99, 100)])
        item, fixed = slot(), condition(slot())
        original = deepcopy((tape, item, fixed))
        out = O.replay(tape, [item], {"枠1": fixed}, "2026-11-06_Day", "人工G0", BOUNDS)
        self.assertEqual(out["conditions"]["枠1"]["trigger"]["time"], 2)
        self.assertEqual(out["quality"]["時計後退行数"], 1)
        self.assertEqual((tape, item, fixed), original)
        out["conditions"]["枠1"]["condition"]["source"]["出典"] = "変更"
        self.assertEqual(fixed["source"]["出典"], "人工の公開完全足")

    def test_max_one_watch_no_same_slot_retry(self):
        """取消後も同じ枠を登録し直さず、一監視だけを保持する。

        引数: なし。
        返り値: None。
        """
        out = run([(0, 100, 99, 100), (301, 100, 99, 100), (302, 111, 99, 100)])
        self.assertEqual(out["metrics"]["条件登録数"], 1)
        self.assertEqual(len([row for row in out["condition_trace"] if row["action"] == "条件登録"]), 1)
        self.assertFalse(out["orders"])


# ----------------------------------------


def self_test() -> dict:
    """全人工を一回実行し、rootの固定前runner向け結果を返す。

    引数: なし。
    返り値: dictは全件一致・人工件数・詳細・旧49不変と市場入力未読の記録。
    """
    before = hashlib.sha256(O.LEGACY_PATH.read_bytes()).hexdigest()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(OperationTests)
    result = unittest.TestResult()
    suite.run(result)
    failed = [{"検査": test.id(), "詳細": message} for test, message in result.failures + result.errors]
    unchanged = before == hashlib.sha256(O.LEGACY_PATH.read_bytes()).hexdigest()
    return {"全件一致": result.wasSuccessful() and unchanged, "人工件数": result.testsRun,
        "詳細": failed, "旧49コード不変": unchanged, "旧49コードSHA256": before,
        "市場入力読取": False}


if __name__ == "__main__":
    report = self_test()
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    raise SystemExit(0 if report["全件一致"] else 1)
