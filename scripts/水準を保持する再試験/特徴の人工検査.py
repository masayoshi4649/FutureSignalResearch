"""市場・教師なしで、保持水準の再試験と期限/欠測/反復観測を検査する。"""

from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("保持再試験の人工対象", HERE / "特徴.py")
N = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(N)
OLD_TEST = HERE.parent / "局所帯分岐/特徴の人工検査.py"
SPEC = importlib.util.spec_from_file_location("保持再試験の固定53人工材料", OLD_TEST)
OLD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OLD)


def candle(close: float, high: float | None = None, low: float | None = None) -> dict:
    """明示した人工終値と高安だけを作る。

    引数: close(float)は終値、high/low(float|None)は高安又は終値±1。
    返り値: dictはOHLC。相場値を使わない。
    """
    return {"open": close, "close": close, "high": close + 1 if high is None else high,
        "low": close - 1 if low is None else low}


def slot_at(frames: list[dict], j: int, delay: float = 0) -> dict:
    """人工正本の任意時点へ、旧準備契約のslotを合わせる。

    引数: frames(list[dict])は人工正本、j(int)は現番号、delay(float)は判断遅延秒。
    返り値: dictは新しい人工slot。前のextract状態には依存しない。
    """
    slot, _ = OLD.fixture(j=j)
    by_index = {row["index"]: row for row in frames}
    slot["time"] += delay
    slot["line"] = 100000
    slot["current"], slot["previous"] = deepcopy(by_index[j]), deepcopy(by_index[j - 1])
    slot["OR"]["sources"] = deepcopy([by_index[index] for index in range(10)])
    slot["diagnostic"]["old_R"]["current"] = deepcopy(slot["current"])
    return slot


def fixture(changes: dict[int, dict] | None = None, j: int = 29) -> tuple[dict, list[dict]]:
    """参照高安90..110の人工銀行へ、指定した経路を置く。

    引数: changes(dict[int,dict]|None)は番号別人工OHLC、j(int)は最後の番号。
    返り値: tuple[dict,list[dict]]はslotとSOURCE。数値bankや実運用は再生しない。
    """
    _, frames = OLD.fixture(j=j)
    for index, value in (changes or {}).items():
        frames[index].update(value)
    return slot_at(frames, j), frames


def t_changes(last: int = 29) -> dict:
    """b10/r16/k20と、その後の保持を作る。

    引数: last(int)は人工末尾。
    返り値: dictは番号別OHLC。b/r/kは五本窓より離れている。
    """
    result = {index: candle(115) for index in range(10, last + 1)}
    result[16] = candle(115, 118, 110)
    for index in range(20, last + 1):
        result[index] = candle(120)
    return result


def r_changes(last: int = 29) -> dict:
    """b10/f14/r19/k23と、その後の保持を作る。

    引数: last(int)は人工末尾。
    返り値: dictは上突破の失敗から反転売りになる人工経路。
    """
    result = {index: candle(115) for index in range(10, last + 1)}
    result.update({index: candle(105) for index in range(14, last + 1)})
    result[19] = candle(104, 110, 102)
    for index in range(23, last + 1):
        result[index] = candle(101 if index == 23 else 100)
    return result


class HoldingTests(unittest.TestCase):
    """独立した明示経路で、保持水準と公開時計の仕様を確認する。"""

    def test_Tは五本外の同水準を保持(self) -> None:
        """b/r/kが離れても登録10本とKを固定し、旧移動帯とは区別する。

        引数: self(HoldingTests)は検査先。
        返り値: None。
        """
        slot, frames = fixture(t_changes())
        result = N.extract(slot, frames)
        path = result["paths"]["1"]["T"]
        self.assertTrue(result["ready"], result["reason"])
        self.assertEqual([path[name]["index"] for name in ("b", "r", "k")], [10, 16, 20])
        self.assertEqual((path["level"], path["line"], path["stage"]), (110, 118, 3))
        self.assertEqual(path["reference_indices"], list(range(10)))
        self.assertNotEqual(path["level"], result["base"]["history"]["band"]["high"])
        self.assertEqual(path["expiry"], frames[10]["confirm"] + 3600)
        self.assertEqual(result["vectors"]["1"][18:24], [3, 1, 1, 1.8, 0, 0])
        self.assertEqual(len(path["trace"]), 3)

    def test_Rは四段を保持し同足再使用なし(self) -> None:
        """fとrを別足にし、固定r反対端を後続終値で突破する。

        引数: self(HoldingTests)は検査先。
        返り値: None。
        """
        slot, frames = fixture(r_changes())
        frames[14].update(high=116)
        path = N.extract(slot, frames)["paths"]["-1"]["R"]
        self.assertEqual([path[name]["index"] for name in ("b", "f", "r", "k")], [10, 14, 19, 23])
        self.assertEqual((path["side"], path["break_direction"], path["stage"], path["line"]), (-1, 1, 4, 102))
        self.assertEqual((path["progress"], path["pullback"]), (0.04, 0))

    def test_最初r固定と境界に追加bufferなし(self) -> None:
        """有利な遅いrへ替えず、k端等号は待ち、隣接floatは突破にする。

        引数: self(HoldingTests)は検査先。
        返り値: None。
        """
        changes = {index: candle(115) for index in range(10, 25)}
        changes.update({11: candle(115, 118, 110), 12: candle(115, 117, 110),
            13: candle(118), **{index: candle(117) for index in range(14, 25)}})
        path = N.extract(*fixture(changes, 24))["paths"]["1"]["T"]
        self.assertEqual((path["r"]["index"], path["k"]), (11, None))
        changes[13] = candle(math.nextafter(118.0, math.inf))
        path = N.extract(*fixture(changes, 24))["paths"]["1"]["T"]
        self.assertEqual(path["k"]["index"], 13)

    def test_bは当足除外の同じ新K(self) -> None:
        """前Cを同じKで比較し、b足の新高値やヒゲをKへ含めない。

        引数: self(HoldingTests)は検査先。
        返り値: None。
        """
        changes = {10: candle(115, 160, 110)}
        changes.update({index: candle(116) for index in range(11, 25)})
        path = N.extract(*fixture(changes, 24))["paths"]["1"]["T"]
        self.assertEqual((path["b"]["index"], path["level"], path["r"]), (10, 110, None))
        changes[10] = candle(math.nextafter(115.0, -math.inf))
        changes[11] = candle(121)
        path = N.extract(*fixture(changes, 24))["paths"]["1"]["T"]
        self.assertEqual((path["b"]["index"], path["level"]), (11, changes[10]["high"]))

    def test_有効中の新crossで置換しない(self) -> None:
        """新高値が続いても、元のb/固定K/期限を保持する。

        引数: self(HoldingTests)は検査先。
        返り値: None。
        """
        changes = {index: candle(115 + 10 * (index - 10)) for index in range(10, 25)}
        path = N.extract(*fixture(changes, 24))["paths"]["1"]["T"]
        self.assertEqual((path["b"]["index"], path["level"], path["stage"]), (10, 110, 1))
        self.assertEqual(len(path["trace"]), 1)

    def test_取消後だけ新bへ置換しTとRは独立(self) -> None:
        """取消足を再登録せず、T/Rの別々の新KとIDを保存する。

        引数: self(HoldingTests)は検査先。
        返り値: None。
        """
        changes = {10: candle(115), 11: candle(105), 12: candle(125), 13: candle(140), 14: candle(105)}
        result = N.extract(*fixture(changes, 14))
        t, r = result["paths"]["1"]["T"], result["paths"]["-1"]["R"]
        self.assertEqual((t["b"]["index"], t["level"], t["cancel"]["index"]), (12, 116, 14))
        self.assertEqual((r["b"]["index"], r["level"], r["f"]["index"]), (13, 126, 14))
        self.assertNotEqual(t["episode_id"], r["episode_id"])
        self.assertEqual((t["stage"], t["episode_valid"], r["stage"], r["episode_valid"]), (1, False, 2, True))

    def test_同episodeを複数定時で識別(self) -> None:
        """定時ごとの新窓に替えず、同じbを同じIDで反復観測する。

        引数: self(HoldingTests)は検査先。
        返り値: None。
        """
        _, frames = fixture(t_changes())
        a = N.extract(slot_at(frames, 24), frames)["paths"]["1"]["T"]
        b = N.extract(slot_at(frames, 29), frames)["paths"]["1"]["T"]
        self.assertEqual((a["episode_id"], a["expiry"], a["reference_indices"]),
            (b["episode_id"], b["expiry"], b["reference_indices"]))
        self.assertEqual(b["age"] - a["age"], 1)

    def test_期限等号はclearしその足で再登録なし(self) -> None:
        """b公開+3600等号を含め失効し、最初の越え足は新bに使わない。

        引数: self(HoldingTests)は検査先。
        返り値: None。
        """
        changes = t_changes(31)
        changes.update({30: candle(160), 31: candle(170)})
        _, frames = fixture(changes, 31)
        a = N.extract(slot_at(frames, 30), frames)["paths"]["1"]["T"]
        self.assertEqual((a["episode_id"], a["stage"], a["expiry"]), (None, 0, None))
        self.assertEqual((a["age"], a["progress"], a["pullback"]), (-1, 0, 0))
        self.assertEqual(a["last_expired"]["observed_at"]["index"], 30)
        self.assertEqual(a["last_expired"]["expiry"], frames[30]["confirm"])
        b = N.extract(slot_at(frames, 31), frames)["paths"]["1"]["T"]
        self.assertEqual(b["b"]["index"], 31)
        self.assertEqual(b["last_expired"], a["last_expired"])

    def test_判断だけの期限と次回再構成の一貫性(self) -> None:
        """公開足のない期限等号も失効し、後の初越え足を同じく登録禁止にする。

        引数: self(HoldingTests)は検査先。
        返り値: None。
        """
        changes = t_changes(32)
        changes.update({30: candle(160), 31: candle(170), 32: candle(180)})
        _, frames = fixture(changes, 32)
        frames[10]["confirm"] += 5
        before = N.extract(slot_at(frames, 30, 4), frames)["paths"]["1"]["T"]
        at = N.extract(slot_at(frames, 30, 5), frames)["paths"]["1"]["T"]
        self.assertTrue(before["episode_valid"])
        self.assertIsNone(at["episode_id"])
        self.assertEqual(at["last_expired"]["observed_at"]["kind"], "判断時刻")
        next_ = N.extract(slot_at(frames, 31), frames)["paths"]["1"]["T"]
        self.assertIsNone(next_["episode_id"])
        self.assertEqual(next_["last_expired"]["observed_at"]["index"], 31)
        after = N.extract(slot_at(frames, 32), frames)["paths"]["1"]["T"]
        self.assertEqual(after["b"]["index"], 32)
        self.assertEqual(at, N.extract(slot_at(frames, 30, 5), frames)["paths"]["1"]["T"])

    def test_取消後k統計と帯取消優先(self) -> None:
        """確認否定後も旧終値の最大進行を記述し、帯取消があれば先に残す。

        引数: self(HoldingTests)は検査先。
        返り値: None。
        """
        changes = {10: candle(115), 11: candle(115, 118, 110), 12: candle(120), 13: candle(125), 14: candle(118)}
        changes.update({index: candle(122) for index in range(15, 25)})
        path = N.extract(*fixture(changes, 24))["paths"]["1"]["T"]
        self.assertEqual((path["stage"], path["episode_valid"], path["k_valid"]), (3, False, False))
        self.assertEqual(path["cancel"]["reasons"], ["確認kの突破線否定"])
        self.assertEqual((path["progress"], path["max_close_progress"], path["pullback"]), (0.08, 0.2, 0.12))
        changes[14] = candle(105)
        path = N.extract(*fixture(changes, 24))["paths"]["1"]["T"]
        self.assertEqual(path["cancel"]["reasons"], ["T帯内失敗", "確認kの突破線否定"])

    def test_欠枠NP不正価格から再準備十本(self) -> None:
        """当時既知の不良は過去episodeを消し、十本目は種で十一足目から登録する。

        引数: self(HoldingTests)は検査先。
        返り値: None。
        """
        changes = {10: candle(115), **{index: candle(100) for index in range(17, 26)},
            26: candle(115), 27: candle(125)}
        for bad in ({"publish": False}, {"missing": 1}, {"close": None}, {"close": math.nan}):
            slot, frames = fixture(changes, 33)
            frames[16].update(bad)
            result = N.extract(slot, frames)
            path = result["paths"]["1"]["T"]
            self.assertTrue(result["ready"], result["reason"])
            self.assertEqual((path["b"]["index"], path["reference_indices"]), (27, list(range(17, 27))))
            self.assertEqual(result["history"]["reset_count"], 1)
            json.dumps(result, allow_nan=False)

    def test_番号gapも現正常足から再準備(self) -> None:
        """未収録の一足をまたいで古い水準を接ぎ替えず、次の正常足を種にする。

        引数: self(HoldingTests)は検査先。
        返り値: None。
        """
        changes = {10: candle(115), 26: candle(115), 27: candle(125)}
        slot, frames = fixture(changes, 33)
        del frames[16]
        result = N.extract(slot, frames)
        path = result["paths"]["1"]["T"]
        self.assertEqual(path["b"]["index"], 27)
        self.assertEqual(result["history"]["last_reset"]["reason"], "番号又は終了時刻のgap")

    def test_resetは同時期限より優先し失効記憶を作らない(self) -> None:
        """不良足と期限到達が重なれば品質resetとし、既存失効記憶だけは維持する。

        引数: self(HoldingTests)は検査先。
        返り値: None。
        """
        changes = t_changes(48)
        changes.update({30: candle(160), 31: candle(170)})
        slot, frames = fixture(changes, 48)
        frames[30]["missing"] = 1
        path = N.extract(slot, frames)["paths"]["1"]["T"]
        self.assertIsNone(path["episode_id"])
        self.assertIsNone(path["last_expired"])
        frames[30]["missing"] = 0
        frames[32]["missing"] = 1
        path = N.extract(slot, frames)["paths"]["1"]["T"]
        self.assertIsNone(path["episode_id"])
        self.assertEqual(path["last_expired"]["b"]["index"], 10)
        self.assertEqual(path["last_expired"]["observed_at"]["index"], 30)

    def test_未来bad追加でもprefix指紋を含め不変(self) -> None:
        """未来のNP/不正価格/欠枠を先読みして現在をclearしない。

        引数: self(HoldingTests)は検査先。
        返り値: None。
        """
        slot, frames = fixture(t_changes())
        before = N.extract(slot, frames)
        for bad in ({"publish": False}, {"missing": 20}, {"close": math.nan, "high": None},
                {"confirm": None, "confirm_line": None}):
            future = deepcopy(frames[-1])
            future.update(index=30, start=5400, end=5580, confirm=5580, confirm_line=100001)
            future.update(bad)
            self.assertEqual(before, N.extract(slot, frames + [future]))
        delayed = deepcopy(frames[-1])
        delayed.update(index=30, confirm=slot["time"], confirm_line=slot["line"] + 1, publish=False)
        self.assertEqual(before, N.extract(slot, frames + [delayed]))

    def test_公開key同秒原行の可視境界(self) -> None:
        """予定後公開のkも判断keyまでなら使い、同秒後行は使わない。

        引数: self(HoldingTests)は検査先。
        返り値: None。
        """
        changes = {index: candle(115) for index in range(10, 25)}
        changes[11] = candle(115, 118, 110)
        changes[24] = candle(119)
        slot, frames = fixture(changes, 24)
        frames[24].update(confirm=slot["scheduled"] + 5)
        slot = slot_at(frames, 24, 10)
        result = N.extract(slot, frames)
        path = result["paths"]["1"]["T"]
        self.assertEqual((path["k"]["index"], path["age"]), (24, 5 / 900))
        future = deepcopy(frames[-1])
        future.update(index=25, confirm=slot["time"], confirm_line=slot["line"] + 1, publish=False)
        self.assertEqual(result, N.extract(slot, frames + [future]))

    def test_入力重複と公開順不正は拒否(self) -> None:
        """過去の可視曖昧性を欠測0補完へ変えず、入力例外にする。

        引数: self(HoldingTests)は検査先。
        返り値: None。
        """
        slot, frames = fixture(t_changes())
        with self.assertRaises(ValueError):
            N.extract(slot, frames + [deepcopy(frames[10])])
        changed = deepcopy(frames)
        changed[10].update(confirm=changed[9]["confirm"], confirm_line=changed[9]["confirm_line"])
        with self.assertRaises(ValueError):
            N.extract(slot, changed)

    def test_過去不準備定時でも機械は進む(self) -> None:
        """初期の旧準備不足を観測しても、後のprefix再構成でbを落とさない。

        引数: self(HoldingTests)は検査先。
        返り値: None。
        """
        _, frames = fixture(t_changes())
        early = N.extract(slot_at(frames, 10), frames)
        self.assertFalse(early["ready"])
        self.assertEqual(early["vectors"], {"1": [], "-1": []})
        self.assertIsNone(early["history"])
        later = N.extract(slot_at(frames, 24), frames)
        self.assertEqual(later["paths"]["1"]["T"]["b"]["index"], 10)
        self.assertEqual(later, N.extract(slot_at(frames, 24), frames))

    def test_上位DIと価格役割は別(self) -> None:
        """DIだけを変えても保持K/価格経路/追加12列を変えない。

        引数: self(HoldingTests)は検査先。
        返り値: None。
        """
        slot, frames = fixture(t_changes())
        original = N.extract(slot, frames)
        slot["upper"].update(plus_di=10, minus_di=30)
        changed = N.extract(slot, frames)
        self.assertEqual(changed["paths"], original["paths"])
        self.assertEqual(changed["background_direction"], -1)
        self.assertEqual(changed["vectors"]["1"][18:], original["vectors"]["1"][18:])

    def test_売買反射で三十列が交換(self) -> None:
        """価格反射でT/Rの役割と期限を維持し、両方向の全特徴を交換する。

        引数: self(HoldingTests)は検査先。
        返り値: None。
        """
        for changes in (t_changes(), r_changes(), {10: candle(115), 11: candle(105), 12: candle(125)}):
            slot, frames = fixture(changes)
            a = N.extract(slot, frames)
            b = N.extract(*OLD.reflect(slot, frames))
            for side in (1, -1):
                self.assertEqual(a["vectors"][str(side)], b["vectors"][str(-side)])
                for role in ("T", "R"):
                    pa, pb = a["paths"][str(side)][role], b["paths"][str(-side)][role]
                    for name in ("stage", "episode_valid", "k_valid", "age", "progress", "pullback", "expiry"):
                        self.assertEqual(pa[name], pb[name])

    def test_現在ATRは既知全終値へ共通尺度(self) -> None:
        """過去のk時ATRではなく、判断ATRの交換で進行と戻りを同率に変える。

        引数: self(HoldingTests)は検査先。
        返り値: None。
        """
        changes = t_changes()
        changes[28], changes[29] = candle(125), candle(119)
        slot, frames = fixture(changes)
        original = N.extract(slot, frames)
        slot["atr"] = 50
        changed = N.extract(slot, frames)
        pa, pb = original["paths"]["1"]["T"], changed["paths"]["1"]["T"]
        self.assertEqual((pa["progress"], pa["pullback"]), (2 * pb["progress"], 2 * pb["pullback"]))

    def test_準備旧十八列と入力不変と小型出典(self) -> None:
        """旧base全文とprefixを保持し、history/pathへSOURCE全文を重ねない。

        引数: self(HoldingTests)は検査先。
        返り値: None。
        """
        slot, frames = fixture(t_changes())
        before = deepcopy((slot, frames))
        result, base = N.extract(slot, frames), N.F53.extract(slot, frames)
        self.assertEqual((slot, frames), before)
        self.assertEqual(result["base"], base)
        self.assertEqual(result["control_vectors"], base["vectors"])
        self.assertEqual(N.FEATURES[:18], N.F53.FEATURES)
        self.assertEqual([m["id"] for m in N.FEATURES], [f"F{i:02d}" for i in range(1, 31)])
        for side in ("1", "-1"):
            self.assertEqual(result["vectors"][side][:18], base["vectors"][side])
            self.assertEqual(len(result["vectors"][side]), 30)
            self.assertTrue(all(math.isfinite(value) for value in result["vectors"][side]))
        path = result["paths"]["1"]["T"]
        self.assertEqual(set(path["b"]), {"index", "key"})
        self.assertEqual(set(path["trace"][0]), {"index", "key", "action", "stage", "episode_valid", "k_valid"})
        self.assertEqual(result["history"]["source_prefix_count"], len(frames))
        json.dumps(result, ensure_ascii=False, allow_nan=False)


def run() -> dict:
    """手作りSOURCEのみで検査し、固定人工材料の指紋と結果を返す。

    引数: なし。
    返り値: dictは成功/人工件数/詳細。市場入力・本物教師・fitを読まず実行しない。
    """
    capture = io.StringIO()
    result = unittest.TextTestRunner(stream=capture, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(HoldingTests))
    return {"成功": result.wasSuccessful(), "人工件数": result.testsRun, "失敗": len(result.failures), "エラー": len(result.errors),
        "市場入力読取": False, "本物特徴計算": False, "本物fit": False,
        "固定53人工factorySHA256": hashlib.sha256(OLD_TEST.read_bytes()).hexdigest(),
        "詳細": "" if result.wasSuccessful() else capture.getvalue()}


if __name__ == "__main__":
    value = run()
    print(json.dumps(value, ensure_ascii=False))
    raise SystemExit(0 if value["成功"] else 1)
