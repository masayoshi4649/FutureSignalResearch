"""実計測部品から教師分類と主の保存経路までを架空価格で接続確認する。"""

from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(path: Path, name: str):
    """対象moduleを人工専用の固有名で読む。

    引数: path(Path)はコード、name(str)はmodule名。
    返り値: ModuleTypeは読込結果。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


A = load(HERE / "計測の人工検査.py", "69接続用の人工価格生成")
V = load(HERE / "検証.py", "69接続の主専用module")


def fixture() -> tuple:
    """利益後の返済と、その後の障壁到達が異なる人工経路を作る。

    引数: なし。
    返り値: tupleはevents/slot/feature/condition。実相場を含まない。
    """
    tape = A.events([(0, 100, 95, 100), (10, 100, 95, 100), (11, 115, 110, 115),
        (12, 115, 110, 115), (15, 140, 135, 140), (16, 100, 95, 100), (17, 100, 95, 100),
        (200, 500, 495, 500), (400, 500, 495, 500), (600, 500, 495, 500),
        (800, 500, 495, 500), (1000, 500, 495, 500)])
    slot = A.slot(tape)
    feature = {"ready": True, "background_direction": 1, "atr": 20, "D": 20,
        "vectors": {"1": [1.0] * 60, "-1": [-1.0] * 60}}
    return tape, slot, feature, A.condition(slot)


class ConnectionTests(unittest.TestCase):
    """実相場を開かず、新部品の境界を検査する。"""

    def test_measurement_to_teacher(self):
        """条件取得からの先着と回収を、別時計の教師として渡せるか検査する。

        引数: self(ConnectionTests)は試験器。
        返り値: None。不一致はAssertionError。
        """
        tape, slot, feature, condition = fixture()
        bank = A.M.MeasurementBank(tape, A.SESSION, A.BOUNDS)
        rows = {}
        for side in (1, -1):
            pure = V.I.pure_for(slot, feature, side)
            result = bank.measure(pure, condition, "接続人工", background_direction=1)
            rows[side] = V.T.describe(slot, feature, side, result["measurement"]["独立先着"], result, "条件")
        self.assertEqual(rows[1]["status"], "確定約定")
        self.assertEqual(rows[1]["row"]["outcome"], "250")
        self.assertLess(rows[1]["row"]["pnl5"], 0)
        self.assertGreater(rows[1]["row"]["end_time"], rows[1]["row"]["recovery_end_time"])
        self.assertEqual(rows[-1]["status"], "確定無取引")
        self.assertEqual((rows[-1]["row"]["filled"], rows[-1]["row"]["outcome"], rows[-1]["row"]["pnl5"]),
            (False, "無取引", 0.0))

    def test_main_measure_all(self):
        """主の全方向計測と全日比較・保存を、同じ架空一場で接続する。

        引数: self(ConnectionTests)は試験器。
        返り値: None。旧moduleのglobalや実入力は変更しない。
        """
        tape, slot, feature, condition = fixture()
        session = slot["session"]
        original_c, original_work = V.C, V.WORK

        def events_for(entry):
            """架空一場の元列を渡す。

            引数: entry(dict)は架空場識別。
            返り値: tupleは元列と人工品質。
            """
            self.assertEqual(entry["session"], session)
            return tape, {"人工": True}

        def bank_factory(events, name):
            """主の二引数銀行呼出しへ人工boundsを接続する。

            引数: events(list[dict])は架空元列、name(str)は架空場。
            返り値: MeasurementBankは実69計測器。
            """
            return A.M.MeasurementBank(events, name, A.BOUNDS)

        def replay(events, slots, conditions, name, candidate):
            """主の完全再生呼出しへ同じ人工boundsを接続する。

            引数: events/slots(list)とconditions(dict)は架空入力、name/candidate(str)は識別。
            返り値: dictは実68Engineの完全単独結果。
            """
            return A.O.replay(events, slots, conditions, name, candidate, A.BOUNDS)

        parent = ROOT / "work/条件入口の教師"
        parent.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix="接続人工_", dir=parent) as temporary:
                self.assertTrue(Path(temporary).resolve().is_relative_to(parent.resolve()))
                V.C = SimpleNamespace(events_for=events_for, jsonline=original_c.jsonline)
                V.WORK = Path(temporary)
                with redirect_stdout(io.StringIO()):
                    measured, checks, counts = V.measure_all([{ "session": session }], {session: {"slots": [slot]}},
                        {slot["slot_id"]: feature}, {slot["slot_id"]: condition},
                        SimpleNamespace(MeasurementBank=bank_factory, comparison_view=A.M.comparison_view),
                        SimpleNamespace(replay=replay))
                self.assertEqual(len(measured), 2)
                self.assertEqual(checks, {"独立方向数": 2, "全日単独比較": 2, "先着新規一致": 1})
                self.assertEqual(counts, {"確定約定": 1, "確定無取引": 1})
                saved = V.P.read_rows(V.WORK / "条件独立測定.jsonl.gz")
                self.assertEqual(len(saved), 2)
                self.assertEqual(saved[0], measured[slot["slot_id"], 1])
        finally:
            V.C, V.WORK = original_c, original_work


def self_test() -> dict:
    """二群の接続人工を実行し、実相場と本物学習を使わず結果を返す。

    引数: なし。
    返り値: dictは成功・テスト件数・失敗詳細。
    """
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ConnectionTests))
    return {"成功": result.wasSuccessful(), "テスト件数": result.testsRun,
        "不一致": stream.getvalue() if not result.wasSuccessful() else "", "実入力読取": False, "本物fit": False}


if __name__ == "__main__":
    result = self_test()
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["成功"] else 1)
