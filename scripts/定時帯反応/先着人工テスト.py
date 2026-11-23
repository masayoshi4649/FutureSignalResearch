"""入口先着の境界・空白・期限を人工気配で検証する。"""

import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location("定時帯先着検証", Path(__file__).with_name("検証.py"))
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def event(now: float, bid: float, ask: float, line: int | None = None) -> dict:
    """正常人工気配を作る。

    引数: now(float)は時計、bid/ask(float)は気配、line(int|None)は行。
    返り値: dictは原行付きイベント。
    """
    return {"now": now, "line": int(now) if line is None else line, "bid": bid, "ask": ask, "valid": True}


def slot(side: int = 1) -> dict:
    """人工新規判断を作る。

    引数: side(int)は方向。
    返り値: dictは未来結果を持たない定時入口。
    """
    return {"slot_id": "人工", "session": "2026-09-21_Day", "policy": "S0", "scheduled": 0,
            "time": 0, "line": 0, "side": side, "role": "順行"}


class LabelTests(unittest.TestCase):
    """先着評価と現実約定を混同しないための境界検査。"""

    def test_barrier_and_mirror(self):
        """買い/売りの鏡像と125/250等号を検査する。

        引数: self(LabelTests)はテスト状態。
        返り値: None。
        """
        for target, expected in ((250, "250"), (-125, "125")):
            rows = [event(1, 990, 1000), event(2, 1000 + target, 1010 + target)]
            a = M.label(rows, slot(), 600)
            mirror = [{**r, "bid": 3000 - r["ask"], "ask": 3000 - r["bid"]} for r in rows]
            b = M.label(mirror, slot(-1), 600)
            self.assertEqual((a["outcome"], b["outcome"]), (expected, expected))

    def test_latency_ttl(self):
        """1秒前や有効期限超過の約定を拒否する。

        引数: self(LabelTests)はテスト状態。
        返り値: None。
        """
        for t, expected in ((.9, False), (30, True), (30.01, False)):
            self.assertEqual(M.label([event(t, 990, 1000, 10)], slot(), 600)["filled"], expected)

    def test_gap_and_eof(self):
        """到達前空白と末尾不足を成功へ置換しない。

        引数: self(LabelTests)はテスト状態。
        返り値: None。
        """
        rows = [event(1, 990, 1000), event(302, 1250, 1260)]
        self.assertEqual(M.label(rows, slot(), 600)["outcome"], "不足")
        self.assertEqual(M.label(rows[:1], slot(), 600)["outcome"], "不足")
        self.assertEqual(M.label([event(1, 990, 1000), event(301, 1250, 1260)], slot(), 600)["outcome"], "250")

    def test_expiry(self):
        """期限後の到達を先着にしない。

        引数: self(LabelTests)はテスト状態。
        返り値: None。
        """
        self.assertEqual(M.label([event(1, 990, 1000), event(200, 1250, 1260)], slot(), 100)["outcome"], "期限")
        self.assertEqual(M.label([event(1, 990, 1000), event(600, 1250, 1260)], slot(), 500)["outcome"], "不足")

    def test_normal_flag(self):
        """数量不正flagを価格だけで救済しない。

        引数: self(LabelTests)はテスト状態。
        返り値: None。
        """
        self.assertFalse(M.normal({**event(1, 990, 1000), "valid": False}))


if __name__ == "__main__":
    unittest.main()
