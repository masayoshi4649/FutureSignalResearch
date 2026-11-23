"""固定人工SOURCEだけで、b起点の八値・旧30射影・時点と対称性を検査する。"""

from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("深さ速度の人工対象", HERE / "特徴.py")
N = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(N)
OLD_TEST = HERE.parent / "水準を保持する再試験/特徴の人工検査.py"
SPEC = importlib.util.spec_from_file_location("深さ速度の固定58人工材料", OLD_TEST)
OLD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OLD)
candle, fixture, slot_at = OLD.candle, OLD.fixture, OLD.slot_at


def t_changes(last: int = 24) -> dict:
    """b10から途中の深さ、確認後の進行、取消後の戻りを持つ人工Tを作る。

    引数: last(int)は人工末尾。
    返り値: dictは番号別OHLC。実市場や数値bankを使わない。
    """
    result = {index: candle(122) for index in range(10, last + 1)}
    result.update({10: candle(115), 11: candle(112), 12: candle(108), 13: candle(114),
        14: candle(117, 118, 110), 15: candle(120), 16: candle(125), 17: candle(118)})
    return result


def r_changes(last: int = 24) -> dict:
    """b10の外側進行後、f/r/kと取消後戻りを持つ反転売りを作る。

    引数: last(int)は人工末尾。
    返り値: dictは上突破を元にした人工R。
    """
    result = {index: candle(101) for index in range(10, last + 1)}
    result.update({10: candle(115), 11: candle(120), 12: candle(108), 13: candle(105),
        14: candle(104, 110, 102), 15: candle(100), 16: candle(98), 17: candle(103)})
    return result


class GeometryTests(unittest.TestCase):
    """黄金値と公開順の境界により、実装の写しではない期待値を確認する。"""

    def test_Tの四値と極値出典(self) -> None:
        """b115から最小108/最大125/現在122を、ATR25と14足で計算する。

        引数: self(GeometryTests)は検査先。
        返り値: None。
        """
        result = N.extract(*fixture(t_changes(), 24))
        path, g = result["paths"]["1"]["T"], result["geometry"]["1"]["T"]
        self.assertTrue(result["ready"], result["reason"])
        self.assertEqual((g["b"]["index"], g["current"]["index"], g["n"], g["observations"]), (10, 24, 14, 15))
        self.assertEqual((g["u_current"], g["u_min"], g["u_max"]), (7, -7, 10))
        self.assertEqual((g["u_min_source"]["index"], g["u_max_source"]["index"]), (12, 16))
        self.assertEqual(g["values"], [0.28, 0.12, 0.02, 0.48])
        self.assertEqual(result["vectors"]["1"][30:34], g["values"])
        self.assertEqual((path["stage"], path["episode_valid"], path["cancel"]["index"]), (3, False, 17))

    def test_Rの四値と実方向(self) -> None:
        """元上突破の反転売りでは、同じ価格差へ実side−1を掛ける。

        引数: self(GeometryTests)は検査先。
        返り値: None。
        """
        result = N.extract(*fixture(r_changes(), 24))
        g = result["geometry"]["-1"]["R"]
        self.assertEqual((g["u_current"], g["u_min"], g["u_max"]), (14, -5, 17))
        self.assertEqual(g["values"], [0.2, 0.12, 0.04, 0.36])
        self.assertEqual(result["vectors"]["-1"][34:38], g["values"])
        self.assertEqual(result["paths"]["-1"]["R"]["cancel"]["index"], 17)

    def test_n零は既知零で終値位置は非零(self) -> None:
        """bと現足が同じなら深さ/戻り/速度は0、Kとの距離は残す。

        引数: self(GeometryTests)は検査先。
        返り値: None。
        """
        result = N.extract(*fixture({24: candle(115)}, 24))
        g = result["geometry"]["1"]["T"]
        self.assertEqual((g["n"], g["observations"], g["u_min"], g["u_max"]), (0, 1, 0, 0))
        self.assertEqual(g["values"], [0, 0, 0, 0.2])
        self.assertEqual(g["u_min_source"], g["b"])
        self.assertEqual(result["geometry"]["-1"]["R"]["values"], [0, 0, 0, -0.2])

    def test_未IDと旧準備不足を区別(self) -> None:
        """readyで未登録は四値0とnNone、旧準備不足はgeometryNoneと空vectorsにする。

        引数: self(GeometryTests)は検査先。
        返り値: None。
        """
        result = N.extract(*fixture({}, 24))
        for side in ("1", "-1"):
            for role in ("T", "R"):
                g = result["geometry"][side][role]
                self.assertEqual((g["episode_id"], g["b"], g["n"], g["observations"]), (None, None, None, 0))
                self.assertEqual((g["u_current"], g["u_min"], g["u_max"]), (None, None, None))
                self.assertEqual(g["values"], [0, 0, 0, 0])
                self.assertEqual(g["current"]["index"], 24)
        _, frames = fixture({}, 24)
        unknown = N.extract(slot_at(frames, 10), frames)
        self.assertFalse(unknown["ready"])
        self.assertEqual(unknown["geometry"], {"1": {"T": None, "R": None}, "-1": {"T": None, "R": None}})
        self.assertEqual(unknown["control_vectors30"], {"1": [], "-1": []})
        self.assertEqual(unknown["vectors"], {"1": [], "-1": []})

    def test_k未形成でもbからの統計がある(self) -> None:
        """未完成を準備不足にせず、F07の一足0とも異なる平均純進行を保存する。

        引数: self(GeometryTests)は検査先。
        返り値: None。
        """
        changes = {index: candle(110) for index in range(10, 25)}
        changes.update({10: candle(115), 11: candle(108)})
        result = N.extract(*fixture(changes, 24))
        path, g = result["paths"]["1"]["T"], result["geometry"]["1"]["T"]
        self.assertEqual((path["stage"], path["k"], path["progress"]), (1, None, 0))
        self.assertEqual(g["values"], [0.28, 0.2, -1 / 70, 0])
        self.assertEqual(result["vectors"]["1"][6], 0)
        self.assertNotEqual(g["values"][2], 0)

    def test_b前の価格と足中高安を深さへ加えない(self) -> None:
        """b足の大きなヒゲを、その公開後の逆行やピークへ転記しない。

        引数: self(GeometryTests)は検査先。
        返り値: None。
        """
        slot, frames = fixture(t_changes(), 24)
        before = N.extract(slot, frames)
        frames[10].update(high=200, low=1)
        after = N.extract(slot, frames)
        self.assertEqual(before["geometry"]["1"]["T"], after["geometry"]["1"]["T"])
        self.assertEqual(after["geometry"]["1"]["T"]["u_min"], -7)

    def test_k前ピークとk後ピークは別(self) -> None:
        """k前の130を新戻りへ残し、k以後の戻り0と同一視しない。

        引数: self(GeometryTests)は検査先。
        返り値: None。
        """
        changes = {index: candle(122) for index in range(10, 25)}
        changes.update({10: candle(115), 11: candle(130), 12: candle(117, 118, 110), 13: candle(120)})
        result = N.extract(*fixture(changes, 24))
        self.assertEqual(result["paths"]["1"]["T"]["pullback"], 0)
        self.assertEqual(result["geometry"]["1"]["T"]["values"][1], 0.32)
        self.assertEqual(result["geometry"]["1"]["T"]["u_max_source"]["index"], 11)

    def test_取消後も更新し有効旗は復活しない(self) -> None:
        """同じ取消episodeのまま現在終値を更新し、0補完や再点火にしない。

        引数: self(GeometryTests)は検査先。
        返り値: None。
        """
        _, frames = fixture(t_changes(), 24)
        a = N.extract(slot_at(frames, 17), frames)
        b = N.extract(slot_at(frames, 24), frames)
        ga, gb = a["geometry"]["1"]["T"], b["geometry"]["1"]["T"]
        self.assertEqual(ga["episode_id"], gb["episode_id"])
        self.assertEqual((ga["u_current"], gb["u_current"]), (3, 7))
        self.assertFalse(b["paths"]["1"]["T"]["episode_valid"])
        self.assertFalse(b["paths"]["1"]["T"]["k_valid"])

    def test_置換で旧統計を捨てる(self) -> None:
        """後続の新bでK/起点が替わったら、古い最大逆行を引き継がない。

        引数: self(GeometryTests)は検査先。
        返り値: None。
        """
        changes = t_changes(25)
        changes[25] = candle(140)
        _, frames = fixture(changes, 25)
        old = N.extract(slot_at(frames, 24), frames)["geometry"]["1"]["T"]
        new = N.extract(slot_at(frames, 25), frames)["geometry"]["1"]["T"]
        self.assertNotEqual(old["episode_id"], new["episode_id"])
        self.assertEqual((new["b"]["index"], new["level"], new["n"]), (25, 126, 0))
        self.assertEqual(new["values"], [0, 0, 0, 0.56])

    def test_TTLclearで未ID四値に戻す(self) -> None:
        """期限越え足の価格が大きくても、旧IDの八値を残したり新登録したりしない。

        引数: self(GeometryTests)は検査先。
        返り値: None。
        """
        changes = t_changes(30)
        changes[30] = candle(160)
        result = N.extract(*fixture(changes, 30))
        g = result["geometry"]["1"]["T"]
        self.assertEqual((g["episode_id"], g["n"], g["values"]), (None, None, [0, 0, 0, 0]))
        self.assertEqual(result["paths"]["1"]["T"]["last_expired"]["b"]["index"], 10)

    def test_resetで古いb深さを接ぎ替えない(self) -> None:
        """旧58の欠測reset後、旧準備が戻っても古いbの極値を使わない。

        引数: self(GeometryTests)は検査先。
        返り値: None。
        """
        slot, frames = fixture(t_changes(33), 33)
        frames[16]["missing"] = 1
        result = N.extract(slot, frames)
        self.assertTrue(result["ready"])
        self.assertIsNone(result["geometry"]["1"]["T"]["episode_id"])
        self.assertEqual(result["vectors"]["1"][30:34], [0, 0, 0, 0])

    def test_D上限とATR尺度を混同しない(self) -> None:
        """ATR200/D125では第四値だけDで割り、ATR2/D5の下限も保持する。

        引数: self(GeometryTests)は検査先。
        返り値: None。
        """
        slot, frames = fixture(t_changes(), 24)
        slot["atr"] = 200
        result = N.extract(slot, frames)
        self.assertEqual((result["atr"], result["D"]), (200, 125))
        self.assertEqual(result["geometry"]["1"]["T"]["values"], [0.035, 0.015, 0.0025, 0.096])
        slot["atr"] = 2
        result = N.extract(slot, frames)
        self.assertEqual(result["D"], 5)
        self.assertEqual(result["geometry"]["1"]["T"]["values"], [3.5, 1.5, 0.25, 2.4])

    def test_同値極値は最初の公開出典(self) -> None:
        """同じ底/峰を再訪しても、最初の出典を後の足へ描き替えない。

        引数: self(GeometryTests)は検査先。
        返り値: None。
        """
        changes = t_changes()
        changes[13] = candle(108)
        changes[18] = candle(125)
        g = N.extract(*fixture(changes, 24))["geometry"]["1"]["T"]
        self.assertEqual((g["u_min_source"]["index"], g["u_max_source"]["index"]), (12, 16))

    def test_最小浮動差をepsilonで消さない(self) -> None:
        """b終値の一ULP下への終値逆行を、有限な正の深さとして保存する。

        引数: self(GeometryTests)は検査先。
        返り値: None。
        """
        changes = {index: candle(115) for index in range(10, 25)}
        changes[12] = candle(math.nextafter(115.0, -math.inf))
        g = N.extract(*fixture(changes, 24))["geometry"]["1"]["T"]
        self.assertGreater(g["values"][0], 0)
        self.assertEqual(g["u_min_source"]["index"], 12)
        self.assertEqual(g["u_max_source"]["index"], 10)

    def test_未来足と同秒後行はgeometryにも使わない(self) -> None:
        """未来の大底や不正足を追加しても、旧keysと八値が完全一致する。

        引数: self(GeometryTests)は検査先。
        返り値: None。
        """
        slot, frames = fixture(t_changes(), 24)
        before = N.extract(slot, frames)
        future = deepcopy(frames[-1])
        future.update(index=25, start=4500, end=4680, confirm=None, confirm_line=None, close=1, low=1, high=1000, publish=False)
        self.assertEqual(before, N.extract(slot, frames + [future]))
        future.update(end=slot["scheduled"], confirm=slot["time"], confirm_line=slot["line"] + 1)
        self.assertEqual(before, N.extract(slot, frames + [future]))

    def test_同秒公開でも速度は足数尺度(self) -> None:
        """公開秒差0でも後行別足を区別し、秒割りの不定値を作らない。

        引数: self(GeometryTests)は検査先。
        返り値: None。
        """
        slot, frames = fixture(t_changes(), 24)
        for index in range(10, 25):
            frames[index]["confirm"] = slot["scheduled"]
        slot = slot_at(frames, 24)
        result = N.extract(slot, frames)
        self.assertTrue(result["ready"], result["reason"])
        self.assertEqual(result["geometry"]["1"]["T"]["values"][2], 0.02)

    def test_売買鏡像で全三十八列を交換(self) -> None:
        """反射と実side交換で、深さ・戻り・平均進行・終値位置を保存する。

        引数: self(GeometryTests)は検査先。
        返り値: None。
        """
        for changes in (t_changes(), r_changes(), {}, {24: candle(115)}):
            slot, frames = fixture(changes, 24)
            a = N.extract(slot, frames)
            b = N.extract(*OLD.OLD.reflect(slot, frames))
            for side in (1, -1):
                self.assertEqual(a["vectors"][str(side)], b["vectors"][str(-side)])
                for role in ("T", "R"):
                    ga, gb = a["geometry"][str(side)][role], b["geometry"][str(-side)][role]
                    for name in ("n", "observations", "u_current", "u_min", "u_max", "u_min_source", "u_max_source", "values"):
                        self.assertEqual(ga[name], gb[name])

    def test_旧三十列射影と深い複写(self) -> None:
        """新旧keys/全出力/入力を厳密照合し、射影の変更が原出力へ伝わらない。

        引数: self(GeometryTests)は検査先。
        返り値: None。
        """
        for changes in (t_changes(), r_changes(), {}):
            slot, frames = fixture(changes, 24)
            before = deepcopy((slot, frames))
            old = N.F58.extract(slot, frames)
            new = N.extract(slot, frames)
            self.assertEqual((slot, frames), before)
            self.assertEqual(N.control_projection(new), old)
            self.assertEqual(set(new), set(old) | {"control_vectors30", "geometry"})
            self.assertEqual(new["control_vectors30"], old["vectors"])
            self.assertEqual(new["control_vectors"], old["control_vectors"])
            for name in set(old) - {"vectors"}:
                self.assertEqual(new[name], old[name])
            for side in ("1", "-1"):
                self.assertEqual(new["vectors"][side][:30], old["vectors"][side])
                self.assertEqual(len(new["vectors"][side]), 38)
            projection = N.control_projection(new)
            projection["paths"]["1"]["T"]["level"] = -1
            self.assertEqual(N.control_projection(new), old)
            new["vectors"]["1"][0] = -999
            self.assertEqual(new["control_vectors30"], old["vectors"])

    def test_geometryの出典矛盾は拒否(self) -> None:
        """壊れたspanを短い別期間へ差し替えず、b/key/番号不整合を例外にする。

        引数: self(GeometryTests)は検査先。
        返り値: None。
        """
        slot, frames = fixture(t_changes(), 24)
        old = N.F58.extract(slot, frames)
        rows = {row["index"]: row for row in N.F58.visible_sources(slot, frames)}
        path, current = old["paths"]["1"]["T"], old["base"]["history"]["reaction_sources"][-1]
        missing = deepcopy(rows)
        del missing[12]
        with self.assertRaises(ValueError):
            N.geometry(path, current, missing, old["atr"], old["D"])
        bad = deepcopy(path)
        bad["b"]["key"][1] += 1
        with self.assertRaises(ValueError):
            N.geometry(bad, current, rows, old["atr"], old["D"])
        with self.assertRaises(ValueError):
            N.geometry(path, current, rows, old["atr"], 0)

    def test_metadataとJSON小型出典(self) -> None:
        """列順/技法/尺度とJSON有限性を確認し、geometryへSOURCE全文を転記しない。

        引数: self(GeometryTests)は検査先。
        返り値: None。
        """
        self.assertEqual(N.FEATURES[:30], N.F58.FEATURES)
        self.assertEqual([m["id"] for m in N.FEATURES], [f"F{i:02d}" for i in range(1, 39)])
        self.assertEqual([m["method"] for m in N.FEATURES[30:]], ["P10", "P10", "P05", "P10"] * 2)
        self.assertTrue(all(m["family"] == "price" and m["scale"] == "m03" for m in N.FEATURES[30:]))
        result = N.extract(*fixture(t_changes(), 24))
        g = result["geometry"]["1"]["T"]
        self.assertEqual(set(g["b"]), {"index", "key"})
        self.assertEqual(set(g["u_max_source"]), {"index", "key"})
        self.assertNotIn("trace", g)
        self.assertNotIn("sources", g)
        json.dumps(result, ensure_ascii=False, allow_nan=False)


def run() -> dict:
    """手作りSOURCEだけで人工を実行し、件数と固定材料指紋を返す。

    引数: なし。
    返り値: dictは成功/人工件数/詳細。実市場・本物教師・fitの読取や計算はしない。
    """
    capture = io.StringIO()
    result = unittest.TextTestRunner(stream=capture, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(GeometryTests))
    return {"成功": result.wasSuccessful(), "人工件数": result.testsRun, "失敗": len(result.failures), "エラー": len(result.errors),
        "市場入力読取": False, "本物特徴計算": False, "本物fit": False,
        "固定58人工factorySHA256": hashlib.sha256(OLD_TEST.read_bytes()).hexdigest(),
        "詳細": "" if result.wasSuccessful() else capture.getvalue()}


if __name__ == "__main__":
    value = run()
    print(json.dumps(value, ensure_ascii=False))
    raise SystemExit(0 if value["成功"] else 1)
