"""74入力を手書きOHLCと保存値だけで検査し、本物入力を開かない。"""

from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import unittest


PATH = Path(__file__).with_name("入力.py")
SPEC = importlib.util.spec_from_file_location("内包偽突破74の人工出力", PATH)
I = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(I)


def fixture(b: int = 10, confirm_offset: int | None = 1, background: int = 1) -> tuple:
    """価格結果や実データなしで、買いの内包偽突破15足と元Q0を作る。

    引数: b(int)は偽突破番号、confirm_offset(int|None)は確認までの足数、background(int)はrawDI。
    返り値: tuple[dict,dict]は元slotと73形の最小特徴。各足の期待価格は人工定数。
    """
    session = "人工74_Day"
    rows = [{"session": session, "index": n, "minutes": 3, "start": n * 180, "end": (n + 1) * 180,
        "confirm": (n + 1) * 180 + 1, "confirm_line": 10 + n, "publish": True, "missing": 0,
        "open": 100, "high": 110, "low": 90, "close": 100} for n in range(15)]
    rows[b - 1].update(high=108, low=92)
    rows[b].update(open=99, high=107, low=91, close=95)
    if confirm_offset is not None and b + confirm_offset < 15:
        rows[b + confirm_offset].update(open=100, high=112, low=93, close=109)
    vectors = {"1": [0.0] * 64, "-1": [0.0] * 64}
    values = {0: .2 * background, 1: .1, 2: .05, 14: .3, 47: -.05, 51: 1.0}
    for index, value in values.items():
        vectors["1"][index] = value
        vectors["-1"][index] = -value if index in (0, 1, 2, 14) else value
    feature = {"ready": True, "reason": "準備済み", "vectors": vectors, "background_direction": background,
        "base": {"history": {"reference_sources": rows[:10], "reaction_sources": rows[10:]},
            "base": {"sources": {"current": deepcopy(rows[-1])}}}}
    slot = {"session": session, "slot_id": "人工74_予定", "scheduled": 2700, "time": 2701, "line": 1000,
        "side": -1, "role": "反転", "atr": 10.0, "D": 10, "reason": "保存Q0理由", "ready": True,
        "policy": "Q0", "feature": "転記禁止", "prediction": "転記禁止", "closed": "参照禁止"}
    return slot, feature


def rows_of(feature: dict) -> list[dict]:
    """人工特徴内の15足を参照順で取り出す。

    引数: feature(dict)は人工特徴。
    返り値: list[dict]は元dictへの参照で、人工反例の変更箇所を明示するためだけに使う。
    """
    history = feature["base"]["history"]
    return history["reference_sources"] + history["reaction_sources"]


def synchronize(feature: dict) -> None:
    """人工の最新足をcurrentへ複写する。

    引数: feature(dict)は最新足を変更した人工特徴。
    返り値: None。期待する一致と改竄反例を分離する。
    """
    feature["base"]["base"]["sources"]["current"] = deepcopy(rows_of(feature)[-1])


def feature_value(feature: dict, index: int, value: float) -> None:
    """一つの保存値を鏡像規約どおり両側へ設定する。

    引数: feature(dict)は人工特徴、index(int)は列、value(float)は買い側値。
    返り値: None。方向不変列は反転しない。
    """
    feature["vectors"]["1"][index] = value
    feature["vectors"]["-1"][index] = -value if index in (0, 1, 2, 14) else value


def reflected_source(row: dict | None) -> dict | None:
    """人工価格を200からの反射へ写す。

    引数: row(dict|None)はSOURCE又は未形成。
    返り値: dict|Noneは高安を交換した深い複写。
    """
    if row is None:
        return None
    result = deepcopy(row)
    result.update(open=200 - row["open"], close=200 - row["close"], high=200 - row["low"], low=200 - row["high"])
    return result


def reflected_feature(feature: dict) -> dict:
    """SOURCE・DI・正規化両vectorをまとめて鏡像へ写す。

    引数: feature(dict)は人工特徴。
    返り値: dictは売買交換後の特徴。元引数を変更しない。
    """
    result = deepcopy(feature)
    history = result["base"]["history"]
    for key in ("reference_sources", "reaction_sources"):
        history[key] = [reflected_source(row) for row in history[key]]
    synchronize(result)
    result["background_direction"] *= -1
    result["vectors"] = {"1": deepcopy(feature["vectors"]["-1"]), "-1": deepcopy(feature["vectors"]["1"])}
    return result


def candidate(observation: dict, b: int = 10, side: int = 1) -> dict:
    """人工で番号を指定した一形を得る。

    引数: observation(dict)は実出力、b/side(int)は人工で固定した識別。
    返り値: dictは一意な候補。実出力から期待価格を計算しない。
    """
    selected = [row for row in observation["candidates"] if row["B"]["index"] == b and row["side"] == side]
    if len(selected) != 1:
        raise AssertionError("人工で指定した形が一意でない")
    return selected[0]


# ----------------------------------------
class InputTests(unittest.TestCase):
    """公開時点・価格境界・複合資格・純射影を架空材料で検査する。"""

    def test_01_basic_source_and_choice(self) -> None:
        """基本の買い確認・出典hash・純14項目を検査する。

        引数: self(InputTests)は検査器。
        返り値: None。不一致ならAssertionError。
        """
        slot, feature = fixture()
        before = deepcopy((slot, feature))
        obs = I.extract(slot, feature)
        self.assertEqual((obs["ready"], obs["side"], obs["role"], obs["source_count"]), (True, 1, "順行", 15))
        self.assertEqual(obs["source_sha256"], hashlib.sha256(I.canonical(rows_of(feature)).encode("utf-8")).hexdigest())
        row = candidate(obs)
        self.assertEqual((row["status"], row["C"]["index"], row["denial"], row["confirmation_line"], row["denial_line"]), ("有効", 11, None, 108, 91))
        self.assertEqual(row["id"], "人工74_Day|H|+1|10|" + float(1981).hex() + "|20")
        old, h0, h1 = [I.choose(slot, obs, p) for p in ("I0", "H0", "H1")]
        self.assertEqual({k: old[k] for k in I.SLOT_FIELDS}, {k: slot[k] for k in I.SLOT_FIELDS})
        self.assertEqual((h0["side"], h0["origin"], h0["pattern_id"]), (1, "内包偽突破", row["id"]))
        self.assertEqual({k: v for k, v in h0.items() if k != "policy"}, {k: v for k, v in h1.items() if k != "policy"})
        self.assertEqual(set(h0), {*I.SLOT_FIELDS, "session", "policy", "origin", "pattern_id"})
        self.assertEqual((slot, feature), before)

    def test_02_strict_inside(self) -> None:
        """内包高値又は安値の等号を形成へ含めない。

        引数: self(InputTests)は検査器。
        返り値: None。
        """
        for key, value in (("high", 110), ("low", 90)):
            slot, feature = fixture()
            rows_of(feature)[9][key] = value
            obs = I.extract(slot, feature)
            self.assertFalse(any(c["B"]["index"] == 10 for c in obs["candidates"]))

    def test_03_strict_false_break(self) -> None:
        """Bの等号と両端同時突破を偽突破へ含めない。

        引数: self(InputTests)は検査器。
        返り値: None。
        """
        for update in ({"high": 108}, {"low": 92}, {"high": 109, "low": 91}):
            slot, feature = fixture()
            rows_of(feature)[10].update(update)
            self.assertFalse(any(c["B"]["index"] == 10 for c in I.extract(slot, feature)["candidates"]))

    def test_04_confirmation_three_bars(self) -> None:
        """B後1/2/3足は確認でき、4足目の初突破を救済しない。

        引数: self(InputTests)は検査器。
        返り値: None。
        """
        for offset in (1, 2, 3):
            slot, feature = fixture(10, offset)
            self.assertEqual(candidate(I.extract(slot, feature))["C"]["index"], 10 + offset)
        slot, feature = fixture(9, 4)
        row = candidate(I.extract(slot, feature), 9)
        self.assertEqual((row["status"], row["C"], row["confirmation_observed"], row["confirmation_deadline_end"]), ("確認期限切れ", None, 3, 2340))

    def test_05_close_cross_and_no_b_reuse(self) -> None:
        """確認端等号や高値だけの突破を確認Cへ使わない。

        引数: self(InputTests)は検査器。
        返り値: None。
        """
        slot, feature = fixture()
        rows = rows_of(feature)
        rows[11].update(close=108, high=120)
        row = candidate(I.extract(slot, feature))
        self.assertIsNone(row["C"])
        self.assertEqual(row["status"], "確認期限切れ")
        slot, feature = fixture(12, None)
        row = candidate(I.extract(slot, feature), 12)
        self.assertEqual((row["status"], row["confirmation_observed"], row["confirmation_complete"]), ("未確認", 2, False))

    def test_06_first_confirmation_and_denial(self) -> None:
        """最初のC・等号否定を固定し、その後の再突破で復活させない。

        引数: self(InputTests)は検査器。
        返り値: None。
        """
        slot, feature = fixture()
        rows = rows_of(feature)
        rows[12].update(close=91)
        rows[13].update(close=110, high=113)
        row = candidate(I.extract(slot, feature))
        self.assertEqual((row["C"]["index"], row["denial"]["index"], row["status"]), (11, 12, "否定"))
        self.assertEqual(row["id"], candidate(I.extract(*fixture()))["id"])

    def test_07_window_edges(self) -> None:
        """C終端の900秒左端を除き、予定同値の右端を含める。

        引数: self(InputTests)は検査器。
        返り値: None。
        """
        slot, feature = fixture(8, 1)
        self.assertEqual(candidate(I.extract(slot, feature), 8)["status"], "確認窓外")
        slot, feature = fixture(13, 1)
        self.assertEqual(candidate(I.extract(slot, feature), 13)["status"], "有効")
        slot, feature = fixture(8, 1)
        rows_of(feature)[10].update(close=91)
        self.assertEqual(candidate(I.extract(slot, feature), 8)["status"], "否定")

    def test_08_latest_confirmation(self) -> None:
        """複数の有効形から最新Cを選ぶ。

        引数: self(InputTests)は検査器。
        返り値: None。
        """
        slot, feature = fixture(12, 1)
        rows = rows_of(feature)
        rows[8].update(high=108, low=92)
        rows[9].update(open=99, high=107, low=91, close=95)
        rows[10].update(high=112, low=93, close=109)
        rows[11].update(high=110, low=95)
        rows[12].update(high=109, low=94, close=97)
        rows[13].update(high=113, low=96, close=111)
        obs = I.extract(slot, feature)
        self.assertEqual(candidate(obs, 9)["status"], "有効")
        self.assertEqual(obs["selected"]["1"]["B"]["index"], 12)

    def test_09_latest_b_tie(self) -> None:
        """同じCを持つ二形では最新Bを選ぶ。

        引数: self(InputTests)は検査器。
        返り値: None。
        """
        slot, feature = fixture()
        rows = rows_of(feature)
        rows[6].update(high=112, low=90)
        rows[7].update(high=110, low=92)
        rows[8].update(high=109, low=91, close=100)
        rows[9].update(high=108, low=93)
        rows[10].update(high=107, low=92, close=95)
        rows[11].update(high=112, low=94, close=111)
        obs = I.extract(slot, feature)
        self.assertEqual((candidate(obs, 8)["C"]["index"], candidate(obs, 10)["C"]["index"]), (11, 11))
        self.assertEqual(obs["selected"]["1"]["B"]["index"], 10)

    def test_10_all_mirror(self) -> None:
        """売買反射で全候補の四足・否定・価格線・資格を交換する。

        引数: self(InputTests)は検査器。
        返り値: None。
        """
        for denied in (False, True):
            slot, feature = fixture(background=-1)
            if denied:
                rows_of(feature)[12].update(close=91)
            left, right = I.extract(slot, feature), I.extract(slot, reflected_feature(feature))
            self.assertEqual((right["side"], right["role"]), (-left["side"], left["role"]))
            self.assertEqual(len(left["candidates"]), len(right["candidates"]))
            for a, b in zip(left["candidates"], right["candidates"]):
                self.assertEqual(b["side"], -a["side"])
                for field in ("A", "I", "B", "C", "denial"):
                    self.assertEqual(b[field], reflected_source(a[field]))
                for field in ("status", "reason", "confirmation_observed", "confirmation_complete", "confirmation_deadline_end"):
                    self.assertEqual(b[field], a[field])
                self.assertEqual(b["confirmation_line"], 200 - a["confirmation_line"])
                self.assertEqual(b["denial_line"], 200 - a["denial_line"])
            for side in ("1", "-1"):
                expected = deepcopy(left["qualifications"][side])
                expected["values"]["raw_background_direction"] *= -1
                self.assertEqual(right["qualifications"][str(-int(side))], expected)

    def test_11_unknown_and_placeholder(self) -> None:
        """旧未準備は履歴を読まず未知を保持し、placeholderも純射影する。

        引数: self(InputTests)は検査器。
        返り値: None。
        """
        slot, feature = fixture()
        slot.update(ready=False, side=0, role="待機", line=None, atr=None, D=None)
        feature = {"ready": False}
        obs = I.extract(slot, feature)
        self.assertEqual((obs["source_count"], obs["source_sha256"], obs["candidates"], obs["side"]), (0, None, [], 0))
        self.assertTrue(all(v is None for v in obs["qualifications"]["1"]["values"].values()))
        self.assertEqual(I.choose(slot, obs, "H1")["line"], None)

    def test_12_fast_boundaries(self) -> None:
        """FastK中央差等号は許し、進行等号は拒否する。

        引数: self(InputTests)は検査器。
        返り値: None。
        """
        for index, value, expected in ((1, 0, True), (1, -.01, False), (2, 0, False), (2, -.01, False)):
            slot, feature = fixture()
            feature_value(feature, index, value)
            self.assertEqual(I.extract(slot, feature)["qualifications"]["1"]["qualified"], expected)

    def test_13_reversal_adx_clv(self) -> None:
        """反転だけADX差有効・減速・正CLVを要求する。

        引数: self(InputTests)は検査器。
        返り値: None。
        """
        slot, feature = fixture(background=-1)
        self.assertEqual((I.extract(slot, feature)["side"], I.extract(slot, feature)["role"]), (1, "反転"))
        for index, value, reason in ((51, 0, "ADX変化が未知"), (47, 0, "ADXが非減速"), (14, 0, "15分終値位置が非正")):
            changed = deepcopy(feature)
            feature_value(changed, index, value)
            self.assertEqual(I.extract(slot, changed)["qualifications"]["1"]["reason"], reason)
        slot, feature = fixture(background=1)
        for index, value in ((51, 0), (47, 0), (14, -1)):
            feature_value(feature, index, value)
        self.assertTrue(I.extract(slot, feature)["qualifications"]["1"]["qualified"])

    def test_14_di_zero(self) -> None:
        """rawDI同値とF01同値をどちらも新候補不採用にする。

        引数: self(InputTests)は検査器。
        返り値: None。
        """
        slot, feature = fixture(background=0)
        self.assertEqual(I.extract(slot, feature)["qualifications"]["1"]["reason"], "上位DI同値")
        slot, feature = fixture()
        feature_value(feature, 0, 0)
        self.assertEqual(I.extract(slot, feature)["qualifications"]["1"]["reason"], "DI優勢差同値")

    def test_15_future_suffix(self) -> None:
        """未来終端・未来keyの不正OHLCを検査せず除外しprefix不変にする。

        引数: self(InputTests)は検査器。
        返り値: None。
        """
        slot, feature = fixture()
        expected = I.extract(slot, feature)
        history = feature["base"]["history"]
        history["reference_sources"].append({"session": slot["session"], "end": 2880, "confirm": None, "close": float("nan")})
        history["reaction_sources"].append({"session": slot["session"], "end": 2700, "confirm": 2702, "confirm_line": 1001, "close": None})
        self.assertEqual(I.extract(slot, feature), expected)

    def test_16_hole_not_repaired(self) -> None:
        """過去窓の穴を未来足で埋めず、可視不連続や欠枠は停止する。

        引数: self(InputTests)は検査器。
        返り値: None。
        """
        for kind in ("不足", "番号gap", "欠枠", "非公開", "時間gap", "key同値"):
            slot, feature = fixture()
            rows = rows_of(feature)
            if kind == "不足":
                feature["base"]["history"]["reference_sources"].pop(3)
                feature["base"]["history"]["reference_sources"].append({"session": slot["session"], "end": 2880})
            elif kind == "番号gap": rows[3]["index"] = 99
            elif kind == "欠枠": rows[3]["missing"] = 1
            elif kind == "非公開": rows[3]["publish"] = False
            elif kind == "時間gap": rows[3]["start"] -= 1
            else:
                rows[2]["confirm"] = rows[3]["confirm"]
                rows[2]["confirm_line"] = rows[3]["confirm_line"]
            with self.assertRaises(ValueError, msg=kind): I.extract(slot, feature)

    def test_17_source_and_value_rejection(self) -> None:
        """current差・非有限・非二値・鏡像矛盾を未知補完せず拒否する。

        引数: self(InputTests)は検査器。
        返り値: None。
        """
        for kind in ("current", "OHLC", "時計", "値", "mask", "両方向進行", "背景"):
            slot, feature = fixture()
            if kind == "current": feature["base"]["base"]["sources"]["current"]["close"] = 101
            elif kind == "OHLC": rows_of(feature)[2]["close"] = float("nan")
            elif kind == "時計": rows_of(feature)[2]["end"] = float("nan")
            elif kind == "値": feature_value(feature, 47, float("nan"))
            elif kind == "mask": feature_value(feature, 51, 2)
            elif kind == "両方向進行": feature["vectors"]["-1"][2] = .1
            else: feature["background_direction"] = -1
            with self.assertRaises(ValueError, msg=kind): I.extract(slot, feature)

    def test_18_clock_and_policy(self) -> None:
        """公開key等号を受理し、後行未公開と政策/準備矛盾を拒否する。

        引数: self(InputTests)は検査器。
        返り値: None。
        """
        slot, feature = fixture(13, 1)
        slot["line"] = 24
        obs = I.extract(slot, feature)
        self.assertEqual(obs["side"], 1)
        slot["line"] = 23
        with self.assertRaises(ValueError): I.extract(slot, feature)
        slot, feature = fixture()
        obs = I.extract(slot, feature)
        with self.assertRaises(ValueError): I.choose(slot, obs, "Q0")
        obs["ready"] = False
        with self.assertRaises(ValueError): I.choose(slot, obs, "H0")


# ----------------------------------------
def self_test() -> dict:
    """入力人工18群だけを実行し、集約helper向けに結果を返す。

    引数: なし。
    返り値: dictは成功/テスト件数と失敗詳細。本物読取・fit・市場再生は行わない。
    """
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(InputTests))
    return {"成功": result.wasSuccessful(), "テスト件数": result.testsRun, "本物入力読取": False,
        "fit": 0, "市場再生": False, "失敗": [] if result.wasSuccessful() else [stream.getvalue()]}


if __name__ == "__main__":
    result = self_test()
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    raise SystemExit(0 if result["成功"] else 1)
