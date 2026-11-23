"""固定人工SOURCEだけで、登録10差分とr前後の区間・旧38射影を検査する。"""

from copy import deepcopy
from fractions import Fraction
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("波区間分離の人工対象", HERE / "特徴.py")
N = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(N)
OLD_TEST = HERE.parent / "価格経路の深さと速度/特徴の人工検査.py"
SPEC = importlib.util.spec_from_file_location("波区間分離の固定59人工材料", OLD_TEST)
OLD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OLD)
candle, fixture, slot_at = OLD.candle, OLD.fixture, OLD.slot_at


class SegmentTests(unittest.TestCase):
    """手計算した各区間により、全体平均と部分区間を混同しないことを確認する。"""

    def test_Tの登録とr前後の黄金値(self) -> None:
        """登録100→115/十差分、p115→r117/四足、r117→122/十足を計算する。

        引数: self(SegmentTests)は検査先。
        返り値: None。
        """
        result = N.extract(*fixture(OLD.t_changes(), 24))
        g = result["segments"]["1"]["T"]
        self.assertEqual([g[name]["index"] for name in ("registration_start", "b", "a", "p", "r", "current")], [0, 10, 10, 10, 14, 24])
        self.assertEqual((g["registration_steps"], g["approach_steps"], g["since_r_steps"]), (10, 4, 10))
        self.assertEqual((g["registration_net"], g["registration_total_abs"], g["approach_net"], g["since_r_net"]), (15, 15, 2, 5))
        self.assertEqual(g["values"], [0.06, 1, 0.02, 0.02])
        self.assertEqual(result["vectors"]["1"][38:42], g["values"])
        self.assertEqual(g["masks"], {"registration": True, "approach": True, "since_r": True})

    def test_Rは実方向とf起点を使う(self) -> None:
        """上突破から売るRでは登録netが負で、a=fからrの前だけを探索する。

        引数: self(SegmentTests)は検査先。
        返り値: None。
        """
        result = N.extract(*fixture(OLD.r_changes(), 24))
        g = result["segments"]["-1"]["R"]
        self.assertEqual([g[name]["index"] for name in ("b", "a", "p", "r")], [10, 13, 13, 14])
        self.assertEqual(g["values"], [-0.06, -1, 0.04, 0.012])
        self.assertEqual((g["approach_net"], g["since_r_net"]), (1, 3))
        self.assertEqual(result["vectors"]["-1"][42:46], g["values"])

    def test_正r進行を否定しない(self) -> None:
        """ヒゲでrが成立しても終値は元のpより高くなれ、第三値を負へ制限しない。

        引数: self(SegmentTests)は検査先。
        返り値: None。
        """
        result = N.extract(*fixture(OLD.t_changes(), 24))
        self.assertGreater(result["segments"]["1"]["T"]["values"][2], 0)
        result = N.extract(*fixture(OLD.r_changes(), 24))
        self.assertGreater(result["segments"]["-1"]["R"]["values"][2], 0)

    def test_r当足の零と未形成mask(self) -> None:
        """r当足は適用済みの第四値0、rなしは適用外0として区別する。

        引数: self(SegmentTests)は検査先。
        返り値: None。
        """
        _, frames = fixture(OLD.t_changes(), 24)
        g = N.extract(slot_at(frames, 14), frames)["segments"]["1"]["T"]
        self.assertEqual((g["since_r_steps"], g["since_r_net"], g["values"][3]), (0, 0, 0))
        self.assertTrue(g["masks"]["since_r"])
        result = N.extract(*fixture({24: candle(115)}, 24))
        g = result["segments"]["1"]["T"]
        self.assertEqual((g["r"], g["p"], g["approach_steps"], g["since_r_steps"]), (None, None, None, None))
        self.assertEqual(g["values"], [0.06, 1, 0, 0])
        self.assertEqual(g["masks"], {"registration": True, "approach": False, "since_r": False})

    def test_登録十差分はbを含む(self) -> None:
        """b以前の十終値だけではなく、十一終値の最後の登録差分を含める。

        引数: self(SegmentTests)は検査先。
        返り値: None。
        """
        g = N.extract(*fixture({24: candle(115)}, 24))["segments"]["1"]["T"]
        self.assertEqual((g["registration_start"]["index"], g["registration_steps"], g["registration_net"]), (14, 10, 15))
        self.assertEqual(g["values"][:2], [0.06, 1])

    def test_効率は隣接差分絶対値和(self) -> None:
        """同じnetでも往復のあった登録区間を効率1へ圧縮しない。

        引数: self(SegmentTests)は検査先。
        返り値: None。
        """
        changes = OLD.t_changes()
        changes.update({1: {"open": 105, "close": 105, "high": 110, "low": 90},
            2: {"open": 95, "close": 95, "high": 110, "low": 90}})
        g = N.extract(*fixture(changes, 24))["segments"]["1"]["T"]
        self.assertEqual((g["registration_net"], g["registration_total_abs"]), (15, 35))
        self.assertEqual(g["values"][:2], [0.06, 3 / 7])

    def test_総変動零の定義と方向符号(self) -> None:
        """純算術の全同値十一終値は0効率とし、符号反転でnetだけを反転する。

        引数: self(SegmentTests)は検査先。
        返り値: None。
        """
        self.assertEqual(N.registration_statistics([100] * 11, 1, 25), (0, 0, 0, 0))
        closes = [100, 105, 95] + [100] * 7 + [115]
        plus, minus = N.registration_statistics(closes, 1, 25), N.registration_statistics(closes, -1, 25)
        self.assertEqual(plus, (15, 35, Fraction(3, 50), Fraction(3, 7)))
        self.assertEqual(minus, (-15, 35, Fraction(-3, 50), Fraction(-3, 7)))

    def test_Tのpはr直前までの最初の最大(self) -> None:
        """同値130を二回訪れても先頭を選び、r自身や後の150をpへ使わない。

        引数: self(SegmentTests)は検査先。
        返り値: None。
        """
        changes = {index: candle(122) for index in range(10, 25)}
        changes.update({10: candle(115), 11: candle(130), 12: candle(130),
            13: candle(117, 118, 110), 14: candle(120), 20: candle(150)})
        _, frames = fixture(changes, 24)
        a = N.extract(slot_at(frames, 14), frames)["segments"]["1"]["T"]
        b = N.extract(slot_at(frames, 24), frames)["segments"]["1"]["T"]
        self.assertEqual((a["p"]["index"], b["p"]["index"], b["approach_steps"]), (11, 11, 2))
        self.assertEqual(b["values"][2], -0.26)

    def test_Rのpは実方向最大すなわち最小終値(self) -> None:
        """反転売りではf以後の最小98を選び、同値の早い足に固定する。

        引数: self(SegmentTests)は検査先。
        返り値: None。
        """
        changes = OLD.r_changes()
        changes.update({11: candle(105), 12: candle(98), 13: candle(98), 20: candle(50)})
        g = N.extract(*fixture(changes, 24))["segments"]["-1"]["R"]
        self.assertEqual((g["a"]["index"], g["p"]["index"], g["r"]["index"]), (11, 12, 14))
        self.assertEqual((g["approach_net"], g["approach_steps"], g["values"][2]), (-6, 2, -0.12))

    def test_現在ATRで過去区間も再尺度化(self) -> None:
        """登録平均とr前後は現在ATRで割り、効率はATRに依存しない。

        引数: self(SegmentTests)は検査先。
        返り値: None。
        """
        slot, frames = fixture(OLD.t_changes(), 24)
        a = N.extract(slot, frames)["segments"]["1"]["T"]
        slot["atr"] = 50
        b = N.extract(slot, frames)["segments"]["1"]["T"]
        self.assertEqual(a["values"], [2 * b["values"][0], b["values"][1], 2 * b["values"][2], 2 * b["values"][3]])
        self.assertEqual(a["p"], b["p"])

    def test_取消後r統計を記述し旗は不変(self) -> None:
        """取消後もr後平均を更新するが、旧episode/k有効旗を復活させない。

        引数: self(SegmentTests)は検査先。
        返り値: None。
        """
        _, frames = fixture(OLD.t_changes(), 24)
        a = N.extract(slot_at(frames, 17), frames)
        b = N.extract(slot_at(frames, 24), frames)
        pa, pb = a["segments"]["1"]["T"], b["segments"]["1"]["T"]
        self.assertEqual(pa["episode_id"], pb["episode_id"])
        self.assertEqual(pa["p"], pb["p"])
        self.assertNotEqual(pa["values"][3], pb["values"][3])
        self.assertFalse(b["paths"]["1"]["T"]["episode_valid"])

    def test_置換と期限は旧区間を消す(self) -> None:
        """新bは新登録10差分に替え、TTLclearは全四値を適用外0へ戻す。

        引数: self(SegmentTests)は検査先。
        返り値: None。
        """
        changes = OLD.t_changes(25)
        changes[25] = candle(140)
        g = N.extract(*fixture(changes, 25))["segments"]["1"]["T"]
        self.assertEqual((g["b"]["index"], g["registration_start"]["index"]), (25, 15))
        self.assertIsNone(g["r"])
        self.assertEqual(g["values"][2:], [0, 0])
        changes = OLD.t_changes(30)
        changes[30] = candle(160)
        g = N.extract(*fixture(changes, 30))["segments"]["1"]["T"]
        self.assertEqual((g["episode_id"], g["values"], g["registration_steps"]), (None, [0, 0, 0, 0], 0))

    def test_resetで旧区間を接続しない(self) -> None:
        """古い不良足をまたいだb/rの進行を新しい準備済み枠へ残さない。

        引数: self(SegmentTests)は検査先。
        返り値: None。
        """
        slot, frames = fixture(OLD.t_changes(33), 33)
        frames[16]["missing"] = 1
        result = N.extract(slot, frames)
        self.assertTrue(result["ready"])
        self.assertEqual(result["segments"]["1"]["T"]["values"], [0, 0, 0, 0])

    def test_未IDと未readyのschema(self) -> None:
        """未IDはcurrentと既知0を残し、旧未準備はsegmentsNoneと空vectorsを保つ。

        引数: self(SegmentTests)は検査先。
        返り値: None。
        """
        result = N.extract(*fixture({}, 24))
        for side in ("1", "-1"):
            for role in ("T", "R"):
                g = result["segments"][side][role]
                self.assertEqual(g["values"], [0, 0, 0, 0])
                self.assertEqual(g["masks"], {"registration": False, "approach": False, "since_r": False})
                self.assertIsNone(g["registration_net"])
                self.assertEqual(g["current"]["index"], 24)
        _, frames = fixture({}, 24)
        unknown = N.extract(slot_at(frames, 10), frames)
        self.assertFalse(unknown["ready"])
        self.assertEqual(unknown["vectors"], {"1": [], "-1": []})
        self.assertEqual(unknown["segments"], {"1": {"T": None, "R": None}, "-1": {"T": None, "R": None}})

    def test_未来の峰と不良足が全出力に影響しない(self) -> None:
        """未来に追加した大きな峰/NPを、既存pや区間値へ先読みしない。

        引数: self(SegmentTests)は検査先。
        返り値: None。
        """
        slot, frames = fixture(OLD.t_changes(), 24)
        before = N.extract(slot, frames)
        future = deepcopy(frames[-1])
        future.update(index=25, start=4500, end=4680, confirm=None, confirm_line=None,
            close=1000, high=1001, low=999, publish=False)
        self.assertEqual(before, N.extract(slot, frames + [future]))
        future.update(end=slot["scheduled"], confirm=slot["time"], confirm_line=slot["line"] + 1)
        self.assertEqual(before, N.extract(slot, frames + [future]))

    def test_売買鏡像で全四十六列を交換(self) -> None:
        """価格反射と実side交換で、新区間値・p選択を保存する。

        引数: self(SegmentTests)は検査先。
        返り値: None。
        """
        for changes in (OLD.t_changes(), OLD.r_changes(), {}, {24: candle(115)}):
            slot, frames = fixture(changes, 24)
            a = N.extract(slot, frames)
            b = N.extract(*OLD.OLD.OLD.reflect(slot, frames))
            for side in (1, -1):
                self.assertEqual(a["vectors"][str(side)], b["vectors"][str(-side)])
                for role in ("T", "R"):
                    sa, sb = a["segments"][str(side)][role], b["segments"][str(-side)][role]
                    for name in ("b", "a", "p", "r", "registration_net", "registration_total_abs", "approach_steps", "approach_net", "since_r_steps", "since_r_net", "masks", "values"):
                        self.assertEqual(sa[name], sb[name])

    def test_旧三十八全辞書への射影と複写(self) -> None:
        """旧keys/geometry/paths/historyを完全保持し、射影や新listを独立にする。

        引数: self(SegmentTests)は検査先。
        返り値: None。
        """
        for changes in (OLD.t_changes(), OLD.r_changes(), {}):
            slot, frames = fixture(changes, 24)
            before = deepcopy((slot, frames))
            old, new = N.F59.extract(slot, frames), N.extract(slot, frames)
            self.assertEqual((slot, frames), before)
            self.assertEqual(N.control_projection(new), old)
            self.assertEqual(set(new), set(old) | {"control_vectors38", "segments"})
            for name in set(old) - {"vectors"}:
                self.assertEqual(new[name], old[name])
            for side in ("1", "-1"):
                self.assertEqual(new["vectors"][side][:38], old["vectors"][side])
                self.assertEqual(len(new["vectors"][side]), 46)
            projection = N.control_projection(new)
            projection["geometry"]["1"]["T"]["values"][0] = -999
            self.assertEqual(N.control_projection(new), old)
            new["vectors"]["1"][0] = -999
            self.assertEqual(new["control_vectors38"], old["vectors"])

    def test_参照十本keyやRのf欠落は拒否(self) -> None:
        """旧登録参照や段階が壊れたときに、都合のよい区間へ替えない。

        引数: self(SegmentTests)は検査先。
        返り値: None。
        """
        slot, frames = fixture(OLD.r_changes(), 24)
        old = N.F59.extract(slot, frames)
        current = old["base"]["history"]["reaction_sources"][-1]
        rows = {row["index"]: row for row in N.F58.visible_sources(slot, frames)}
        path = deepcopy(old["paths"]["-1"]["R"])
        path["f"] = None
        with self.assertRaises(ValueError):
            N.segments(path, current, rows, old["atr"])
        path = deepcopy(old["paths"]["-1"]["R"])
        path["reference_keys"][0][1] += 1
        with self.assertRaises(ValueError):
            N.segments(path, current, rows, old["atr"])
        path = deepcopy(old["paths"]["-1"]["R"])
        del rows[path["b"]["index"] - 1]
        with self.assertRaises(ValueError):
            N.segments(path, current, rows, old["atr"])

    def test_同秒公開も足数で計算(self) -> None:
        """公開秒差0でも原行と足番号を区別し、区間平均を秒割りしない。

        引数: self(SegmentTests)は検査先。
        返り値: None。
        """
        slot, frames = fixture(OLD.t_changes(), 24)
        for index in range(10, 25):
            frames[index]["confirm"] = slot["scheduled"]
        result = N.extract(slot_at(frames, 24), frames)
        self.assertEqual(result["segments"]["1"]["T"]["values"], [0.06, 1, 0.02, 0.02])

    def test_metadataと小型JSON出典(self) -> None:
        """全追加を同じprice系として記録し、SOURCE配列をsegmentsへ複製しない。

        引数: self(SegmentTests)は検査先。
        返り値: None。
        """
        self.assertEqual(N.FEATURES[:38], N.F59.FEATURES)
        self.assertEqual([m["id"] for m in N.FEATURES], [f"F{i:02d}" for i in range(1, 47)])
        self.assertTrue(all(m["family"] == "price" and m["method"] == "P05" and m["scale"] == "m03" for m in N.FEATURES[38:]))
        result = N.extract(*fixture(OLD.t_changes(), 24))
        g = result["segments"]["1"]["T"]
        self.assertEqual(set(g["p"]), {"index", "key"})
        self.assertNotIn("sources", g)
        self.assertNotIn("closes", g)
        json.dumps(result, ensure_ascii=False, allow_nan=False)


def run() -> dict:
    """手作りSOURCEだけで人工を実行し、結果と固定材料指紋を返す。

    引数: なし。
    返り値: dictは成功/件数/詳細。本物の入力・教師・fit・市場計算を読まず実行しない。
    """
    capture = io.StringIO()
    result = unittest.TextTestRunner(stream=capture, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SegmentTests))
    return {"成功": result.wasSuccessful(), "人工件数": result.testsRun, "失敗": len(result.failures), "エラー": len(result.errors),
        "市場入力読取": False, "本物特徴計算": False, "本物fit": False,
        "固定59人工factorySHA256": hashlib.sha256(OLD_TEST.read_bytes()).hexdigest(),
        "詳細": "" if result.wasSuccessful() else capture.getvalue()}


if __name__ == "__main__":
    value = run()
    print(json.dumps(value, ensure_ascii=False))
    raise SystemExit(0 if value["成功"] else 1)
