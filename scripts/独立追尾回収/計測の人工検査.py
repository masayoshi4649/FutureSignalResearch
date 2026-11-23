"""固定O49全期間singletonと、prefix継承した独立測定を人工で照合する。"""

from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location("独立追尾回収の人工対象", Path(__file__).with_name("計測.py"))
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
O = M.O49
BOUNDS = {"start": 0, "force": 100, "end": 110}
SESSION = "人工_Day"


def events(values: list[tuple]) -> list[dict]:
    """人工の時刻・気配・flagを原行strict昇順の6列へ写す。

    引数: values(list[tuple])は(now,bid,ask[,valid])。
    返り値: list[dict]は原市場を使わない入力。
    """
    return [{"now": t, "line": i + 1, "last": (bid + ask) / 2, "bid": bid, "ask": ask, "valid": valid[0] if valid else True}
        for i, (t, bid, ask, *valid) in enumerate(values)]


def slot(tape: list[dict], scheduled: float = 10, side: int = 1, distance: float = 40) -> dict:
    """人工入力の予定以後最初の原行を純slotへ対応させる。

    引数: tape(list[dict])は人工6列、scheduled(float)は予定、side(int)は±1、distance(float)はD。
    返り値: dictは純O49判断。正常flagで原行を待ち直さない。
    """
    first = next((e for e in tape if scheduled <= e["now"] <= scheduled + 30), None)
    return {"slot_id": "人工枠", "scheduled": scheduled, "time": first["now"] if first else scheduled,
        "line": first["line"] if first else None, "side": side, "role": "順行", "atr": distance, "D": distance,
        "reason": "人工", "ready": first is not None}


def mirrored(tape: list[dict]) -> list[dict]:
    """価格を1000−価格で反射し、bid/askの役割も交換する。

    引数: tape(list[dict])は正の人工気配。
    返り値: list[dict]は時刻・原行・正常flagを保つ鏡像。
    """
    return [{**e, "last": 1000 - e["last"], "bid": 1000 - e["ask"], "ask": 1000 - e["bid"]} for e in tape]


class ArtificialTests(unittest.TestCase):
    """経済的全属性・品質・prefix・同秒境界を人工で確認する。"""

    def compare(self, tape: list[dict], pure: dict, bounds: dict = BOUNDS) -> tuple[dict, dict]:
        """同じ全期間singletonと高速法を公開射影で比較する。

        引数: tape(list[dict])は人工入力、pure(dict)は一枠、bounds(dict)は人工場境界。
        返り値: tuple[dict,dict]は全期間結果と高速結果。
        """
        before_tape, before_slot = deepcopy(tape), deepcopy(pure)
        full = O.replay(tape, [pure], SESSION, "人工候補", bounds)
        fast = M.MeasurementBank(tape, SESSION, bounds).measure(pure, "人工候補")
        self.assertEqual(M.comparison_view(fast), M.comparison_view(full))
        self.assertEqual(tape, before_tape)
        self.assertEqual(pure, before_slot)
        self.assertEqual(fast["measurement"]["予定枠分母"], 1)
        return full, fast

    def test_現在正strictと名目床と鏡像(self) -> None:
        """12.2pt等号不起動・12.3正起動と名目床返済を売買両側で照合する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        tape = events([(0, 99, 100), (5, 99, 100, False), (10, 99, 100), (11, 99, 100),
            (12, 112.2, 113.2), (13, 112.3, 113.3), (14, 100, 101), (15, 99, 100), (105, 102, 103)])
        for inputs, side in ((tape, 1), (mirrored(tape), -1)):
            _, fast = self.compare(inputs, slot(inputs, side=side))
            row = fast["closed"][0]
            self.assertEqual((row["arm_time"], row["exit_request_time"], row["exit_time"]), (13, 14, 15))
            self.assertEqual((row["arm_net"], row["L"], row["pnl5"]), (1, 0, -132))

    def test_返済pending中は保護凍結し実MFE継続(self) -> None:
        """+1秒前の再上昇を保護旗へ戻さず、実経路だけ更新する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        tape = events([(0, 99, 100), (10, 99, 100), (11, 99, 100), (12, 120, 121),
            (13, 100, 101), (13.5, 150, 151), (14, 99, 100), (105, 99, 100)])
        _, fast = self.compare(tape, slot(tape))
        row = fast["closed"][0]
        self.assertEqual((row["h"], row["mfe"], row["L"], row["exit_request_time"]), (20, 50, 0, 13))

    def test_正常flagと新規TTL等号(self) -> None:
        """見た目の価格が正常でもvalid=Falseをfillへ使わず、TTL等号は認める。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        tape = events([(0, 99, 100), (10, 99, 100), (11, 98, 99, False), (40, 99, 100, False),
            (40, 99, 100), (100, 100, 101), (101, 100, 101), (109, 100, 101)])
        _, fast = self.compare(tape, slot(tape))
        self.assertEqual(fast["closed"][0]["entry_time"], 40)
        self.assertEqual(fast["closed"][0]["entry_line"], 5)
        late = deepcopy(tape)
        late[4]["now"] = 40.1
        _, cancelled = self.compare(late, slot(late))
        self.assertEqual(cancelled["closed"], [])
        self.assertEqual((cancelled["orders"][0]["cancel_time"], cancelled["orders"][0]["cancel_reason"]), (40, "新規TTL30秒"))

    def test_force独立タイマーと同秒原行(self) -> None:
        """force当秒の気配で約定せず、前既知原行から要求し+1秒で返す。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        tape = events([(0, 99, 100), (90, 99, 100), (91, 99, 100), (100, 100, 101),
            (100, 101, 102), (101, 101, 102, False), (101, 102, 103), (109, 99, 100)])
        _, fast = self.compare(tape, slot(tape, scheduled=90))
        row = fast["closed"][0]
        self.assertEqual((row["exit_request_time"], row["exit_request_line"], row["exit_time"], row["exit_line"]), (100, 3, 101, 7))
        self.assertEqual(row["exit_reason"], "場末強制")
        no_fill = events([(0, 99, 100), (90, 99, 100), (100, 99, 100), (101, 99, 100)])
        _, cancelled = self.compare(no_fill, slot(no_fill, scheduled=90))
        self.assertEqual(cancelled["closed"], [])
        self.assertEqual((cancelled["orders"][0]["cancel_time"], cancelled["orders"][0]["cancel_reason"]), (100, "強制時刻"))

    def test_未解消は新規費用とnullを保持(self) -> None:
        """末尾に返済気配が無ければ架空返済せず、費用だけの台帳とnullを保つ。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        tape = events([(0, 99, 100), (10, 99, 100), (11, 99, 100)])
        _, fast = self.compare(tape, slot(tape))
        self.assertEqual(fast["closed"], [])
        self.assertEqual(fast["metrics"]["約定台帳観測確定円"], {"0": -11, "5": -61, "10": -111})
        self.assertEqual(fast["metrics"]["全体確定対象円"], {"0": None, "5": None, "10": None})
        self.assertEqual((fast["quality"]["未解消建玉数"], fast["quality"]["未解消注文数"]), (1, 1))

    def test_保有中長gapと300秒等号(self) -> None:
        """切出前の正常気配も残し、保有中gap>300だけを損益注意へ結ぶ。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        bounds = {"start": 0, "force": 1000, "end": 1010}
        for after, cautions in ((311, 0), (311.1, 1)):
            tape = events([(0, 99, 100), (9, 99, 100, False), (10, 99, 100), (11, 99, 100),
                (after, 100, 101), (600, 100, 101), (899, 100, 101), (1000, 100, 101), (1001, 100, 101)])
            _, fast = self.compare(tape, slot(tape), bounds)
            self.assertEqual(fast["measurement"]["prefix"]["last_quote_time"], 0)
            self.assertEqual(fast["quality"]["損益確定可能"], cautions == 0)
            self.assertEqual(fast["quality"]["保有中長気配間隔数"], cautions)

    def test_新規約定同quoteの広いspreadで保護要求(self) -> None:
        """新規fill直後から返済側BBOで保護し、同quoteでは返済約定しない。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        tape = events([(0, 99, 100), (10, 99, 100), (11, 90, 100), (11.5, 91, 100), (12, 90, 100), (105, 99, 100)])
        _, fast = self.compare(tape, slot(tape, distance=5))
        row = fast["closed"][0]
        self.assertEqual((row["entry_time"], row["exit_request_time"], row["exit_time"], row["pnl5"]), (11, 11, 12, -222))

    def test_新規pending長gapは損益注意にしない(self) -> None:
        """新規取消後のflat走査を省いても、単体pnl品質を悪化/救済しない。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        bounds = {"start": 0, "force": 1000, "end": 1010}
        tape = events([(0, 99, 100), (10, 99, 100), (50, 99, 100, False), (500, 99, 100), (1001, 99, 100)])
        full, fast = self.compare(tape, slot(tape), bounds)
        self.assertTrue(fast["quality"]["損益確定可能"])
        self.assertEqual(fast["orders"][0]["cancel_reason"], "新規TTL30秒")
        self.assertEqual(full["quality"]["新規待機長気配間隔数"], 1)
        self.assertEqual(fast["quality"]["新規待機長気配間隔数"], 0)

    def test_prefixのflat品質と元入力不変(self) -> None:
        """prefix品質を引継ぎ、銀行構築後に元辞書が変わっても内部原行を保つ。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        bounds = {"start": 0, "force": 1000, "end": 1010}
        tape = events([(0, 99, 100), (301, 99, 100), (310, 99, 100, False), (320, 99, 100),
            (321, 99, 100), (322, 80, 81), (323, 80, 81), (1001, 99, 100)])
        pure = slot(tape, scheduled=320, distance=5)
        original = deepcopy(tape)
        bank = M.MeasurementBank(tape, SESSION, bounds)
        tape[0]["bid"] = 1
        first = bank.measure(pure, "人工候補")
        full = O.replay(original, [pure], SESSION, "人工候補", bounds)
        self.assertEqual(M.comparison_view(first), M.comparison_view(full))
        prefix = first["measurement"]["prefix"]
        self.assertEqual((prefix["last_time"], prefix["last_line"], prefix["raw_line"], prefix["last_quote_time"], prefix["非正常BBO行数"], prefix["空き時間長気配間隔数"]), (310, 3, 3, 301, 1, 1))

    def test_無効BBOと欠測placeholderと無新規(self) -> None:
        """原行のinvalidを待ち直さず、欠測timerとside0の無新規も一致させる。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        tape = events([(0, 99, 100), (10, 99, 100, False), (11, 99, 100), (105, 99, 100)])
        _, invalid = self.compare(tape, slot(tape))
        self.assertEqual(invalid["decisions"][0]["action"], "判定不能")
        later = deepcopy(slot(tape))
        later.update(time=11, line=3)
        with self.assertRaises(ValueError):
            M.MeasurementBank(tape, SESSION, BOUNDS).measure(later)
        missing = {**slot(tape), "line": None, "time": 10, "ready": False, "reason": "判断時計欠測"}
        self.compare(tape, missing)
        self.compare(events([(0, 99, 100)]), missing)
        flat = slot(tape, side=0)
        self.compare(tape, flat)

    def test_銀行の複数測定とDI0説明(self) -> None:
        """同じ銀行を方向ごとに使っても建玉を引継がず、DI同値を説明へ残す。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        tape = events([(0, 99, 100), (10, 99, 100), (11, 99, 100), (12, 120, 121), (13, 100, 101), (14, 99, 100), (101, 99, 100)])
        bank = M.MeasurementBank(tape, SESSION, BOUNDS)
        one = bank.measure(slot(tape), "人工候補", background_direction=0)
        two = bank.measure(slot(tape, side=-1), "人工候補")
        again = bank.measure(slot(tape), "人工候補", background_direction=0)
        self.assertEqual(one, again)
        self.assertIn("DI同値", one["measurement"]["役割説明"])
        self.assertEqual(M.comparison_view(two), M.comparison_view(O.replay(tape, [slot(tape, side=-1)], SESSION, "人工候補", BOUNDS)))

    def test_場内入力と純判断契約を拒否で守る(self) -> None:
        """後退/場外/未来label列を拒否し、half-open終了境界を曖昧にしない。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        tape = events([(0, 99, 100), (10, 99, 100), (11, 99, 100)])
        for key, value in (("now", -1), ("line", 0), ("now", 110), ("valid", 1)):
            invalid = deepcopy(tape)
            invalid[1][key] = value
            with self.assertRaises(ValueError):
                M.MeasurementBank(invalid, SESSION, BOUNDS)
        contaminated = deepcopy(slot(tape))
        contaminated["outcome"] = "250"
        with self.assertRaises(ValueError):
            M.MeasurementBank(tape, SESSION, BOUNDS).measure(contaminated)
        invalid = deepcopy(tape)
        invalid[0]["future"] = 1
        with self.assertRaises(ValueError):
            M.MeasurementBank(invalid, SESSION, BOUNDS)


def run() -> dict:
    """人工市場だけで全期間O49と高速測定を照合する。

    引数: なし。
    返り値: dictは人工成功件数と固定O49指紋。実市場・教師・fitを使わない。
    """
    capture = io.StringIO()
    result = unittest.TextTestRunner(stream=capture, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ArtificialTests))
    return {"全件一致": result.wasSuccessful(), "人工件数": result.testsRun, "失敗数": len(result.failures), "エラー数": len(result.errors),
        "固定運用SHA256": M.OPERATION_SHA256, "市場入力読取": False, "実モデル学習": False,
        "詳細": "" if result.wasSuccessful() else capture.getvalue()}


if __name__ == "__main__":
    value = run()
    print(json.dumps(value, ensure_ascii=False))
    raise SystemExit(0 if value["全件一致"] else 1)
