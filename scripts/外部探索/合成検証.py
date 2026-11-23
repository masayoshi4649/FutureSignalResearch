"""00008の入口式・時点・選定・期間境界を、実データなしで確認する。"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("外部探索の合成対象", Path(__file__).with_name("探索.py"))
E = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = E
SPEC.loader.exec_module(E)
CONFIG = E.W.read_json(E.STUDY / "条件.json")


def rule(family: str, parameter: int | float, extra: str = "なし", size: int = 3) -> dict:
    """合成入口に適用する固定形式の候補を作る。

    引数: family (str) は系統、parameter (int | float) は閾値、extra (str) は補助、size (int) は分足。
    返り値: dict は一候補。
    """
    return {"候補ID": f"{size}分_{family}_{parameter}_{extra}", "時間足分": size,
            "手法": family, "パラメータ": parameter, "補助": extra}


def row_for(family: str = "RSI回復") -> dict:
    """各系統で買い条件が成立する、小さな確定特徴を作る。

    引数: family (str) は検査対象の系統。
    返り値: dict は時点と指標の合成値。実価格を使わない。
    """
    row = {"時間足分": 3, "side": 1, "close": 101.0, "rsi": 35.0, "adx": 19.0,
           "plus_di": 12.0, "minus_di": 8.0, "ema20": 100.0, "bb_mean": 100.0, "bb_sd": 5.0,
           "前値": {"close": 99.0, "rsi": 29.0, "adx": 19.0, "plus_di": 8.0, "minus_di": 12.0,
                    "bb_mean": 100.0, "bb_sd": 5.0},
           "過去RSI": [39.0, 45.0, 49.0], "上位準備済": True, "上位方向": 0}
    if family == "RSI再加速":
        row["rsi"] = 51.0
        row["前値"]["rsi"] = 49.0
        row["上位方向"] = 1
    elif family == "DMI方向発生":
        row["adx"] = 25.0
        row["前値"]["adx"] = 24.0
    elif family == "BB復帰価格確認":
        row["前値"]["close"] = 89.0
        row["close"] = 90.0
    return row


def mirror(row: dict) -> dict:
    """価格・RSI・DIと方向を上下対称へ写す。

    引数: row (dict) は買い側の合成特徴。
    返り値: dict は売り側へ鏡像変換した新しい辞書。
    """
    value = deepcopy(row)
    value["side"] *= -1
    value["上位方向"] *= -1
    for target in (value, value["前値"]):
        for key in ("close", "ema20", "bb_mean"):
            if key in target and target[key] is not None:
                target[key] = 200 - target[key]
        if target["rsi"] is not None:
            target["rsi"] = 100 - target["rsi"]
        target["plus_di"], target["minus_di"] = target["minus_di"], target["plus_di"]
    value["過去RSI"] = [None if r is None else 100-r for r in value["過去RSI"]]
    return value


def frame(index: int, rsi: float | None, missing: int = 0) -> dict:
    """上位足の時点と過去窓を検査する確定足を作る。

    引数: index (int) は足番号、rsi (float | None) は指標、missing (int) は欠枠数。
    返り値: dict はenrich用の最小入力。
    """
    return {"index": index, "end": (index+1)*180, "confirm": (index+1)*180,
            "confirm_line": index+1, "publish": True, "missing": missing,
            "close": 100+index, "rsi": rsi, "adx": 19.0, "plus_di": 12.0, "minus_di": 8.0,
            "bb_mean": 100.0, "bb_sd": 5.0, "ema20": 99.0, "ema20_previous": 98.0}


def selection_row(cid: str, train: float = .7, validation: float = .7) -> dict:
    """選定規則を検査する支持付きの期間集計を作る。

    引数: cid (str) は候補ID、train/validation (float) は主確認率。
    返り値: dict は入口・運用を持つ合成候補。
    """
    result = {"候補ID": cid}
    for phase, rate in (("学習", train), ("条件選択", validation)):
        result[phase] = {"入口": {**CONFIG["入口支持"][phase], "確認率": rate,
                        "30分間引き_約定候補数": CONFIG["間引き必要件数"][phase], "30分間引き_確認率": rate},
                        "運用": {**CONFIG["費用支持"][phase], "品質注意場数": 0,
                        "追加5pt純損益円": 1000.0 if phase == "学習" else 500.0, "追加5pt平均円": 50.0}}
    return result


# ----------------------------------------
# 入口の式、等号と売買の対称性。

class 入口条件検証(unittest.TestCase):
    """未来のラベルを含まない手作り特徴で条件を確認する。"""

    def test_RSI回復の境界と二閾値(self) -> None:
        """前値の等号を許し、現在値の等号では交差を発動しない。

        引数: なし。
        返り値: None。
        """
        for level in (30, 40):
            row = row_for()
            row["前値"]["rsi"], row["rsi"] = level, level+1
            self.assertTrue(E.allowed(row, rule("RSI回復", level)))
            row["rsi"] = level
            self.assertFalse(E.allowed(row, rule("RSI回復", level)))
            row["前値"]["rsi"], row["rsi"] = level+1, level+2
            self.assertFalse(E.allowed(row, rule("RSI回復", level)))

    def test_全系統は実終値改善が必要(self) -> None:
        """指標だけ改善して終値が同値または悪化した入口を拒否する。

        引数: なし。
        返り値: None。
        """
        for family, parameter in (("RSI回復", 30), ("RSI再加速", 3), ("DMI方向発生", 25), ("BB復帰価格確認", 2.0)):
            row = row_for(family)
            self.assertTrue(E.allowed(row, rule(family, parameter)))
            row["close"] = row["前値"]["close"]
            self.assertFalse(E.allowed(row, rule(family, parameter)))
            row["close"] -= 1
            self.assertFalse(E.allowed(row, rule(family, parameter)))

    def test_低ADXは二十未満かつ非上昇(self) -> None:
        """低ADX補助の閾値と前値同値を確認する。

        引数: なし。
        返り値: None。
        """
        row = row_for()
        candidate = rule("RSI回復", 30, "役割別")
        self.assertTrue(E.allowed(row, candidate))
        row["adx"] = 20
        self.assertFalse(E.allowed(row, candidate))
        row["adx"], row["前値"]["adx"] = 19, 18
        self.assertFalse(E.allowed(row, candidate))
        row["前値"]["adx"] = None
        self.assertFalse(E.allowed(row, candidate))

    def test_補助なしへ不要な指標準備を課さない(self) -> None:
        """RSI回復単体はADXや上位足の未準備で抑止しない。

        引数: なし。
        返り値: None。
        """
        row = row_for()
        row["adx"] = row["前値"]["adx"] = None
        row["上位準備済"] = False
        self.assertTrue(E.allowed(row, rule("RSI回復", 30)))
        self.assertFalse(E.allowed(row, rule("RSI回復", 30, "役割別")))

    def test_RSI再加速の窓幅と欠損(self) -> None:
        """直近3本と5本を区別し、窓全体の定義を要求する。

        引数: なし。
        返り値: None。
        """
        row = row_for("RSI再加速")
        row["過去RSI"] = [20, 20, 45, 45, 49]
        self.assertFalse(E.allowed(row, rule("RSI再加速", 3)))
        self.assertTrue(E.allowed(row, rule("RSI再加速", 5)))
        row["過去RSI"] = [39, None, 49]
        self.assertFalse(E.allowed(row, rule("RSI再加速", 3)))
        row["過去RSI"] = [39, 49]
        self.assertFalse(E.allowed(row, rule("RSI再加速", 3)))

    def test_RSI再加速の五十交差とEMA側(self) -> None:
        """50の現在同値とEMA同値を拒否し、実際の交差を要求する。

        引数: なし。
        返り値: None。
        """
        row = row_for("RSI再加速")
        row["前値"]["rsi"] = 50
        self.assertTrue(E.allowed(row, rule("RSI再加速", 3)))
        row["rsi"] = 50
        self.assertFalse(E.allowed(row, rule("RSI再加速", 3)))
        row["rsi"], row["ema20"] = 51, row["close"]
        self.assertFalse(E.allowed(row, rule("RSI再加速", 3)))

    def test_DMI交差とADX上昇境界(self) -> None:
        """DI前同値とADX閾値同値を許すが、ADX横ばいを拒否する。

        引数: なし。
        返り値: None。
        """
        for level in (20, 25):
            row = row_for("DMI方向発生")
            row["前値"]["plus_di"] = row["前値"]["minus_di"]
            row["adx"], row["前値"]["adx"] = level, level-1
            self.assertTrue(E.allowed(row, rule("DMI方向発生", level)))
            row["前値"]["adx"] = level
            self.assertFalse(E.allowed(row, rule("DMI方向発生", level)))
            row["前値"]["adx"] = level-1
            row["plus_di"] = row["minus_di"]
            self.assertFalse(E.allowed(row, rule("DMI方向発生", level)))

    def test_BBの各足帯と倍率と等号(self) -> None:
        """前足は前足の帯を使い、現在の帯内等号を許す。

        引数: なし。
        返り値: None。
        """
        row = row_for("BB復帰価格確認")
        self.assertTrue(E.allowed(row, rule("BB復帰価格確認", 2.0)))
        self.assertFalse(E.allowed(row, rule("BB復帰価格確認", 2.5)))
        row["前値"]["close"] = 87
        self.assertTrue(E.allowed(row, rule("BB復帰価格確認", 2.5)))
        row["前値"]["close"] = 90
        self.assertFalse(E.allowed(row, rule("BB復帰価格確認", 2.0)))
        row["前値"]["close"], row["前値"]["bb_mean"], row["bb_mean"] = 89, 100, 120
        self.assertFalse(E.allowed(row, rule("BB復帰価格確認", 2.0)))

    def test_BB反対帯への飛越えを許可(self) -> None:
        """計画の同側境界だけの復帰は反対帯越えも許す。

        引数: なし。
        返り値: None。
        """
        row = row_for("BB復帰価格確認")
        row["close"] = 120
        self.assertTrue(E.allowed(row, rule("BB復帰価格確認", 2.0)))
        self.assertTrue(E.allowed(mirror(row), rule("BB復帰価格確認", 2.0)))

    def test_売買の鏡像と未準備(self) -> None:
        """全系統・補助の成立と不成立を上下対称へ変換して確認する。

        引数: なし。
        返り値: None。
        """
        for family, parameter in (("RSI回復", 30), ("RSI再加速", 3), ("DMI方向発生", 25), ("BB復帰価格確認", 2.0)):
            for extra in ("なし", "役割別"):
                row = row_for(family)
                candidate = rule(family, parameter, extra)
                self.assertTrue(E.allowed(row, candidate))
                self.assertEqual(E.allowed(row, candidate), E.allowed(mirror(row), candidate))
                row["close"] = row["前値"]["close"]
                self.assertEqual(E.allowed(row, candidate), E.allowed(mirror(row), candidate))

    def test_未来ラベルと新規価格に非依存(self) -> None:
        """未来のラベル・約定・判定時刻を書き換えても入口が不変である。

        引数: なし。
        返り値: None。
        """
        for family, parameter in (("RSI回復", 30), ("RSI再加速", 3), ("DMI方向発生", 25), ("BB復帰価格確認", 2.0)):
            row = row_for(family)
            changed = {**deepcopy(row), "ラベル": "逆行先着", "新規価格": -9999,
                       "判定時計秒": 1e30, "最大順行pt": 1e30, "基準純損益円": -1e30}
            for extra in ("なし", "役割別"):
                self.assertEqual(E.allowed(row, rule(family, parameter, extra)), E.allowed(changed, rule(family, parameter, extra)))


# ----------------------------------------
# 上位足、同場窓と候補の準備。

class 時点と候補検証(unittest.TestCase):
    """確認原行と必要履歴を合成した足で検査する。"""

    def test_上位未準備は中立ではない(self) -> None:
        """不足値と未公開足を準備済み中立へ変換しない。

        引数: なし。
        返り値: None。
        """
        self.assertEqual(E.upper_state(None), (False, 0))
        higher = frame(4, 50)
        higher["ema20_previous"] = None
        self.assertEqual(E.upper_state(higher), (False, 0))
        higher["ema20_previous"], higher["publish"] = 98, False
        self.assertEqual(E.upper_state(higher), (False, 0))
        higher["publish"], higher["close"] = True, higher["ema20"]
        self.assertEqual(E.upper_state(higher), (True, 0))

    def test_系統ごとの上位条件(self) -> None:
        """F2は整合、F3は中立も可、F4は中立だけと区別する。

        引数: なし。
        返り値: None。
        """
        for family, parameter, permitted in (("RSI再加速", 3, {1}), ("DMI方向発生", 25, {0, 1}), ("BB復帰価格確認", 2.0, {0})):
            for direction in (-1, 0, 1):
                row = row_for(family)
                row["上位方向"] = direction
                self.assertEqual(E.allowed(row, rule(family, parameter, "役割別")), direction in permitted)
                row["上位準備済"] = False
                self.assertFalse(E.allowed(row, rule(family, parameter, "役割別")))

    def test_同時計上位の原行順と足終了(self) -> None:
        """上位確認が後の原行または未終了なら参照しない。

        引数: なし。
        返り値: None。
        """
        higher = {**frame(4, 50), "end": 900, "confirm": 901, "confirm_line": 20}
        lower = {**frame(4, 51), "end": 900, "confirm": 901, "confirm_line": 19}
        self.assertFalse(E.enrich([lower], [higher])[0]["上位準備済"])
        lower["confirm_line"] = 20
        self.assertTrue(E.enrich([lower], [higher])[0]["上位準備済"])
        lower["end"] = 899
        self.assertFalse(E.enrich([lower], [higher])[0]["上位準備済"])

    def test_RSI窓は今足と未来足を含めない(self) -> None:
        """履歴付加は今足の追加前に行い、未来変更へ依存しない。

        引数: なし。
        返り値: None。
        """
        frames = [frame(i, 40+i) for i in range(7)]
        rows = E.enrich(frames, [])
        self.assertEqual(rows[0]["過去RSI"], [])
        self.assertEqual(rows[5]["過去RSI"], [40, 41, 42, 43, 44])
        self.assertEqual(rows[5]["前値"]["rsi"], 44)
        altered = deepcopy(frames)
        altered[6]["rsi"] = 0
        self.assertEqual(E.enrich(altered, [])[:6], rows[:6])

    def test_欠枠と場切替で前足窓を切る(self) -> None:
        """欠枠直後と別場の先頭に旧RSI窓を持ち込まない。

        引数: なし。
        返り値: None。
        """
        frames = [frame(i, 40+i) for i in range(5)]
        frames[3]["missing"] = 1
        rows = E.enrich(frames, [])
        self.assertEqual(rows[3]["過去RSI"], [])
        self.assertIsNone(rows[3]["前値"]["rsi"])
        self.assertEqual(rows[4]["過去RSI"], [43])
        self.assertEqual(E.enrich([frame(0, 10)], [])[0]["過去RSI"], [])

    def test_三十三IDと旧対照条件(self) -> None:
        """32改作と旧006の固定対照を唯一のIDで列挙する。

        引数: なし。
        返り値: None。
        """
        rules = E.rules(CONFIG)
        self.assertEqual((len(rules), len({r["候補ID"] for r in rules})), (33, 33))
        control = rules[-1]
        self.assertEqual((control["候補ID"], control["時間足分"], control["手法"], control["パラメータ"], control["補助"]),
                         (CONFIG["対照ID"], 3, "開始幅失敗復帰", 15, "ADX環境"))
        for side in (1, -1):
            row = {"時間足分": 3, "side": side, "adx": 19,
                   f"開始幅失敗復帰_15_{side}": True}
            self.assertEqual(E.allowed(row, control), E.W.allowed(row, control))

    def test_期間は開始日で分離(self) -> None:
        """夜の翌日ではなく場開始日で40・24・新1の境界を決める。

        引数: なし。
        返り値: None。
        """
        self.assertEqual(E.phase_of("2026-10-16_Night", CONFIG), "学習")
        self.assertEqual(E.phase_of("2026-10-19_Day", CONFIG), "条件選択")
        self.assertEqual(E.phase_of("2026-11-03_Night", CONFIG), "条件選択")
        self.assertEqual(E.phase_of("2026-11-04_Day", CONFIG), "後続検査")

    def test_全候補の運用は00007の条件と一致(self) -> None:
        """同じ状態機械と幅・倍率・費用・待機を再利用する。

        引数: なし。
        返り値: None。
        """
        old = E.W.read_json(ROOT / "study/00007_固定入口の単一建玉と費用感度/条件.json")
        self.assertTrue(all(old[key] == value for key, value in CONFIG["運用"].items()))
        self.assertEqual(E.O.replay_session.__module__, E.O.__name__)

    def test_実行依存と合成コードも固定対象(self) -> None:
        """共有指標と旧Average・時刻、合成検証の版を後続前に固定する。

        引数: なし。
        返り値: None。
        """
        pins = E.fixed_files(E.STUDY)
        for path in ("scripts/外部探索/合成検証.py", "scripts/複合検証/再生.py", "study/00001_MACDと方向条件の比較/再現.py"):
            self.assertIn(path, pins)


# ----------------------------------------
# 支持・選定順位と、小標本・費用資格の切り分け。

class 選定検証(unittest.TestCase):
    """人工の集計値から事前順位を検査する。"""

    def test_支持を高率小標本より優先(self) -> None:
        """1件全勝の候補を支持付き候補より上へ選ばない。

        引数: なし。
        返り値: None。
        """
        enough = selection_row("十分", .4, .4)
        small = selection_row("少数", 1, 1)
        small["学習"]["入口"]["約定候補数"] = 1
        result = E.select([small, enough], CONFIG)
        self.assertEqual(result["入口用ID"], "十分")
        self.assertEqual(result["70目標達成数"], 0)

    def test_入口は低い期間率と間引きと件数とID順(self) -> None:
        """平均率でなく低い期間率を優先し、同値時の順を確認する。

        引数: なし。
        返り値: None。
        """
        one, two = selection_row("A", .9, .5), selection_row("B", .6, .6)
        self.assertEqual(E.select([one, two], CONFIG)["入口用ID"], "B")
        one = selection_row("A", .6, .6)
        two["条件選択"]["入口"]["30分間引き_確認率"] = .59
        self.assertEqual(E.select([two, one], CONFIG)["入口用ID"], "A")
        two = selection_row("B", .6, .6)
        two["条件選択"]["入口"]["約定候補数"] += 1
        self.assertEqual(E.select([one, two], CONFIG)["入口用ID"], "B")
        self.assertEqual(E.select([selection_row("B"), selection_row("A")], CONFIG)["入口用ID"], "A")

    def test_七十目標は間引き件数も必要(self) -> None:
        """主率が70%以上でも間引き不足を目標達成に数えない。

        引数: なし。
        返り値: None。
        """
        row = selection_row("A", .7, .7)
        self.assertEqual(E.select([deepcopy(row)], CONFIG)["70目標達成数"], 1)
        row["条件選択"]["入口"]["30分間引き_約定候補数"] -= 1
        self.assertEqual(E.select([row], CONFIG)["70目標達成数"], 0)

    def test_費用資格は両期正と買売支持と品質(self) -> None:
        """片期赤字、片方向不足、品質注意を費用候補から除く。

        引数: なし。
        返り値: None。
        """
        for key, value in (("追加5pt純損益円", 0), ("買い取引数", 0), ("品質注意場数", 1)):
            row = selection_row("A")
            row["条件選択"]["運用"][key] = value
            self.assertIsNone(E.select([row], CONFIG)["費用用ID"])

    def test_費用順位は低い平均から総額へ(self) -> None:
        """一期間だけの大勝ちより、低い期間の平均を優先する。

        引数: なし。
        返り値: None。
        """
        one, two = selection_row("A"), selection_row("B")
        one["学習"]["運用"]["追加5pt平均円"] = 1000
        one["条件選択"]["運用"]["追加5pt平均円"] = 40
        self.assertEqual(E.select([one, two], CONFIG)["費用用ID"], "B")
        one = selection_row("A")
        two["条件選択"]["運用"]["追加5pt純損益円"] += 100
        self.assertEqual(E.select([one, two], CONFIG)["費用用ID"], "B")

    def test_対照は順位選択から除外し固定IDは重複しない(self) -> None:
        """対照の好成績で入口を選ばず、同じ勝者を二回確認しない。

        引数: なし。
        返り値: None。
        """
        row = selection_row("A", .6, .6)
        control = selection_row(CONFIG["対照ID"], 1, 1)
        result = E.select([row, control], CONFIG)
        self.assertEqual(result["入口用ID"], "A")
        self.assertEqual(result["固定ID"], ["A", CONFIG["対照ID"]])

    def test_空の運用と観測注意は確定利益なし(self) -> None:
        """無取引の平均は未定義、注意付き経路の確定額も未定義にする。

        引数: なし。
        返り値: None。
        """
        empty = E.operation_metrics([], [])
        self.assertIsNone(empty["追加5pt平均円"])
        info = {"観測経路注意": True, "終了建玉": 1, "EOF期限未達": True, "場時間分": 60}
        value = E.operation_metrics([info], [])
        self.assertIsNone(value["追加0pt確定対象円"])
        self.assertEqual(value["未解消場数"], 1)


# ----------------------------------------
# 実ファイルを置かない未来側を、探索が開かないことを確認する。

class 期間実行検証(unittest.TestCase):
    """一時フォルダの空入力と差替え読取器だけで段階を検査する。"""

    def test_固定された一または二新候補と対照だけを返す(self) -> None:
        """二用途が同じ候補なら一回にまとめ、対照を含む固定候補だけ返す。

        引数: なし。
        返り値: None。
        """
        candidates = E.rules(CONFIG)
        first, second = candidates[0]["候補ID"], candidates[1]["候補ID"]
        for profit, expected in ((None, [first, CONFIG["対照ID"]]),
                                 (first, [first, CONFIG["対照ID"]]),
                                 (second, [first, second, CONFIG["対照ID"]])):
            selection = {"入口用ID": first, "費用用ID": profit, "固定ID": expected}
            locked = {"ファイルSHA256": {}, "探索結果SHA256": "正本", "選定": selection}
            with patch.object(E, "fixed_files", return_value={}), patch.object(E.O, "sha", return_value="正本"), \
                    patch.object(E.W, "read_json", return_value={"選定": deepcopy(selection)}):
                selected = E.validate_locked(Path("合成試行"), locked, CONFIG, candidates)
            self.assertEqual({r["候補ID"] for r in selected}, set(expected))

    def test_探索結果のSHAまたは選定変更を後続前に拒否(self) -> None:
        """固定後の探索結果不一致をキャッシュ読取の前段で拒否する。

        引数: なし。
        返り値: None。
        """
        candidates = E.rules(CONFIG)
        selection = {"入口用ID": candidates[0]["候補ID"], "費用用ID": None,
                     "固定ID": [candidates[0]["候補ID"], CONFIG["対照ID"]]}
        locked = {"ファイルSHA256": {}, "探索結果SHA256": "正本", "選定": selection}
        for digest, saved in (("別物", selection), ("正本", {**selection, "入口用ID": "別ID"})):
            with patch.object(E, "fixed_files", return_value={}), patch.object(E.O, "sha", return_value=digest), \
                    patch.object(E.W, "read_json", return_value={"選定": saved}), self.assertRaises(ValueError):
                E.validate_locked(Path("合成試行"), locked, CONFIG, candidates)

    def test_未知または空の固定候補と対照自身の選択を拒否(self) -> None:
        """空集合・未知候補・対照を入口用にした選定を通さない。

        引数: なし。
        返り値: None。
        """
        candidates = E.rules(CONFIG)
        first = candidates[0]["候補ID"]
        for selection in ({"入口用ID": first, "費用用ID": None, "固定ID": []},
                          {"入口用ID": "未知", "費用用ID": None, "固定ID": ["未知", CONFIG["対照ID"]]},
                          {"入口用ID": CONFIG["対照ID"], "費用用ID": None, "固定ID": [CONFIG["対照ID"]]}):
            locked = {"ファイルSHA256": {}, "探索結果SHA256": "正本", "選定": selection}
            with patch.object(E, "fixed_files", return_value={}), patch.object(E.O, "sha", return_value="正本"), \
                    patch.object(E.W, "read_json", return_value={"選定": deepcopy(selection)}), self.assertRaises(ValueError):
                E.validate_locked(Path("合成試行"), locked, CONFIG, candidates)

    def test_期間別入力数の不一致は読取前に拒否(self) -> None:
        """40・24・1場から外れた台帳をキャッシュ読取前に拒否する。

        引数: なし。
        返り値: None。
        """
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(E.W, "read_json", side_effect=[deepcopy(CONFIG), {"entries": []}]), \
                    patch.object(E.W.PREP, "read_events") as reads, self.assertRaises(ValueError):
                E.run(Path(directory), "探索")
            reads.assert_not_called()

    def test_探索は未来原板もキャッシュも開かない(self) -> None:
        """新1のsourceを存在させず、探索が旧64だけ読むことを確認する。

        引数: なし。
        返り値: None。
        """
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            study, work = base / "試行", base / "作業"
            study.mkdir()
            entries, current = [], date(2026, 9, 21)
            while current <= date(2026, 11, 3):
                if current.weekday() < 5:
                    for part in ("Day", "Night"):
                        session = f"{current.isoformat()}_{part}"
                        source = base / f"{session}.空入力"
                        source.touch()
                        stat = source.stat()
                        entries.append({"symbol": "NK225", "session": session, "source_path": source.name,
                            "cache_path": f"合成/{session}.npz", "source_size": stat.st_size, "source_mtime_ns": stat.st_mtime_ns,
                            "sha256_cache": "合成", "in_session_contract_codes": ["合成限月"]})
                current += timedelta(days=1)
            self.assertEqual(len(entries), 64)
            entries.append({"symbol": "NK225", "session": "2026-11-04_Day", "source_path": "未来は不存在",
                            "cache_path": "未来は読取禁止", "source_size": 0, "source_mtime_ns": 0,
                            "sha256_cache": "合成", "in_session_contract_codes": ["合成限月"]})
            manifest = {"source_root": str(base), "entries": entries}
            original = E.W.read_json

            def reader(path: Path) -> dict:
                """条件と合成台帳だけを返す。

                引数: path (Path) は読取要求。
                返り値: dict は設定または合成台帳。
                """
                return deepcopy(CONFIG) if path.name == "条件.json" else manifest if path.name == "入力台帳.json" else original(path)

            def events(path: Path):
                """旧空入力だけを受け付ける。

                引数: path (Path) は合成キャッシュ名。
                返り値: iterator は空列。未来要求は検証失敗。
                """
                self.assertNotIn("未来", str(path))
                return iter(())

            with patch.object(E, "WORK", work), patch.object(E.W, "read_json", side_effect=reader), \
                    patch.object(E.O, "sha", return_value="合成"), patch.object(E.W.PREP, "read_events", side_effect=events) as reads, \
                    patch.object(E, "fixed_files", return_value={}), patch.object(E, "publish_details"), patch("builtins.print"):
                result = E.run(study, "探索")
            self.assertEqual(reads.call_count, 64)
            self.assertEqual(result["候補数"], 33)
            self.assertFalse((base / "未来は不存在").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
