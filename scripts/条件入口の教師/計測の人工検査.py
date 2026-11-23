"""68の完全単独再生と69短区間測定・独立条件先着を架空経路で照合する。"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("条件教師69の人工計測", HERE / "計測.py")
M = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = M
SPEC.loader.exec_module(M)
O = M.O68
SESSION = "人工_Day"
BOUNDS = {"start": 0, "force": 1000, "end": 1010}


def events(rows: list[tuple]) -> list[dict]:
    """手書きの価格経路へ原行番号を与える。

    引数: rows(list[tuple])はnow/last/bid/askと任意valid。
    返り値: list[dict]は固定68の元6列。実相場を含まない。
    """
    return [{"now": row[0], "line": index, "last": row[1], "bid": row[2], "ask": row[3],
        "valid": row[4] if len(row) == 5 else True} for index, row in enumerate(rows, 1)]


def slot(tape: list[dict], scheduled: float = 10, side: int = 1, D: float = 20) -> dict:
    """最初の価格時計へ追加metadataを含む人工判断を結合する。

    引数: tape(list[dict])は人工列、scheduled(float)は予定、side(int)は±1、D(float)は固定距離。
    返り値: dictは純判断とsession/policy/不透明feature。正常flagまで待ち直さない。
    """
    first = next((row for row in tape if scheduled <= row["now"] <= scheduled + 30), None)
    return {"slot_id": "人工枠", "scheduled": scheduled,
        "time": first["now"] if first else scheduled, "line": first["line"] if first else None,
        "side": side, "role": "順行", "atr": 20, "D": D, "reason": "人工複合候補",
        "ready": first is not None, "session": SESSION, "policy": "人工両方向",
        "feature": {"説明": "計測へ渡すが判断に使用しない"}}


def condition(item: dict, high: float = 110, low: float = 90) -> dict:
    """当時公開済みという人工SOURCE13と価格条件を作る。

    引数: item(dict)は元枠、high/low(float)は固定端。
    返り値: dictは68条件4キー。人工時計の完全180秒幅を持つ。
    """
    source = {"session": item["session"], "index": 1, "minutes": 3,
        "start": item["scheduled"] - 180, "end": item["scheduled"],
        "confirm": item["scheduled"], "confirm_line": item["line"] or 0,
        "publish": True, "missing": 0, "open": 100, "high": high, "low": low, "close": 100}
    return {"high": high, "low": low, "source": source, "expires": item["scheduled"] + 900}


def mirror(tape: list[dict]) -> list[dict]:
    """価格と気配を2000を中心に反射する。

    引数: tape(list[dict])は正の人工価格列。
    返り値: list[dict]は時計・原行・数量flagを保つ売り鏡像。
    """
    return [{**row, "last": 2000 - row["last"] if isinstance(row["last"], (int, float)) else row["last"],
        "bid": 2000 - row["ask"], "ask": 2000 - row["bid"]} for row in tape]


# ----------------------------------------


class MeasurementTests(unittest.TestCase):
    """短縮によるwatch早期終了と、flat後の差を保有品質へ混ぜる誤りを検査する。"""

    def compare(self, tape: list[dict], item: dict | None = None,
            fixed: dict | None = None, background_direction: int | None = None,
            bounds: dict | None = None) -> tuple[dict, dict]:
        """完全一枠と短縮法を同じ候補ID・公開射影で照合する。

        引数: tape(list[dict])は人工原行、item/fixed(dict|None)は元判断と条件、background_direction(int|None)は説明用、bounds(dict|None)は人工場時計。
        返り値: tuple[dict,dict]は完全結果と高速結果。原入力の不変も確認する。
        """
        item = slot(tape) if item is None else item
        fixed = condition(item) if fixed is None else fixed
        bounds = BOUNDS if bounds is None else bounds
        saved = deepcopy((tape, item, fixed))
        pure = {key: item[key] for key in O.SLOT_FIELDS if key in item}
        full = O.replay(tape, [pure], {item["slot_id"]: fixed}, SESSION, "人工独立", bounds)
        fast = M.MeasurementBank(tape, SESSION, bounds).measure(item, fixed, "人工独立", background_direction)
        self.assertEqual(M.comparison_view(full), M.comparison_view(fast))
        self.assertEqual((tape, item, fixed), saved)
        self.assertEqual(fast["measurement"]["予定枠分母"], 1)
        if item["ready"] and item["side"] in (-1, 1) and item["line"] is not None:
            self.assertTrue(fast["measurement"]["独立先着約定一致"])
        return full, fast

    def test_watch_continues_until_future_trigger_and_closed(self):
        """登録直後flatで止めず、後の発動・保護・返済完結まで供給する。

        引数: なし。
        返り値: None。
        """
        tape = events([(0, 100, 99, 100), (10, 100, 99, 100), (11, 100, 99, 100),
            (40, 111, 99, 100), (41, 111, 99, 100), (42, 115, 115, 116),
            (43, 100, 100, 101), (44, 95, 95, 96), (100, 350, 350, 351), (1001, 100, 99, 100)])
        _, fast = self.compare(tape)
        self.assertEqual((fast["closed"][0]["entry_time"], fast["closed"][0]["exit_time"]), (41, 44))
        self.assertEqual(fast["measurement"]["打切理由"], "初回完結")
        self.assertLess(fast["measurement"]["供給イベント数"], len(tape) - 1)
        self.assertEqual(fast["measurement"]["独立先着"]["outcome"], "250")
        self.assertLess(fast["closed"][0]["pnl5"], 0)

    def test_mirror_economic_and_barrier(self):
        """上下反射で条件・新規・保護・費用と先着の意味を一致させる。

        引数: なし。
        返り値: None。
        """
        tape = events([(0, 100, 99, 100), (10, 100, 99, 100), (11, 111, 99, 100),
            (12, 111, 99, 100), (13, 115, 115, 116), (14, 100, 100, 101),
            (15, 95, 95, 96), (100, 350, 350, 351)])
        _, long = self.compare(tape)
        reflected = mirror(tape)
        item = slot(reflected, side=-1)
        fixed = condition(item, high=1910, low=1890)
        fixed["source"].update(open=1900, close=1900)
        _, short = self.compare(reflected, item, fixed)
        for key in ("entry_time", "exit_time", "h", "L", "arm", "mfe", "mae", "pnl0", "pnl5", "pnl10"):
            self.assertEqual(long["closed"][0][key], short["closed"][0][key], key)
        self.assertEqual(long["measurement"]["独立先着"]["outcome"], short["measurement"]["独立先着"]["outcome"])

    def test_setting_denied_is_known_zero_not_watch(self):
        """設定否定はwatchを始めず、正常な無取引と0回収を保つ。

        引数: なし。
        返り値: None。
        """
        tape = events([(0, 100, 99, 100), (10, 90, 89, 90), (11, 111, 99, 100), (1001, 100, 99, 100)])
        _, fast = self.compare(tape)
        self.assertEqual(fast["measurement"]["独立先着"]["condition_outcome"], "設定否定")
        self.assertEqual(fast["measurement"]["打切理由"], "条件終了:設定否定")
        self.assertEqual(fast["metrics"]["全体確定対象円"], {"0": 0, "5": 0, "10": 0})
        self.assertFalse(fast["conditions"]["人工枠"]["watch_started"])

    def test_monitor_denied_trace_and_same_slot_no_restart(self):
        """監視後否定を条件終了まで残し、その後の突破へ復活しない。

        引数: なし。
        返り値: None。
        """
        tape = events([(0, 100, 99, 100), (10, 100, 99, 100), (11, 90, 89, 90), (12, 111, 99, 100), (1001, 100, 99, 100)])
        _, fast = self.compare(tape)
        self.assertEqual(fast["measurement"]["独立先着"]["condition_outcome"], "前提否定")
        self.assertEqual(fast["condition_trace"][-1]["action"], "条件取消")
        self.assertEqual(fast["conditions"]["人工枠"]["last_observation_time"], 11)
        self.assertFalse(fast["orders"])

    def test_not_triggered_expiry_timer_and_condition_trace(self):
        """watchを次定時timerまで走らせ、正常未発動として終結する。

        引数: なし。
        返り値: None。
        """
        tape = events([(0, 100, 99, 100), (10, 100, 99, 100), (300, 100, 99, 100),
            (600, 100, 99, 100), (900, 100, 99, 100), (920, 111, 99, 100), (1001, 100, 99, 100)])
        _, fast = self.compare(tape)
        self.assertEqual(fast["measurement"]["独立先着"]["condition_outcome"], "未発動")
        self.assertEqual(fast["conditions"]["人工枠"]["end_time"], 910)
        self.assertEqual(fast["conditions"]["人工枠"]["end_line"], 5)
        self.assertTrue(fast["quality"]["損益確定可能"])

    def test_expiry_with_no_later_event_300_equal(self):
        """末尾から満了まで300秒等号ならfinalizeで正常無取引となる。

        引数: なし。
        返り値: None。
        """
        tape = events([(0, 100, 99, 100), (10, 100, 99, 100), (310, 100, 99, 100), (610, 100, 99, 100)])
        _, fast = self.compare(tape)
        self.assertEqual(fast["measurement"]["独立先着"]["condition_outcome"], "未発動")
        self.assertTrue(fast["quality"]["損益確定可能"])
        self.assertEqual(fast["conditions"]["人工枠"]["end_line"], 4)
        short = tape[:-1]
        _, insufficient = self.compare(short)
        self.assertEqual(insufficient["measurement"]["独立先着"]["condition_outcome"], "観測不足")
        self.assertFalse(insufficient["quality"]["損益確定可能"])

    def test_trigger_pending_expiry_equal_before_fill(self):
        """発動済みでも次定時等号で新規pendingを取り消し、架空fillしない。

        引数: なし。
        返り値: None。
        """
        tape = events([(0, 100, 99, 100), (10, 100, 99, 100), (300, 100, 99, 100),
            (600, 100, 99, 100), (900, 100, 99, 100), (909, 111, 99, 100),
            (910, 111, 99, 100), (1001, 100, 99, 100)])
        _, fast = self.compare(tape)
        self.assertEqual(fast["measurement"]["独立先着"]["condition_outcome"], "発動未約定")
        self.assertEqual(fast["orders"][0]["cancel_reason"], "次定時満了")
        self.assertEqual(fast["conditions"]["人工枠"]["end_line"], 6)
        self.assertFalse(fast["trades"])

    def test_ttl_equal_and_last_not_required_after_trigger(self):
        """TTL30等号の正常BBOを使い、発動後Last不正はfillを妨げない。

        引数: なし。
        返り値: None。
        """
        tape = events([(0, 100, 99, 100), (10, 100, 99, 100), (11, 111, 99, 100),
            (12, 90, 99, 100, False), (41, None, 99, 100), (42, 350, 350, 351),
            (43, 300, 300, 301), (44, 300, 300, 301)])
        _, fast = self.compare(tape)
        self.assertEqual(fast["measurement"]["独立先着"]["entry_time"], 41)
        self.assertEqual(fast["measurement"]["独立先着"]["outcome"], "250")

    def test_watch_gap_prior_to_invalidation_and_breakthrough(self):
        """監視300秒超は否定・突破より先に不足となり、0回収確定にしない。

        引数: なし。
        返り値: None。
        """
        for last in (90, 111):
            tape = events([(0, 100, 99, 100), (10, 100, 99, 100), (311, last, 99, 100), (1001, 100, 99, 100)])
            _, fast = self.compare(tape)
            self.assertEqual(fast["measurement"]["独立先着"]["condition_outcome"], "観測不足")
            self.assertTrue(fast["conditions"]["人工枠"]["watch_quality"])
            self.assertIsNone(fast["metrics"]["全体確定対象円"]["5"])

    def test_invalid_raw_watch_gap_key(self):
        """Last又は数量flagが不正でも、最初の間隔超過原行keyを保存する。

        引数: なし。
        返り値: None。
        """
        tape = events([(0, 100, 99, 100), (10, 100, 99, 100), (200, None, 99, 100),
            (311, None, 99, 100, False), (312, 111, 99, 100)])
        _, fast = self.compare(tape)
        self.assertEqual(fast["conditions"]["人工枠"]["end_line"], 4)
        self.assertEqual(fast["measurement"]["独立先着"]["end_line"], 4)

    def test_setting_unknown_is_not_known_zero_teacher(self):
        """設定観測不足は損益品質が真でも先着未知であることを残す。

        引数: なし。
        返り値: None。
        """
        for last, valid in ((None, True), (100, False)):
            tape = events([(0, 100, 99, 100), (10, last, 99, 100, valid), (11, 111, 99, 100)])
            _, fast = self.compare(tape)
            self.assertTrue(fast["quality"]["損益確定可能"])
            self.assertEqual(fast["metrics"]["全体確定対象円"]["5"], 0)
            self.assertEqual(fast["measurement"]["独立先着"]["outcome"], "観測不足")
            self.assertFalse(fast["measurement"]["独立先着"]["watch_started"])

    def test_entry_cancel_then_flat_gap_not_pnl_attention(self):
        """watch消費後の新規TTL取消とflat長gapを保有品質へ混ぜない。

        引数: なし。
        返り値: None。
        """
        tape = events([(0, 100, 99, 100), (10, 100, 99, 100), (11, 111, 99, 100),
            (350, 100, 99, 100), (700, 100, 99, 100), (1001, 100, 99, 100)])
        full, fast = self.compare(tape)
        self.assertEqual(fast["orders"][0]["cancel_time"], 41)
        self.assertEqual(fast["measurement"]["独立先着"]["condition_outcome"], "発動未約定")
        self.assertTrue(fast["quality"]["損益確定可能"])
        self.assertGreater(full["quality"]["空き時間長気配間隔数"], fast["quality"]["空き時間長気配間隔数"])

    def test_protection_pending_freeze_and_real_mfe(self):
        """返済pending中のh/L/arm凍結と実MFE継続まで全再生へ一致させる。

        引数: なし。
        返り値: None。
        """
        tape = events([(0, 100, 99, 100), (10, 100, 99, 100), (11, 111, 99, 100),
            (12, 111, 99, 100), (13, 120, 120, 121), (14, 100, 100, 101),
            (14.5, 150, 150, 151), (15, 99, 99, 100), (100, 350, 350, 351)])
        _, fast = self.compare(tape)
        row = fast["closed"][0]
        self.assertEqual((row["h"], row["L"], row["mfe"], row["exit_time"]), (20, 0, 50, 15))

    def test_force_independent_timer_and_first_same_second_label(self):
        """強制要求はtimer、先着はforce最初正常行、返済fillは次秒である。

        引数: なし。
        返り値: None。
        """
        tape = events([(0, 100, 99, 100), (10, 100, 99, 100), (11, 111, 99, 100),
            (12, 111, 99, 100), (300, 100, 99, 100), (600, 100, 99, 100),
            (900, 100, 99, 100), (1000, 100, 99, 100), (1000, 350, 350, 351), (1001, None, 99, 100)])
        _, fast = self.compare(tape)
        row = fast["closed"][0]
        self.assertEqual((row["exit_request_time"], row["exit_request_line"], row["exit_time"]), (1000, 7, 1001))
        self.assertEqual(fast["measurement"]["独立先着"]["outcome"], "期限")
        self.assertEqual(fast["measurement"]["独立先着"]["end_line"], 8)

    def test_unresolved_keeps_entry_cost_and_null(self):
        """EOFで保有・返済pendingが残れば、架空返済せず全費用nullを残す。

        引数: なし。
        返り値: None。
        """
        tape = events([(0, 100, 99, 100), (10, 100, 99, 100), (11, 111, 99, 100), (12, 111, 99, 100)])
        _, fast = self.compare(tape)
        self.assertEqual(fast["metrics"]["約定台帳観測確定円"], {"0": -11, "5": -61, "10": -111})
        self.assertEqual(fast["metrics"]["全体確定対象円"], {"0": None, "5": None, "10": None})
        self.assertEqual((fast["quality"]["未解消建玉数"], fast["quality"]["未解消注文数"]), (1, 1))
        self.assertEqual(fast["measurement"]["独立先着"]["outcome"], "不足")

    def test_holding_gap_300_boundary(self):
        """保有中の300秒等号と超過を、prefixに依らず完全再生と同じにする。

        引数: なし。
        返り値: None。
        """
        for now, cautions in ((312, 0), (312.1, 1)):
            tape = events([(0, 100, 99, 100), (10, 100, 99, 100), (11, 111, 99, 100),
                (12, 111, 99, 100), (now, 100, 99, 100), (600, 100, 99, 100),
                (900, 100, 99, 100), (1000, 100, 99, 100), (1001, 100, 99, 100)])
            _, fast = self.compare(tape)
            self.assertEqual(fast["quality"]["保有中長気配間隔数"], cautions)
            self.assertEqual(fast["quality"]["損益確定可能"], cautions == 0)

    def test_prefix_clock_quote_and_flat_quality(self):
        """切出前の最終時計・原行・前正常気配とflatカウンタを保存する。

        引数: なし。
        返り値: None。
        """
        tape = events([(0, 100, 99, 100), (301, 100, 99, 100), (310, 100, 99, 100, False),
            (320, 100, 99, 100), (321, 111, 99, 100), (322, 111, 99, 100),
            (323, 80, 80, 81), (324, 80, 80, 81), (1001, 100, 99, 100)])
        _, fast = self.compare(tape, slot(tape, scheduled=320), bounds={"start": 0, "force": 2000, "end": 2010})
        prefix = fast["measurement"]["prefix"]
        self.assertEqual(prefix, {"last_time": 310, "last_line": 3, "raw_line": 3,
            "last_quote_time": 301, "非正常BBO行数": 1, "空き時間長気配間隔数": 1})

    def test_same_second_trigger_keeps_original_setting_key(self):
        """設定同秒の後行発動でも、元枠と発動要求とfillを混同しない。

        引数: なし。
        返り値: None。
        """
        tape = events([(0, 100, 99, 100), (10, 100, 99, 100), (10, 111, 99, 100),
            (11, 111, 99, 100), (12, 80, 80, 81), (13, 80, 80, 81)])
        _, fast = self.compare(tape)
        label = fast["measurement"]["独立先着"]
        self.assertEqual((label["time"], label["line"]), (10, 2))
        self.assertEqual((label["trigger"]["time"], label["trigger"]["line"]), (10, 3))
        self.assertEqual((label["entry_time"], label["entry_line"]), (11, 4))

    def test_placeholder_and_side_zero_outside_teacher_scope(self):
        """非準備placeholderとside0も標準形を保ち、独立先着は作らない。

        引数: なし。
        返り値: None。
        """
        tape = events([(0, 100, 99, 100), (50, 100, 99, 100), (1001, 100, 99, 100)])
        _, missing = self.compare(tape)
        self.assertIsNone(missing["measurement"]["独立先着"])
        valid = events([(0, 100, 99, 100), (10, 100, 99, 100), (20, 111, 99, 100)])
        _, zero = self.compare(valid, slot(valid, side=0))
        self.assertIsNone(zero["measurement"]["独立先着"])

    def test_first_raw_not_first_normal_and_metadata_projection(self):
        """最初の無効行を後正常行へ救済せず、追加metadataをEngineへ渡さない。

        引数: なし。
        返り値: None。
        """
        tape = events([(0, 100, 99, 100), (10, 100, 99, 100, False), (11, 111, 99, 100)])
        bank = M.MeasurementBank(tape, SESSION, BOUNDS)
        item = slot(tape)
        self.assertTrue(bank.measure(item, condition(item))["measurement"]["独立先着約定一致"])
        delayed = {**item, "time": 11, "line": 3}
        with self.assertRaises(ValueError):
            bank.measure(delayed, condition(delayed))
        extra = {**item, "feature": {"説明": "別の追加値"}, "その他": [1, 2, 3]}
        self.assertEqual(M.comparison_view(bank.measure(item, condition(item))), M.comparison_view(bank.measure(extra, condition(extra))))

    def test_bank_copy_and_repeated_measurement_independence(self):
        """銀行と返り値の深い不変性を保ち、前測定のwatchや建玉を引き継がない。

        引数: なし。
        返り値: None。
        """
        tape = events([(0, 100, 99, 100), (10, 100, 99, 100), (11, 90, 89, 90), (12, 111, 99, 100)])
        item, saved = slot(tape), deepcopy(tape)
        fixed = condition(item)
        bank = M.MeasurementBank(tape, SESSION, BOUNDS)
        tape[0]["bid"] = 1
        one = bank.measure(item, fixed)
        baseline = M.comparison_view(one)
        one["conditions"]["人工枠"]["condition"]["source"]["open"] = 1
        self.assertEqual(M.comparison_view(bank.measure(item, fixed)), baseline)
        pure = {key: item[key] for key in O.SLOT_FIELDS}
        full = O.replay(saved, [pure], {item["slot_id"]: fixed}, SESSION, "独立条件測定", BOUNDS)
        self.assertEqual(M.comparison_view(full), baseline)

    def test_di_zero_role_and_schema_guards(self):
        """DI同値仮役割の説明と、入力時計・場名・生未来列の拒否を確認する。

        引数: なし。
        返り値: None。
        """
        tape = events([(0, 100, 99, 100), (10, 90, 89, 90)])
        item = slot(tape)
        _, fast = self.compare(tape, item, background_direction=0)
        self.assertIn("測定用順行仮置", fast["measurement"]["役割説明"])
        bank = M.MeasurementBank(tape, SESSION, BOUNDS)
        with self.assertRaises(ValueError):
            bank.measure({**item, "role": "反転"}, condition(item), background_direction=0)
        with self.assertRaises(ValueError):
            bank.measure({**item, "session": "別場"}, condition(item))
        for bad in ([{**tape[0], "outcome": "250"}], [{**tape[0], "now": float("nan")}],
                [tape[1], tape[0]], [{**tape[0], "now": BOUNDS["end"]}]):
            with self.assertRaises(ValueError):
                M.MeasurementBank(bad, SESSION, BOUNDS)


# ----------------------------------------


def self_test() -> dict:
    """人工だけを一回実行し、固定参照の不変と比較範囲を返す。

    引数: なし。
    返り値: dictは全件一致・人工件数・失敗詳細・参照SHA・市場未読。
    """
    before = {name: hashlib.sha256((M.ROOT / name).read_bytes()).hexdigest() for name in M.SHARED_SHA256}
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(MeasurementTests)
    result = unittest.TestResult()
    suite.run(result)
    failures = [{"検査": test.id(), "詳細": message} for test, message in result.failures + result.errors]
    after = {name: hashlib.sha256((M.ROOT / name).read_bytes()).hexdigest() for name in M.SHARED_SHA256}
    unchanged = before == after == M.SHARED_SHA256
    return {"全件一致": result.wasSuccessful() and unchanged, "人工件数": result.testsRun,
        "詳細": failures, "固定参照不変": unchanged, "固定参照SHA256": before,
        "完全単独再生との比較": "comparison_view全体・条件遷移を含む", "本物入力読取": False, "fit": 0}


if __name__ == "__main__":
    report = self_test()
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    raise SystemExit(0 if report["全件一致"] else 1)
