"""市場ファイルなしで、局所監視・公開時計・定時消費を人工検査する。"""

from copy import deepcopy
from fractions import Fraction
import importlib.util
from pathlib import Path
import sys
import unittest


SPEC = importlib.util.spec_from_file_location("局所再開の人工対象", Path(__file__).with_name("入口.py"))
I = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = I
SPEC.loader.exec_module(I)


def frame(index: int, close: float = 100, high: float | None = None,
          low: float | None = None, minutes: int = 3) -> dict:
    """完全公開の人工SOURCE足を作る。

    引数: index(int)は番号、close(float)は終値、high/low(float|None)は高安、minutes(int)は幅。
    返り値: dictはSOURCE12。原板を開かない。
    """
    end = (index + 1) * minutes * 60
    return {"index": index, "minutes": minutes, "start": index * minutes * 60, "end": end,
            "confirm": end, "confirm_line": index + 1, "publish": True, "missing": 0,
            "open": close, "high": close + 1 if high is None else high,
            "low": close - 1 if low is None else low, "close": close}


def raw(rows: list[dict]) -> dict:
    """3/15分の小さな人工場をまとめる。

    引数: rows(list[dict])は3分系列。
    返り値: dictは49build_bankの入力。
    """
    return {"session": "人工場", "contract": ("人工限月",), "begin": 0, "end": len(rows) * 180,
            "frames3": rows, "frames15": [frame(i, minutes=15) for i in range(len(rows) // 5)]}


def bank(kind: str = "T", b: int = 12, trigger: int = 16, mirror: bool = False) -> dict:
    """状態機械の入力を、明示した価格とFast/DI状態で作る。

    引数: kind(str)はT/R/旧R、b(int)は起点、trigger(int)は発動、
        mirror(bool)は価格と方向を反射するか。
    返り値: dictは人工銀行。Fast/DIは監視機械の単体入力として明示設定する。
    """
    rows = [frame(i) for i in range(45)]
    for i in range(10):
        rows[i] = frame(i, high=110, low=90)
    changes = {}
    if kind == "T":
        for i in range(10, 45):
            rows[i] = frame(i, close=124)
        rows[b] = frame(b, close=120)
        for i in range(b + 1, trigger):
            rows[i] = frame(i, close=120)
        for i in range(trigger, 45):
            rows[i] = frame(i, close=124 + i - trigger)
        changes[b] = -1
    elif kind == "R":
        for i in range(b, trigger - 1):
            rows[i] = frame(i, close=120)
        f = trigger - 1
        rows[f] = frame(f, close=104, high=105, low=103)
        changes[f] = -1
        for i in range(trigger, 45):
            rows[i] = frame(i, close=100, high=101, low=99)
    else:
        for i in range(10, 45):
            rows[i] = frame(i, close=103, high=104, low=102)
            changes[i] = -1
        rows[16] = frame(16, close=108, high=120, low=106)
    if mirror:
        for row in rows:
            row["open"], row["close"] = 300 - row["open"], 300 - row["close"]
            row["high"], row["low"] = 300 - row["low"], 300 - row["high"]
    result = I.build_bank([raw(rows)])
    for row in result["人工場"]["frames3"]:
        row.update(atr=10.0, fast_k=I.I49.exact(Fraction(40 if mirror else 60)),
                   fast_previous=I.I49.exact(Fraction(40 if mirror else 60)),
                   fast_change=I.I49.exact(Fraction(changes.get(row["index"], 0) * (-1 if mirror else 1))))
    for row in result["人工場"]["frames15"]:
        row.update(plus_di=0 if mirror or kind != "T" else 20,
                   minus_di=20 if mirror and kind == "T" else 0, adx=50)
    return result


def evaluate(machine: object, scheduled: float = 3600, line: int | None = 999,
             bbo_ok: bool = True) -> dict:
    """一枠の人工callbackを呼ぶ。

    引数: machine(object)はSessionSignals、scheduled(float)は予定、
        line(int|None)は原行、bbo_ok(bool)は気配正常性。
    返り値: dictはP0/P1の特徴。
    """
    return machine.evaluate(scheduled, scheduled, line, bbo_ok)


class SignalTests(unittest.TestCase):
    """段階と消費を、期待する方向・ID・取消理由へ照合する。"""

    def test_t_and_r_mirror(self) -> None:
        """新Tと新Rが反射で符号だけを反転する。

        引数: なし。
        返り値: None。
        """
        for kind, side in (("T", 1), ("R", -1)):
            for mirror in (False, True):
                result = evaluate(I.SessionSignals(bank(kind, mirror=mirror), "人工場"))
                self.assertEqual(result["P1"]["side"], -side if mirror else side)
                self.assertEqual(result["P1"]["role"], "順行" if kind == "T" else "反転")
                self.assertEqual(result["P1"]["D"], 10)
                self.assertEqual(len(result["P1"]["diagnostic"]["consumed_ids"]), 1)

    def test_real_49_numeric_path(self) -> None:
        """手置きDI/Fastを使わない人工価格でも押し戻り→再開を認識する。

        引数: なし。
        返り値: None。
        """
        rows = [frame(i, close=100 + 2 * i) for i in range(100)]
        rows[91] = frame(91, close=277)
        item = raw(rows)
        item["frames15"] = [frame(i, close=100 + 10 * i, minutes=15) for i in range(20)]
        result = evaluate(I.SessionSignals(I.build_bank([item]), "人工場"), 17100)
        self.assertEqual(result["P1"]["side"], 1)
        event = result["P1"]["diagnostic"]["candidate_events"][0]
        self.assertEqual((event["origin_index"], event["trigger_index"]), (91, 92))

    def test_consumed_once(self) -> None:
        """採用後に同じ発動を次枠へ再掲しない。

        引数: なし。
        返り値: None。
        """
        machine = I.SessionSignals(bank(), "人工場")
        first = evaluate(machine)
        second = evaluate(machine, 4500)
        self.assertEqual(first["P1"]["side"], 1)
        self.assertEqual(second["P1"]["side"], 0)
        self.assertEqual(second["P1"]["diagnostic"]["consumed_ids"], [])

    def test_bad_bbo_and_missing_consume(self) -> None:
        """不正BBO・欠測callbackでも既知の初発動を消費する。

        引数: なし。
        返り値: None。
        """
        for line in (999, None):
            machine = I.SessionSignals(bank(), "人工場")
            result = evaluate(machine, line=line, bbo_ok=False)
            self.assertFalse(result["P1"]["ready"])
            self.assertEqual(len(result["P1"]["diagnostic"]["consumed_ids"]), 1)
            self.assertEqual(evaluate(machine, 4500)["P1"]["side"], 0)

    def test_900_seconds(self) -> None:
        """発動終了から900秒は有効、901秒は消費だけにする。

        引数: なし。
        返り値: None。
        """
        for scheduled, side in ((3600, 1), (3601, 0)):
            result = evaluate(I.SessionSignals(bank(b=13, trigger=14), "人工場"), scheduled)
            self.assertEqual(result["P1"]["side"], side)
            self.assertEqual(result["P1"]["diagnostic"]["consumed_events"][0]["age_seconds"], scheduled - 2700)

    def test_t_lifetime_ten(self) -> None:
        """T起点を含む10本目は可、11本目は取消を先にする。

        引数: なし。
        返り値: None。
        """
        for trigger, expected in ((20, 1), (21, 0)):
            result = evaluate(I.SessionSignals(bank(b=11, trigger=trigger), "人工場"), 4500)
            self.assertEqual(result["P1"]["side"], expected)

    def test_r_lifetime_ten(self) -> None:
        """Rのb→kも起点を含む10本で切る。

        引数: なし。
        返り値: None。
        """
        for trigger, expected in ((20, -1), (21, 0)):
            result = evaluate(I.SessionSignals(bank("R", b=11, trigger=trigger), "人工場"), 4500)
            self.assertEqual(result["P1"]["side"], expected)

    def test_same_frame_f_not_k(self) -> None:
        """復帰足fのlow自身で反転確認を成立させない。

        引数: なし。
        返り値: None。
        """
        data = bank("R", b=15, trigger=20)
        # f=index19なので、この枠まででは復帰だけが既知。
        result = evaluate(I.SessionSignals(data, "人工場"))
        self.assertEqual(result["P1"]["side"], 0)
        self.assertEqual(result["P1"]["diagnostic"]["R_watch"]["stage"], "逆端確認待ち")

    def test_post_trigger_equality_negates(self) -> None:
        """発動後の別足が否定線等号へ戻れば失効する。

        引数: なし。
        返り値: None。
        """
        data = bank()
        row = data["人工場"]["frames3"][18]
        row.update(open=121, high=122, low=120, close=121)
        result = evaluate(I.SessionSignals(data, "人工場"))
        self.assertEqual(result["P1"]["side"], 0)
        self.assertEqual(result["P1"]["diagnostic"]["consumed_events"][0]["cancel_reason"], "発動線の終値否定")

    def test_background_denial_before_t(self) -> None:
        """同足で価格が再開しても、DI背景失効を先にする。

        引数: なし。
        返り値: None。
        """
        data = bank(b=15, trigger=19)
        data["人工場"]["frames15"][3].update(plus_di=0, minus_di=20)
        result = evaluate(I.SessionSignals(data, "人工場"))
        self.assertEqual(result["P1"]["side"], 0)
        actions = result["P1"]["diagnostic"]["actions"]
        self.assertTrue(any(a["action"] == "監視取消" and a["reason"] == "T背景失効" for a in actions))
        self.assertFalse(any(a["action"] == "監視登録" and a["watch"]["kind"] == "T"
                             and a["source"]["index"] == 19 for a in actions))

    def test_r_reclaim_before_confirmation(self) -> None:
        """f後の元OR外側再獲得で監視を取消す。

        引数: なし。
        返り値: None。
        """
        data = bank("R", b=12, trigger=18)
        row = data["人工場"]["frames3"][18]
        row.update(open=115, high=116, low=114, close=115)
        for i in range(19, 21):
            data["人工場"]["frames3"][i].update(open=114, high=115, low=113, close=114)
        result = evaluate(I.SessionSignals(data, "人工場"), 4500)
        self.assertEqual(result["P1"]["side"], 0)
        self.assertTrue(any(a["action"] == "監視取消" and a["reason"] == "R元外側再獲得"
                            for a in result["P1"]["diagnostic"]["actions"]))

    def test_r_first_f_failure_consumes(self) -> None:
        """最初の復帰でFastが不一致なら後の良い復帰へ取り直さない。

        引数: なし。
        返り値: None。
        """
        data = bank("R")
        data["人工場"]["frames3"][15]["fast_change"] = I.I49.exact(Fraction(1))
        result = evaluate(I.SessionSignals(data, "人工場"))
        self.assertEqual(result["P1"]["side"], 0)
        self.assertTrue(any(a["action"] == "初回復帰見送り消費" for a in result["P1"]["diagnostic"]["actions"]))
        self.assertIsNone(result["P1"]["diagnostic"]["R_watch"])

    def test_future_and_delayed_upper(self) -> None:
        """未来上位DIを過去背景へ使わず、未公開追加のprefixを不変にする。

        引数: なし。
        返り値: None。
        """
        data = bank()
        data["人工場"]["frames15"][3].update(confirm=4000, plus_di=0, minus_di=20)
        first = evaluate(I.SessionSignals(data, "人工場"))
        prefix = deepcopy(data)
        prefix["人工場"]["frames15"] = prefix["人工場"]["frames15"][:3]
        prefix["人工場"]["frames3"] = prefix["人工場"]["frames3"][:20]
        second = evaluate(I.SessionSignals(prefix, "人工場"))
        self.assertEqual(first, second)
        self.assertEqual(first["P1"]["side"], 1)

    def test_f_missing_is_consumed_not_permanent_invalid(self) -> None:
        """fの上位不足は記録・消費し、定時準備の回復を妨げない。

        引数: なし。
        返り値: None。
        """
        data = bank("R")
        data["人工場"]["frames15"][2].update(plus_di=None, minus_di=None)
        result = evaluate(I.SessionSignals(data, "人工場"))["P1"]
        self.assertTrue(result["ready"])
        self.assertEqual(result["side"], 0)
        failures = [a for a in result["diagnostic"]["actions"] if a["action"] == "初回復帰見送り消費"]
        self.assertEqual(failures[0]["status"], "invalid")
        self.assertIsNone(result["diagnostic"]["R_watch"])

    def test_first_k_di_failure_not_retried(self) -> None:
        """初kのDI不一致を消費し、次枠の良いDIで取り直さない。

        引数: なし。
        返り値: None。
        """
        data = bank("R", b=12, trigger=19)
        data["人工場"]["frames15"][3].update(plus_di=20, minus_di=0)
        machine = I.SessionSignals(data, "人工場")
        first = evaluate(machine)["P1"]
        self.assertEqual(first["side"], 0)
        self.assertTrue(any(a["action"] == "初回逆端見送り消費" for a in first["diagnostic"]["actions"]))
        self.assertEqual(evaluate(machine, 4500)["P1"]["side"], 0)

    def test_missing_same_second_publication(self) -> None:
        """欠測keyの原行−1は予定と同秒に公開された足を可視にしない。

        引数: なし。
        返り値: None。
        """
        data = bank(b=18, trigger=19)
        machine = I.SessionSignals(data, "人工場")
        result = evaluate(machine, line=None, bbo_ok=False)
        self.assertNotIn(19, machine.processed)
        self.assertEqual(result["P1"]["diagnostic"]["consumed_ids"], [])

    def test_multiple_triggers_conflict(self) -> None:
        """同枠の二つの同方向Tも両消費してWAITにする。

        引数: なし。
        返り値: None。
        """
        data = bank(b=14, trigger=15)
        rows = data["人工場"]["frames3"]
        for index, close in ((16, 125), (17, 123), (18, 127), (19, 128)):
            rows[index].update(open=close, high=close + 1, low=close - 1, close=close)
        rows[17]["fast_change"] = I.I49.exact(Fraction(-1))
        result = evaluate(I.SessionSignals(data, "人工場"))
        self.assertEqual(result["P1"]["side"], 0)
        self.assertEqual(result["P1"]["reason"], "同枠複数発動WAIT")
        self.assertEqual(len(result["P1"]["diagnostic"]["consumed_ids"]), 2)

    def test_old_r_is_per_slot(self) -> None:
        """P0旧Rは新イベントの一回消費へ変えず49S1と一致する。

        引数: なし。
        返り値: None。
        """
        data = bank("旧R")
        machine = I.SessionSignals(data, "人工場")
        for scheduled in (3600, 4500):
            actual = evaluate(machine, scheduled)["P0"]
            old = I.I49.evaluate_slot(data, "人工場", scheduled, scheduled, 999, "S1")
            for name in ("side", "role", "atr", "D", "ready"):
                self.assertEqual(actual[name], old[name])
            self.assertEqual(actual["side"], -1)

    def test_callbacks_once_and_input_unchanged(self) -> None:
        """一枠取り直しを拒否し、呼出元の銀行を変えない。

        引数: なし。
        返り値: None。
        """
        data = bank()
        saved = deepcopy(data)
        machine = I.SessionSignals(data, "人工場")
        evaluate(machine)
        self.assertEqual(data, saved)
        with self.assertRaises(I.I49.InputError):
            evaluate(machine)


if __name__ == "__main__":
    unittest.main(verbosity=2)
