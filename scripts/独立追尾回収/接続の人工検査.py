"""表示欠測と実運用の値、独立新規の厳密対応を分離して検査する。"""

import importlib.util
import json
import math
from pathlib import Path
import sys
import unittest

SPEC = importlib.util.spec_from_file_location("独立回収接続の人工主", Path(__file__).with_name("検証.py"))
P = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = P
SPEC.loader.exec_module(P)


class Tests(unittest.TestCase):
    """記録の欠測が架空値や保存不能値へ変わらないことを確認する。"""

    def test_unready_quote_is_not_zero(self) -> None:
        """未準備を未測定のまま保存する。

        引数: なし。
        返り値: None。
        """
        slot = {"session": "2026-01-01_Day", "slot_id": "枠", "scheduled": 0, "time": 0, "line": None}
        feature = {"ready": False, "reason": "欠測", "vectors": {"1": [], "-1": []}, "background_direction": None, "atr": None, "D": None}
        row = P.measured_row(slot, feature, 1, None, None, {"last": math.nan}, "人工")
        self.assertEqual(row["status"], "技法未準備")
        self.assertIsNone(row["operation"])
        self.assertIsNone(row["decision_bbo"])
        json.dumps(row, allow_nan=False)

    def test_display_nan_does_not_change_event(self) -> None:
        """正常BBOと欠測現値を区別し、元イベントを変更しない。

        引数: なし。
        返り値: None。
        """
        slot = {"session": "2026-01-01_Day", "slot_id": "枠", "scheduled": 0, "time": 0, "line": 1}
        feature = {"ready": True, "reason": "", "vectors": {"1": [0] * 18, "-1": [0] * 18}, "background_direction": 0, "atr": 20, "D": 20}
        event = {"now": 0.0, "line": 1, "last": math.nan, "bid": 100.0, "ask": 110.0, "valid": True}
        operation = {"closed": [], "final_state": {"position": None, "pending": None}}
        row = P.measured_row(slot, feature, 1, operation, None, event, "人工")
        self.assertTrue(math.isnan(event["last"]))
        self.assertIsNone(row["decision_bbo"]["last"])
        self.assertEqual(row["role"], "上位同値")
        self.assertEqual(row["status"], "未約定")
        json.dumps(row, allow_nan=False)

    def test_strict_entry_type(self) -> None:
        """別IDを許しても約定の型違いは同じ新規と認めない。

        引数: なし。
        返り値: None。
        """
        self.assertTrue(P.equivalent_close({"id": "A", "price": 100.0}, {"id": "B", "price": 100.0}))
        self.assertFalse(P.equivalent_close({"id": "A", "price": 100.0}, {"id": "B", "price": 100}))
        self.assertFalse(P.equivalent_close({"id": "A", "price": 100.0}, {"id": "B", "price": 101.0}))


if __name__ == "__main__":
    unittest.main()
