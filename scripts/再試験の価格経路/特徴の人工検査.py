"""旧人工SOURCEだけで、別足の順序・取消・既知進行と売買鏡像を検査する。"""

from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("再試験の新特徴人工", HERE / "特徴.py")
N = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(N)
OLD_TEST = HERE.parent / "局所帯分岐/特徴の人工検査.py"
SPEC = importlib.util.spec_from_file_location("再試験の固定53人工材料", OLD_TEST)
OLD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OLD)


def candle(close: float, high: float | None = None, low: float | None = None) -> dict:
    """反応足の終値と明示高安を持つ、小型人工価格を作る。

    引数: close(float)は終値、high/low(float|None)は高安又は既定の±1。
    返り値: dictはopen/high/low/closeだけ。実市場を読まない。
    """
    return {"open": close, "close": close, "high": close + 1 if high is None else high,
        "low": close - 1 if low is None else low}


def fixture(values: list[dict]) -> tuple[dict, list[dict]]:
    """旧53の帯90..110/ATR25の人工5足へ、明示した高安を接続する。

    引数: values(list[dict])は反応5足の人工OHLC。
    返り値: tuple[dict,list[dict]]は旧契約のslotとSOURCE。数値bankを再生しない。
    """
    if len(values) != 5:
        raise ValueError("人工反応は5足")
    slot, frames = OLD.fixture([row["close"] for row in values])
    for source, value in zip(frames[-5:], values):
        source.update(value)
    refresh(slot, frames)
    return slot, frames


def refresh(slot: dict, frames: list[dict]) -> None:
    """人工正本の現前足と、同じ出典を持つ旧slotを同期する。

    引数: slot(dict)/frames(list[dict])は人工材料。
    返り値: None。人工の出典だけを更新する。
    """
    slot["current"], slot["previous"] = deepcopy(frames[-1]), deepcopy(frames[-2])
    slot["diagnostic"]["old_R"]["current"] = deepcopy(slot["current"])


def t_path() -> list[dict]:
    """b20/r21/k22と、その後の進行・戻りを持つ人工例を返す。

    引数: なし。
    返り値: list[dict]は旧上端110を使う反応5足。
    """
    return [candle(115), candle(115, 118, 110), candle(120), candle(125), candle(119)]


def r_path() -> list[dict]:
    """b20/f21/r22/k23の反転売りと、その後の進行を作る。

    引数: なし。
    返り値: list[dict]は旧上端110を使う反応5足。
    """
    return [candle(115), candle(105, 116, 104), candle(104, 110, 102), candle(101), candle(100)]


class SequenceTests(unittest.TestCase):
    """未形成・途中・形成後取消を落とさず、時点と線の境界を確認する。"""

    def test_Tの三別足と進行と押戻(self) -> None:
        """Tはb/r/kを別足へ置き、現在ATRで既知終値だけを測る。

        引数: self(SequenceTests)は検査先。
        返り値: None。
        """
        slot, frames = fixture(t_path())
        result = N.extract(slot, frames)
        self.assertTrue(result["ready"], result["reason"])
        path = result["paths"]["1"]["T"]
        self.assertEqual([path[k]["index"] for k in ("b", "r", "k")], [20, 21, 22])
        self.assertIsNone(path["f"])
        self.assertEqual((path["stage"], path["episode_valid"], path["k_valid"], path["line"]), (3, True, True, 118))
        self.assertEqual((path["age"], path["progress"], path["max_close_progress"], path["pullback"]), (0.4, -0.04, 0.2, 0.24))
        self.assertEqual(result["vectors"]["1"][18:24], [3, 1, 1, 0.4, -0.04, 0.24])
        self.assertEqual([r["action"] for r in path["trace"][:3]], ["b登録", "T再試験r", "T再開k"])

    def test_Rの四別足と元方向と実方向(self) -> None:
        """上抜け失敗からの売りをRへ置き、f足をrとして重複消費しない。

        引数: self(SequenceTests)は検査先。
        返り値: None。
        """
        slot, frames = fixture(r_path())
        result = N.extract(slot, frames)
        path = result["paths"]["-1"]["R"]
        self.assertEqual([path[k]["index"] for k in ("b", "f", "r", "k")], [20, 21, 22, 23])
        self.assertEqual((path["break_direction"], path["side"], path["stage"], path["line"]), (1, -1, 4, 102))
        self.assertEqual(result["vectors"]["-1"][24:], [4, 1, 1, 0.2, 0.04, 0.0])
        self.assertEqual([r["stage"] for r in path["trace"]], [1, 2, 3, 4, 4])

    def test_準備同一と未完成と真の零(self) -> None:
        """episode不成立やk未形成をready不足へ変えず、段階とmaskで零を区別する。

        引数: self(SequenceTests)は検査先。
        返り値: None。
        """
        cases = [([candle(100)] * 5, [0, 0, 0, -1, 0, 0]),
            ([candle(c) for c in (115, 116, 117, 118, 119)], [1, 1, 0, -1, 0, 0]),
            ([candle(115), candle(115, 118, 110), candle(118), candle(117), candle(118)], [2, 1, 0, -1, 0, 0])]
        for values, expected in cases:
            slot, frames = fixture(values)
            result, base = N.extract(slot, frames), N.F53.extract(slot, frames)
            self.assertTrue(result["ready"])
            self.assertEqual(result["control_vectors"], base["vectors"])
            self.assertEqual(result["vectors"]["1"][18:24], expected)
        values = t_path()
        values[3], values[4] = candle(120), candle(120)
        path = N.extract(*fixture(values))["paths"]["1"]["T"]
        self.assertTrue(path["k_valid"])
        self.assertEqual((path["progress"], path["pullback"]), (0.0, 0.0))

    def test_b足の再試験再使用なし(self) -> None:
        """b自体のヒゲが端へ届いても、その足をrへ使わない。

        引数: self(SequenceTests)は検査先。
        返り値: None。
        """
        values = [candle(115, 118, 110)] + [candle(c) for c in (116, 117, 118, 119)]
        path = N.extract(*fixture(values))["paths"]["1"]["T"]
        self.assertEqual(path["stage"], 1)
        self.assertIsNone(path["r"])

    def test_最初r固定で有利な後続rへ置換しない(self) -> None:
        """Tは遅い低い端への置換を拒否し、Rも最初のr端を維持する。

        引数: self(SequenceTests)は検査先。
        返り値: None。
        """
        values = [candle(115), candle(115, 118, 110), candle(115, 117, 110), candle(118), candle(117)]
        path = N.extract(*fixture(values))["paths"]["1"]["T"]
        self.assertEqual((path["stage"], path["r"]["index"], path["k"]), (2, 21, None))
        values = r_path()
        values[3], values[4] = candle(104, 110, 100), candle(101)
        path = N.extract(*fixture(values))["paths"]["-1"]["R"]
        self.assertEqual((path["r"]["index"], path["k"]["index"], path["line"]), (22, 24, 102))

    def test_T途中取消と同足再登録禁止(self) -> None:
        """帯失敗でstageを保持し、その後の外crossでも同じ窓を再開しない。

        引数: self(SequenceTests)は検査先。
        返り値: None。
        """
        values = [candle(115), candle(115, 118, 110), candle(105), candle(115, 120, 110), candle(125)]
        result = N.extract(*fixture(values))
        path = result["paths"]["1"]["T"]
        self.assertEqual((path["stage"], path["episode_valid"], path["k_valid"]), (2, False, False))
        self.assertEqual(path["cancel"], {"index": 22, "key": path["trace"][2]["key"], "reasons": ["T帯内失敗"]})
        self.assertEqual(path["b"]["index"], 20)
        self.assertIsNone(path["k"])
        self.assertEqual(result["vectors"]["1"][18:24], [2, 0, 0, -1, 0, 0])
        self.assertGreater(result["base"]["history"]["upper"]["out_count"], 1)

    def test_Rのf前外残留とf後再取得取消(self) -> None:
        """f前の外側継続は待ち、f後のbuffer等号再取得では取消する。

        引数: self(SequenceTests)は検査先。
        返り値: None。
        """
        values = [candle(115), candle(116), candle(105), candle(104, 110, 102), candle(101)]
        path = N.extract(*fixture(values))["paths"]["-1"]["R"]
        self.assertEqual((path["f"]["index"], path["k"]["index"], path["episode_valid"]), (22, 24, True))
        values = r_path()
        values[3], values[4] = candle(115), candle(100)
        path = N.extract(*fixture(values))["paths"]["-1"]["R"]
        self.assertEqual((path["stage"], path["episode_valid"], path["k"]), (3, False, None))
        self.assertEqual(path["cancel"]["reasons"], ["R元外側再取得"])

    def test_k否定等号と取消後の履歴更新(self) -> None:
        """確認線の等号で取消し、以後の進行を記述しても再点火しない。

        引数: self(SequenceTests)は検査先。
        返り値: None。
        """
        values = t_path()
        values[3], values[4] = candle(118), candle(130)
        path = N.extract(*fixture(values))["paths"]["1"]["T"]
        self.assertEqual((path["stage"], path["episode_valid"], path["k_valid"]), (3, False, False))
        self.assertEqual(path["cancel"]["reasons"], ["確認kの突破線否定"])
        self.assertEqual((path["progress"], path["max_close_progress"], path["pullback"]), (0.4, 0.4, 0.0))
        self.assertEqual(path["trace"][-1]["action"], "取消後履歴")
        values = r_path()
        values[4] = candle(102)
        path = N.extract(*fixture(values))["paths"]["-1"]["R"]
        self.assertFalse(path["k_valid"])
        self.assertEqual(path["cancel"]["reasons"], ["確認kの突破線否定"])
        self.assertEqual((path["progress"], path["pullback"]), (-0.04, 0.04))

    def test_帯取消優先と複数理由(self) -> None:
        """帯失敗と確認否定が同じ終値で成立したら帯を先に記録する。

        引数: self(SequenceTests)は検査先。
        返り値: None。
        """
        values = t_path()
        values[3] = candle(105)
        path = N.extract(*fixture(values))["paths"]["1"]["T"]
        self.assertEqual(path["cancel"]["reasons"], ["T帯内失敗", "確認kの突破線否定"])
        self.assertEqual(path["stage"], 3)
        values = r_path()
        values[4] = candle(115)
        path = N.extract(*fixture(values))["paths"]["-1"]["R"]
        self.assertEqual(path["cancel"]["reasons"], ["R元外側再取得", "確認kの突破線否定"])

    def test_buffer接触kの等号と隣接浮動値(self) -> None:
        """±5と接触の等号、kのstrict境界へepsilonを足さない。

        引数: self(SequenceTests)は検査先。
        返り値: None。
        """
        values = [candle(math.nextafter(115.0, -math.inf)), candle(115), candle(116), candle(117), candle(118)]
        path = N.extract(*fixture(values))["paths"]["1"]["T"]
        self.assertEqual(path["b"]["index"], 21)
        values = [candle(115), candle(115, 118, 110), candle(118), candle(117), candle(118)]
        self.assertIsNone(N.extract(*fixture(values))["paths"]["1"]["T"]["k"])
        values[2] = candle(math.nextafter(118.0, math.inf))
        self.assertEqual(N.extract(*fixture(values))["paths"]["1"]["T"]["k"]["index"], 22)
        values = [candle(115), candle(115, 118, math.nextafter(110.0, math.inf)), candle(116), candle(117), candle(118)]
        self.assertIsNone(N.extract(*fixture(values))["paths"]["1"]["T"]["r"])
        values = r_path()
        values[2]["high"] = math.nextafter(110.0, -math.inf)
        self.assertIsNone(N.extract(*fixture(values))["paths"]["-1"]["R"]["r"])

    def test_ageは予定でなく判断時計と公開秒(self) -> None:
        """予定後に公開された最終足kでも、判断で既知ならageを非負にする。

        引数: self(SequenceTests)は検査先。
        返り値: None。
        """
        values = [candle(115), candle(115, 118, 110), candle(117), candle(118), candle(119)]
        slot, frames = fixture(values)
        frames[-1]["confirm"] = slot["scheduled"] + 5
        slot["time"] = slot["scheduled"] + 10
        refresh(slot, frames)
        result = N.extract(slot, frames)
        self.assertTrue(result["ready"], result["reason"])
        path = result["paths"]["1"]["T"]
        self.assertEqual(path["k"]["index"], 24)
        self.assertEqual(path["age"], 5 / 900)
        self.assertEqual((path["progress"], path["pullback"]), (0, 0))

    def test_反射で全三十列を交換(self) -> None:
        """上下反射と実side交換で、T/R意味・取消・全特徴を保存する。

        引数: self(SequenceTests)は検査先。
        返り値: None。
        """
        cancelled = t_path()
        cancelled[3], cancelled[4] = candle(118), candle(130)
        for values in (t_path(), r_path(), cancelled, [candle(100)] * 5):
            slot, frames = fixture(values)
            original = N.extract(slot, frames)
            mirror = N.extract(*OLD.reflect(slot, frames))
            self.assertTrue(original["ready"] and mirror["ready"])
            for side in (1, -1):
                self.assertEqual(original["vectors"][str(side)], mirror["vectors"][str(-side)])
                for role in ("T", "R"):
                    a, b = original["paths"][str(side)][role], mirror["paths"][str(-side)][role]
                    for key in ("stage", "episode_valid", "k_valid", "age", "progress", "max_close_progress", "pullback", "cancel"):
                        self.assertEqual(a[key], b[key])

    def test_未来足不使用と呼出し間初期化(self) -> None:
        """窓外未来を無視し、別定時の状態を次のextractへ持ち越さない。

        引数: self(SequenceTests)は検査先。
        返り値: None。
        """
        slot, frames = fixture(t_path())
        original = N.extract(slot, frames)
        extended = deepcopy(frames)
        future = deepcopy(frames[-1])
        future.update(index=25, close=1, high=1000, low=1, confirm=100000, confirm_line=100000)
        extended.append(future)
        self.assertEqual(original, N.extract(slot, extended))
        empty = N.extract(*fixture([candle(100)] * 5))
        self.assertEqual(empty["vectors"]["1"][18:], [0, 0, 0, -1, 0, 0] * 2)
        self.assertEqual(original, N.extract(slot, frames))

    def test_価格T_Rと上位DI役割を混同しない(self) -> None:
        """DI背景を交換しても、同じ価格とATRの経路分類は変えない。

        引数: self(SequenceTests)は検査先。
        返り値: None。
        """
        slot, frames = fixture(t_path())
        original = N.extract(slot, frames)
        slot["upper"].update(plus_di=10, minus_di=30)
        changed = N.extract(slot, frames)
        self.assertEqual(changed["background_direction"], -1)
        self.assertEqual(changed["paths"], original["paths"])
        for side in ("1", "-1"):
            self.assertEqual(changed["vectors"][side][18:], original["vectors"][side][18:])

    def test_旧prefixと欠測と入力保全と出典参照(self) -> None:
        """旧準備・旧18値を完全保持し、全SOURCE転記をpathへ重ねない。

        引数: self(SequenceTests)は検査先。
        返り値: None。
        """
        slot, frames = fixture(t_path())
        before = deepcopy((slot, frames))
        old = N.F53.extract(slot, frames)
        result = N.extract(slot, frames)
        self.assertEqual((slot, frames), before)
        self.assertEqual(result["base"], old)
        self.assertEqual(result["control_vectors"], old["vectors"])
        self.assertEqual(N.FEATURES[:18], N.F53.FEATURES)
        self.assertEqual([m["id"] for m in N.FEATURES], [f"F{i:02d}" for i in range(1, 31)])
        for side in ("1", "-1"):
            self.assertEqual(result["vectors"][side][:18], old["vectors"][side])
            self.assertEqual(len(result["vectors"][side]), 30)
            self.assertTrue(all(math.isfinite(v) for v in result["vectors"][side]))
        self.assertEqual(set(result["paths"]["1"]["T"]["b"]), {"index", "key"})
        json.dumps(result, ensure_ascii=False, allow_nan=False)
        short_slot, short_frames = OLD.fixture(j=9)
        unknown = N.extract(short_slot, short_frames)
        self.assertFalse(unknown["ready"])
        self.assertEqual(unknown["vectors"], {"1": [], "-1": []})
        self.assertEqual(unknown["control_vectors"], {"1": [], "-1": []})


def run() -> dict:
    """このファイルの手作り経路だけを実行し、検査範囲と出典を返す。

    引数: なし。
    返り値: dictは人工成功/件数。本物の特徴・教師・モデル・運用は計算しない。
    """
    capture = io.StringIO()
    result = unittest.TextTestRunner(stream=capture, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SequenceTests))
    return {"成功": result.wasSuccessful(), "人工件数": result.testsRun, "失敗": len(result.failures), "エラー": len(result.errors),
        "市場入力読取": False, "本物特徴計算": False, "本物fit": False,
        "固定53人工factorySHA256": hashlib.sha256(OLD_TEST.read_bytes()).hexdigest(),
        "詳細": "" if result.wasSuccessful() else capture.getvalue()}


if __name__ == "__main__":
    value = run()
    print(json.dumps(value, ensure_ascii=False))
    raise SystemExit(0 if value["成功"] else 1)
