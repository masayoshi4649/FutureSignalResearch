"""定時callbackの欠測消費と、最初の板を取り直さない接続を検査する。"""

from datetime import datetime
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest


def load_main():
    """市場処理を起動せず実行adapterだけを読む。

    引数: なし。
    返り値: ModuleTypeは検証モジュール。
    """
    spec = importlib.util.spec_from_file_location("局所再開_接続検査対象", Path(__file__).with_name("検証.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


M = load_main()


class Probe:
    """入力値を出力へ保存する、時刻接続専用の偽信号器。"""

    def __init__(self, bank: dict, session: str) -> None:
        """呼出し履歴を初期化する。

        引数: bank(dict)は未使用、session(str)は対象場。
        返り値: None。
        """
        self.count = 0

    def evaluate(self, scheduled: float, time: float, line: int | None, bbo_ok: bool) -> dict:
        """欠測を含む各呼出しの順序を記録する。

        引数: scheduled/time(float)は予定/実時計、line(int|None)は原行、bbo_ok(bool)は板判定。
        返り値: dictは二候補の偽特徴。
        """
        self.count += 1
        return {p: {"side": 0, "role": "待機", "atr": None, "D": None, "ready": bbo_ok,
                    "reason": "接続検査", "calls": self.count, "observed": [scheduled, time, line, bbo_ok]}
                for p in M.POLICIES}


class ConnectionTests(unittest.TestCase):
    """実値計算と独立した時計・候補分離の接続検査。"""

    def test_missing_consumed_every_slot(self) -> None:
        """全欠測でも25/49回の状態消費が呼ばれることを確認する。

        引数: なし。
        返り値: None。
        """
        for session, count in (("2026-11-04_Day", 25), ("2026-11-04_Night", 49)):
            result = M.make_slots([], session, {}, SimpleNamespace(SessionSignals=Probe))
            for policy in M.POLICIES:
                self.assertEqual(len(result[policy]), count)
                self.assertEqual([r["calls"] for r in result[policy]], list(range(1, count + 1)))
                self.assertTrue(all(r["line"] is None and r["time"] == r["scheduled"] and not r["ready"] for r in result[policy]))
                self.assertTrue(all(r["policy"] == policy for r in result[policy]))

    def test_first_invalid_not_retried(self) -> None:
        """最初の不正板を後続の正常板に取り直さないことを確認する。

        引数: なし。
        返り値: None。
        """
        session = "2026-11-04_Day"
        t = M.O.scheduled_times(session)[0]
        events = [{"now": t, "line": 10, "last": 100, "bid": 100, "ask": 100, "valid": True},
                  {"now": t + 1, "line": 11, "last": 100, "bid": 100, "ask": 105, "valid": True}]
        result = M.make_slots(events, session, {}, SimpleNamespace(SessionSignals=Probe))
        self.assertEqual(result["P0"][0]["line"], 10)
        self.assertFalse(result["P0"][0]["ready"])
        self.assertEqual(result["P0"][0]["observed"], [t, t, 10, False])

    def test_thirty_second_boundary(self) -> None:
        """判断猶予30秒を含め31秒を除くことを確認する。

        引数: なし。
        返り値: None。
        """
        session = "2026-11-04_Day"
        t = M.O.scheduled_times(session)[0]
        for delay, accepted in ((30, True), (31, False)):
            event = {"now": t + delay, "line": 10, "last": 100, "bid": 100, "ask": 105, "valid": True}
            result = M.make_slots([event], session, {}, SimpleNamespace(SessionSignals=Probe))
            self.assertEqual(result["P1"][0]["ready"], accepted)
            self.assertEqual(result["P1"][0]["line"], 10 if accepted else None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
