"""定時判断と連続保護を、相場を使わない明示期待値で検査する。"""

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("定時帯反応の人工運用", HERE / "運用.py")
O = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = O
SPEC.loader.exec_module(O)


def quotes(rows: list[tuple]) -> list[dict]:
    """手書き価格列へ原行番号と最小6字段を与える。

    引数: rows(list[tuple])はnow/bid/askと任意validの列。
    返り値: list[dict]は人工BBO。実相場・旧モデルを読まない。
    """
    return [{"now": r[0], "line": i, "last": r[1], "bid": r[1], "ask": r[2], "valid": r[3] if len(r) == 4 else True} for i, r in enumerate(rows, 1)]


def slot(now: float, line: int | None, side: int = 1, role: str | None = "順行", D: float = 20, ready: bool = True, scheduled: float | None = None) -> dict:
    """最小の人工定時判断を作る。

    引数: now(float)/line(int|None)は判断出典、side/role/D/readyは純判断、scheduled(float|None)は予定。
    返り値: dictは未来labelの無いslot。
    """
    return {"scheduled": now if scheduled is None else scheduled, "time": now, "line": line, "side": side, "role": role, "atr": 20, "D": D, "reason": "人工条件", "ready": ready}


def run_fixture(events: list[dict], slots: list[dict], force: float = 50, end: float = 60) -> dict:
    """人工時計だけで公開APIを呼び出す。

    引数: events/slots(list[dict])は人工入力、force/end(float)は時計。
    返り値: dictは一候補結果。ファイルを出力しない。
    """
    return O.replay(events, slots, "2026-11-06_Day", "人工S0", {"start": 0, "force": force, "end": end})


class OperationTests(unittest.TestCase):
    """実装の写しでなく、境界と異なる結果を持つ人工経路を検査する。"""

    def test_schedule(self):
        """予定枠数と日跨ぎの両端を確認する。

        引数: なし。
        返り値: None。
        """
        day, night = O.scheduled_times("2026-11-06_Day"), O.scheduled_times("2026-11-06_Night")
        self.assertEqual((len(day), len(night)), (25, 49))
        self.assertTrue(O.timestamp(day[0]).endswith("09:15:00+09:00"))
        self.assertTrue(O.timestamp(day[-1]).endswith("15:15:00+09:00"))
        self.assertTrue(O.timestamp(night[0]).endswith("17:30:00+09:00"))
        self.assertTrue(O.timestamp(night[-1]).startswith("2026-11-07T05:30:00"))

    def test_arm_protect_cash_and_mirror(self):
        """買売鏡像、同値床、次秒返済、同約定費用を確認する。

        引数: なし。
        返り値: None。
        """
        events = quotes([(0, 100, 110), (1, 100, 110), (2, 123, 133), (3, 110, 120), (4, 105, 115)])
        long = run_fixture(events, [slot(0, 1)])
        mirrored = [{**e, "bid": 2000 - e["ask"], "ask": 2000 - e["bid"], "last": 2000 - e["last"]} for e in events]
        short = run_fixture(mirrored, [slot(0, 1, side=-1)])
        for result in (long, short):
            c = result["closed"][0]
            self.assertEqual((c["entry_time"], c["exit_request_time"], c["exit_time"]), (1, 3, 4))
            self.assertEqual((c["h"], c["L"], c["arm"]), (13, 0, True))
            self.assertEqual((c["pnl0"], c["pnl5"], c["pnl10"]), (-72, -172, -272))
            self.assertEqual([t["fee_yen"] for t in result["trades"]], [61, 61])
            self.assertEqual(result["metrics"]["約定台帳観測確定円"]["5"], -172)

    def test_strict_current_122_boundary(self):
        """12.2pt等号非起動と、その直上での現在益起動を確認する。

        引数: なし。
        返り値: None。
        """
        out = run_fixture(quotes([(0, 99, 100), (1, 99, 100), (2, 112.2, 113.2), (3, 112.2001, 113.2001), (51, 110, 111)]), [slot(0, 1)])
        updates = [r for r in out["trail"] if r["action"] == "保護更新"]
        self.assertFalse(next(r for r in updates if r["time"] == 2)["state"]["position"]["arm"])
        self.assertTrue(next(r for r in updates if r["time"] == 3)["state"]["position"]["arm"])
        self.assertEqual(out["closed"][0]["arm_time"], 3)

    def test_prearm_positive_line_and_pending_freeze(self):
        """費用起動前の正保護線と、pending後のarm補完禁止を確認する。

        引数: なし。
        返り値: None。
        """
        out = run_fixture(quotes([(0, 99, 100), (1, 99, 100), (2, 110, 111), (3, 105, 106), (3.5, 120, 121), (4, 120, 121)]), [slot(0, 1, D=5)])
        c = out["closed"][0]
        self.assertEqual((c["h"], c["L"], c["arm"]), (10, 5, False))
        self.assertEqual((c["mfe"], c["exit_request_time"], c["exit_time"]), (20, 3, 4))
        self.assertIsNone(c["arm_time"])

    def test_initial_loss_line_same_fill_quote(self):
        """新規fill当行の損失線等号と、同じ行で返済しないことを確認する。

        引数: なし。
        返り値: None。
        """
        out = run_fixture(quotes([(0, 95, 100), (1, 95, 100), (1.5, 95, 100), (2, 90, 95)]), [slot(0, 1, D=5)])
        c = out["closed"][0]
        self.assertEqual((c["exit_request_time"], c["exit_time"], c["L"], c["arm"]), (1, 2, -5, False))
        self.assertEqual(c["pnl0"], -122)

    def test_no_fixed_250_tp(self):
        """250を越えても固定利確せず、場末タイマーで返済する。

        引数: なし。
        返り値: None。
        """
        out = run_fixture(quotes([(0, 99, 100), (1, 99, 100), (2, 400, 401), (51, 390, 391)]), [slot(0, 1, D=125)])
        self.assertEqual((out["closed"][0]["exit_request_time"], out["closed"][0]["exit_reason"]), (50, "場末強制"))

    def test_entry_delay_and_ttl_equality(self):
        """+1秒前は不約定、TTL30秒等号は約定可能とする。

        引数: なし。
        返り値: None。
        """
        early = run_fixture(quotes([(0, 99, 100), (0.9, 90, 91), (1, 99, 100), (51, 100, 101)]), [slot(0, 1)])
        boundary = run_fixture(quotes([(0, 99, 100), (30, 99, 100), (51, 100, 101)]), [slot(0, 1)])
        late = run_fixture(quotes([(0, 99, 100), (30.01, 99, 100), (51, 100, 101)]), [slot(0, 1)])
        self.assertEqual(early["closed"][0]["entry_time"], 1)
        self.assertEqual(boundary["closed"][0]["entry_time"], 30)
        self.assertFalse(late["trades"])
        self.assertEqual(late["orders"][0]["cancel_time"], 30)

    def test_valid_quantity_flag_and_invalid_slot_no_retry(self):
        """良い価格でもvalid=Falseを売買に使わず、枠を再試行しない。

        引数: なし。
        返り値: None。
        """
        invalid = run_fixture(quotes([(0, 99, 100, False), (1, 99, 100), (2, 99, 100)]), [slot(0, 1)])
        self.assertEqual(invalid["decisions"][0]["action"], "判定不能")
        self.assertFalse(invalid["orders"])
        self.assertFalse(invalid["quality"]["活動評価適格"])
        pending = run_fixture(quotes([(0, 99, 100), (1, 99, 100, False), (2, 99, 100), (51, 100, 101)]), [slot(0, 1)])
        self.assertEqual(pending["closed"][0]["entry_time"], 2)

    def test_holding_ready_and_invalid_bbo_priority(self):
        """保有はready不問だが、非正常BBOは判定不能を優先する。

        引数: なし。
        返り値: None。
        """
        out = run_fixture(quotes([(0, 99, 100), (1, 99, 100), (2, 100, 101), (3, 100, 101, False), (51, 100, 101)]), [slot(0, 1), slot(2, 3, side=0, ready=False), slot(3, 4, side=0)])
        self.assertEqual([r["action"] for r in out["decisions"]], ["買い新規要求", "保有継続", "判定不能"])
        self.assertTrue(out["decisions"][2]["holding"])
        self.assertEqual(out["metrics"]["主待ち率"], 0)
        self.assertTrue(out["metrics"]["待ち率条件適格"])
        self.assertFalse(out["metrics"]["全枠判定可能"])

    def test_missing_slot_is_historical_timer(self):
        """欠測枠を後日のイベント時点でなく予定時計の保有へ結ぶ。

        引数: なし。
        返り値: None。
        """
        out = run_fixture(quotes([(0, 99, 100), (1, 99, 100), (3, 90, 91), (4, 90, 91)]), [slot(0, 1, D=5), slot(2, None, side=0, ready=False)])
        missing = out["decisions"][1]
        self.assertEqual((missing["time"], missing["line"], missing["action"], missing["holding"]), (2, None, "判定不能", True))
        self.assertEqual(out["closed"][0]["exit_request_time"], 3)

    def test_slot_delay_boundary_and_first_event_contract(self):
        """30秒境界と、非正常BBOを飛ばした根拠の拒否を確認する。

        引数: なし。
        返り値: None。
        """
        good = run_fixture(quotes([(30, 99, 100), (31, 99, 100), (51, 100, 101)]), [slot(30, 1, scheduled=0)])
        self.assertEqual(good["decisions"][0]["time"], 30)
        with self.assertRaises(ValueError):
            run_fixture(quotes([(31, 99, 100)]), [slot(31, 1, scheduled=0)])
        with self.assertRaises(ValueError):
            run_fixture(quotes([(0, 99, 100, False), (1, 99, 100)]), [slot(1, 2, scheduled=0)])

    def test_pending_classification_and_new_slot_after_exit_fill(self):
        """処理中と、旧返済fill後の同原行の新規要求を区別する。

        引数: なし。
        返り値: None。
        """
        out = run_fixture(quotes([(0, 99, 100), (0.5, 99, 100), (1, 99, 100), (2, 95, 96), (3, 95, 96), (4, 95, 96), (51, 95, 96)]), [slot(0, 1, D=5), slot(0.5, 2, side=-1), slot(3, 5, side=-1, role="反転", D=5)])
        self.assertEqual([r["action"] for r in out["decisions"]], ["買い新規要求", "処理中", "売り新規要求"])
        self.assertEqual([r["entry_time"] for r in out["closed"]], [1, 4])

    def test_force_independent_timer_and_line(self):
        """強制要求を気配到着へ遅らせず、force+1/後行で約定する。

        引数: なし。
        返り値: None。
        """
        out = run_fixture(quotes([(0, 99, 100), (1, 99, 100), (50.5, 100, 101), (51, 100, 101)]), [slot(0, 1)])
        c = out["closed"][0]
        self.assertEqual((c["exit_request_time"], c["exit_request_line"], c["exit_time"]), (50, 2, 51))

    def test_no_fictitious_close_and_open_entry_fee(self):
        """未解消を最終値で埋めず、新規費用だけを台帳へ含める。

        引数: なし。
        返り値: None。
        """
        out = run_fixture(quotes([(0, 99, 100), (1, 99, 100)]), [slot(0, 1)])
        self.assertEqual((len(out["trades"]), len(out["closed"])), (1, 0))
        self.assertEqual(out["metrics"]["完結取引観測純額円"], {"0": 0, "5": 0, "10": 0})
        self.assertEqual(out["metrics"]["約定台帳観測確定円"], {"0": -11, "5": -61, "10": -111})
        self.assertEqual(out["metrics"]["全体確定対象円"], {"0": None, "5": None, "10": None})
        self.assertEqual(out["final_state"]["pending"]["request_time"], 50)

    def test_end_half_open(self):
        """終了直前の正常BBOだけを使い、終了等号で架空の返済を作らない。

        引数: なし。
        返り値: None。
        """
        before = run_fixture(quotes([(0, 99, 100), (1, 99, 100), (59.999, 100, 101)]), [slot(0, 1)])
        exact = run_fixture(quotes([(0, 99, 100), (1, 99, 100), (60, 100, 101)]), [slot(0, 1)])
        self.assertEqual(before["closed"][0]["exit_time"], 59.999)
        self.assertFalse(exact["closed"])
        self.assertFalse(exact["quality"]["損益確定可能"])

    def test_conservative_activity_upper_bound(self):
        """判定不能1/2と保有1/2は上限等号で許し、不能2/2は不適格にする。

        引数: なし。
        返り値: None。
        """
        half = O.activity_metrics([{"action": "判定不能"}, {"action": "保有継続"}])
        unknown = O.activity_metrics([{"action": "判定不能"}, {"action": "判定不能"}])
        self.assertEqual((half["主待ち率"], half["保守待ち率上限"], half["待ち率条件適格"], half["全枠判定可能"]), (0, 0.5, True, False))
        self.assertEqual((unknown["保守待ち率上限"], unknown["待ち率条件適格"]), (1, False))

    def test_gap_exposure_and_idle_diagnostics(self):
        """保有をまたぐ長gapだけ損益不適格とし、空きは診断に留める。

        引数: なし。
        返り値: None。
        """
        exposed = run_fixture(quotes([(0, 99, 100), (1, 99, 100), (302, 100, 101), (401, 100, 101), (501, 100, 101)]), [slot(0, 1)], force=500, end=510)
        idle = run_fixture(quotes([(0, 99, 100), (400, 99, 100)]), [slot(0, 1, side=0), slot(400, 2, side=0)], force=500, end=510)
        entry_pending = run_fixture(quotes([(0, 99, 100), (400, 99, 100)]), [slot(0, 1)], force=500, end=510)
        self.assertEqual(exposed["quality"]["保有中長気配間隔数"], 1)
        self.assertFalse(exposed["quality"]["損益確定可能"])
        self.assertEqual(idle["quality"]["空き時間長気配間隔数"], 1)
        self.assertTrue(idle["quality"]["損益確定可能"])
        self.assertEqual(entry_pending["quality"]["新規待機長気配間隔数"], 1)
        self.assertTrue(entry_pending["quality"]["損益確定可能"])

    def test_clock_skip_and_input_immutability(self):
        """欠測/後退時計を飛ばし、入力辞書へラベル等を追記しない。

        引数: なし。
        返り値: None。
        """
        events = quotes([(None, 99, 100), (1, 99, 100), (2, 99, 100), (1.5, 50, 51), (51, 100, 101)])
        slots = [slot(1, 2)]
        before = deepcopy((events, slots))
        out = run_fixture(events, slots)
        self.assertEqual((out["quality"]["時計不正行数"], out["quality"]["時計後退行数"]), (1, 1))
        self.assertEqual((events, slots), before)

    def test_future_label_and_invalid_D_rejected(self):
        """未来label・context混入と保護幅範囲外を拒否する。

        引数: なし。
        返り値: None。
        """
        events, slots = quotes([(0, 99, 100), (1, 99, 100)]), [slot(0, 1)]
        for d in (4.99, 125.01, float("nan")):
            with self.assertRaises(ValueError):
                run_fixture(events, [slot(0, 1, D=d)])
        with self.assertRaises(ValueError):
            run_fixture(events, [{**slots[0], "label": "順行先着"}])
        with self.assertRaises(ValueError):
            run_fixture([{**events[0], "label": "順行先着"}], slots)
        with self.assertRaises(ValueError):
            run_fixture(events, [{**slots[0], "reason": {"未来label": True}}])

    def test_all_scheduled_slots_remain_denominator(self):
        """全予定枠を欠測でも残し、0待ちだけで適格にしない。

        引数: なし。
        返り値: None。
        """
        scheduled = O.scheduled_times("2026-11-06_Day")
        out = O.replay([], [slot(t, None, side=0, ready=False) for t in scheduled], "2026-11-06_Day")
        self.assertEqual((out["metrics"]["予定枠数"], out["metrics"]["主待ち率"]), (25, 0))
        self.assertFalse(out["metrics"]["待ち率条件適格"])


def run_tests() -> dict:
    """相場未使用の人工一式を実行し、明示合否とコード指紋を返す。

    引数: なし。
    返り値: dictは人工結果。市場・準備・主金融・保存診断を起動しない。
    """
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(OperationTests)
    count = suite.countTestCases()
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return {"全件成功": result.wasSuccessful(), "人工件数": count, "失敗数": len(result.failures), "例外数": len(result.errors), "実相場使用": False, "コードSHA256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE / "運用.py", Path(__file__))}}


def main() -> None:
    """人工結果を表示し、指定がある場合だけ小型証明を保存する。

    引数: --output(Path|None)は任意の保存先。
    返り値: None。不合格なら終了コード1。
    """
    parser = argparse.ArgumentParser(description="相場を使わない定時運用の人工境界")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_tests()
    body = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(body, encoding="utf-8")
    print(body)
    if not result["全件成功"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
