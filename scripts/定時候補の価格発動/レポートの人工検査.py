"""67の条件段階と表示を、正式入力なしの人工辞書で検査する。"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
R = None


def artificial_context(renderer) -> dict:
    """固定66の人工文脈を、新しい条件表示の件数へ写す。

    引数: renderer(ModuleType)は67表示器。
    返り値: dictは人工文脈。正式結果・モデル・教師は開かない。
    """
    spec = importlib.util.spec_from_file_location("条件67が参照する固定66人工", renderer.PREVIOUS.HERE / "レポートの人工検査.py")
    old_test = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = old_test
    spec.loader.exec_module(old_test)
    context = old_test.artificial_context(renderer.PREVIOUS)
    result = context["result"]
    mapping = {"U0": "E0", "U1": "E1", "E0": "G0", "E1": "G1"}
    for field in ("候補", "役割別入口", "判断理由"):
        result[field] = {mapping[p]: v for p, v in result[field].items()}
    result.update(試行=67, 新条件入口評価=488,
        学習参照={**renderer.PREVIOUS.REFERENCE, "旧即時入口の教師": True, "新条件入口を学習したか": False},
        対照参照={"候補": ["E0", "E1"], "元試行": 66, "同じ評価46場": True, "市場再生": False})
    result["旧証明検査"] = deepcopy(result["検査"])
    result["検査"] = {"旧66純判断一致": 3404, "当時最新3分出典一致": 488, "同一条件実仮新規一致": 0}
    result["条件段階"], result["入口取得比較"] = {}, {}
    for policy, control, count in (("G0", "E0", 433), ("G1", "E1", 55)):
        result["条件段階"][policy], result["入口取得比較"][policy] = {}, {}
        for period in renderer.PERIODS:
            n = count if period == "条件選択" else 0
            for p in (policy, control):
                e = result["候補"][p][period]["入口"]
                e.update(候補=n, 結果別={"未約定": n} if n else {})
                if p == policy and n:
                    e["結果別"] = {"未発動": n - 3, "既超過": 1, "観測不足": 1, "発動未約定": 1}
                result["役割別入口"][p][period]["順行"] = deepcopy(e)
            result["候補"][policy][period]["運用"].update(条件登録数=0, 条件未約定=0)
            result["条件段階"][policy][period] = {"全予定枠": result["準備比較"][period]["全予定枠"], "純候補": n,
                "条件結果別": {"未発動": n - 3, "既超過": 1, "観測不足": 1, "発動未約定": 1} if n else {}, "発動": 1 if n else 0, "仮約定": 0, "実条件登録": 0, "実新規": 0, "実登録未約定": 0}
            result["入口取得比較"][policy][period] = {"同じ純候補": n, "両約定": 0, "旧のみ約定": 0, "新のみ約定": 0,
                "結果対": {"未約定→未発動/未発動": n - 3, "未約定→既超過/既超過": 1, "未約定→観測不足/観測不足": 1, "未約定→発動未約定/発動未約定": 1} if n else {}, "両約定の平均追随pt": None, "両約定の平均取得遅延秒": None}
    context["sources"] = [Path(renderer.__file__), Path(__file__)]
    return context


def virtual_outputs(context: dict) -> set[Path]:
    """人工の参照先だけを仮想出力として与える。

    引数: context(dict)は人工モデル参照を含む文脈。
    返り値: set[Path]は書き込まない二MD・正本・旧モデル参照。
    """
    paths = {R.STUDY / name for name in ("README.md", "設定と結果.md", "結果.json", "保存物確認.json", "検証計画.md", "条件.json", "一覧.resources.json")}
    for value in context["models"].values():
        paths.update((value["base_path"], value["path"]))
    return {p.resolve() for p in paths}


def add_registered_pair(context: dict) -> None:
    """二登録のうち一新規・一未約定となる人工段階を作る。

    引数: context(dict)は変更可能な人工文脈。
    返り値: None。実運用や先着を呼ばず保存集計を整合させる。
    """
    result = context["result"]
    e, o = result["候補"]["G0"]["条件選択"]["入口"], result["候補"]["G0"]["条件選択"]["運用"]
    e.update(約定=1, 結果別={"125": 1, "未発動": 429, "既超過": 1, "観測不足": 1, "発動未約定": 1}, 率=0.0, 間引き約定=1, 間引き率=0.0, 日数=1, 場数=1)
    o.update(判断別={"待ち": 886, "条件登録": 2}, 待ち数=886, 条件登録数=2, 条件未約定=1, 完結数=1,
        主待ち率=886 / 888, 待ち率保守上限=887 / 888,
        完結観測額円={"0": -22, "5": -122, "10": -222}, 全体確定額円={"0": -22, "5": -122, "10": -222})
    result["役割別入口"]["G0"]["条件選択"]["順行"] = deepcopy(e)
    o["役割別完結"]["順行"].update(件数=1, 観測純額5=-122)
    result["条件段階"]["G0"]["条件選択"].update(発動=2, 仮約定=1, 実条件登録=2, 実新規=1, 実登録未約定=1)
    result["条件段階"]["G0"]["条件選択"]["条件結果別"] = {"約定": 1, "未発動": 429, "既超過": 1, "観測不足": 1, "発動未約定": 1}
    result["入口取得比較"]["G0"]["条件選択"].update(新のみ約定=1, 結果対={"未約定→約定/125": 1, "未約定→未発動/未発動": 429, "未約定→既超過/既超過": 1, "未約定→観測不足/観測不足": 1, "未約定→発動未約定/発動未約定": 1})


class RenderTests(unittest.TestCase):
    """同じ候補・発動差・活動と品質nullの表示を人工で検査する。"""

    def test_documents(self) -> None:
        """全60・55×9・全旧node・リンクと純表示の非変更を確認する。

        引数: self(RenderTests)は検査器。
        返り値: None。正式MDを書かない。
        """
        context = artificial_context(R)
        R.validate_result(context["result"])
        before = deepcopy(context)
        first, second = R.documents(context), R.documents(context)
        self.assertEqual(first, second)
        self.assertEqual(context, before)
        self.assertGreater(R.validate_documents(first, virtual_outputs(context)), 50)
        for key in ("未発動", "既超過", "観測不足", "発動未約定"):
            self.assertGreater(context["result"]["候補"]["G0"]["条件選択"]["入口"]["結果別"][key], 0)
        for text in ("旧66E0/E1", "新G0/G1", "新fit0", "Lastのstrict突破", "T+900", "同じ候補の入口取得比較", "条件入口先着は新しい要求・入口で計算"):
            self.assertTrue(text in first["README.md"] + first["設定と結果.md"], text)
        self.assertNotIn("G0_W20.json", first["設定と結果.md"])
        self.assertNotIn("66の新fit・新測定結果", first["設定と結果.md"])

    def test_registration_is_not_entry(self) -> None:
        """二登録・一entry・一未約定の保守分母を表示する。

        引数: self(RenderTests)は検査器。
        返り値: None。
        """
        context = artificial_context(R)
        add_registered_pair(context)
        R.validate_result(context["result"])
        self.assertIn("実登録未約定", R.stage_table(context["result"]))
        self.assertIn("新のみ約定", R.comparison_table(context["result"]))
        context["result"]["候補"]["G0"]["条件選択"]["運用"]["待ち率保守上限"] = 886 / 888
        with self.assertRaises(ValueError):
            R.validate_result(context["result"])

    def test_stage_missing_or_mismatch(self) -> None:
        """段階の不足・候補削除・約定取り違えを拒否する。

        引数: self(RenderTests)は検査器。
        返り値: None。
        """
        for key in ("純候補", "仮約定", "実条件登録"):
            context = artificial_context(R)
            context["result"]["条件段階"]["G0"]["条件選択"][key] += 1
            with self.assertRaises(ValueError):
                R.validate_result(context["result"])
        context = artificial_context(R)
        del context["result"]["条件段階"]["G0"]["条件選択"]["発動"]
        with self.assertRaises(ValueError):
            R.validate_result(context["result"])

    def test_no_fit_or_new_teacher(self) -> None:
        """新fit・新木・旧即時教師の新時刻評価への混同を拒否する。

        引数: self(RenderTests)は検査器。
        返り値: None。
        """
        for key in ("新回帰器fit", "新保存木数", "新独立計測"):
            context = artificial_context(R)
            context["result"][key] = 1
            with self.assertRaises(ValueError):
                R.validate_result(context["result"])
        context = artificial_context(R)
        context["result"]["学習参照"]["新条件入口を学習したか"] = True
        with self.assertRaises(ValueError):
            R.validate_result(context["result"])

    def test_null_rates_and_quality(self) -> None:
        """未発動の率nullと品質注意の全体確定nullを区別する。

        引数: self(RenderTests)は検査器。
        返り値: None。
        """
        context = artificial_context(R)
        self.assertIn("対象なし（分母0）", R.documents(context)["README.md"])
        o = context["result"]["候補"]["G0"]["学習"]["運用"]
        o["品質注意場"] = ["架空の観測不足場"]
        o["全体確定額円"] = {"0": None, "5": None, "10": None}
        R.validate_result(context["result"])
        self.assertIn("null（品質注意）", R.main_tables(context["result"])[1])
        o["全体確定額円"]["5"] = 0
        with self.assertRaises(ValueError):
            R.validate_result(context["result"])

    def test_comparison_denominator(self) -> None:
        """両約定だけの平均を全候補へ転用する誤りを拒否する。

        引数: self(RenderTests)は検査器。
        返り値: None。
        """
        context = artificial_context(R)
        context["result"]["入口取得比較"]["G0"]["条件選択"]["両約定の平均追随pt"] = 0.0
        with self.assertRaises(ValueError):
            R.validate_result(context["result"])
        context = artificial_context(R)
        context["result"]["入口取得比較"]["G0"]["条件選択"]["同じ純候補"] -= 1
        with self.assertRaises(ValueError):
            R.validate_result(context["result"])


def run(renderer) -> dict:
    """表示器を注入して人工の成功と件数を返す。

    引数: renderer(ModuleType)は67表示器。
    返り値: dictは正式人工レコーダー用。実入力・fit・市場0。
    """
    global R
    R = renderer
    outcome = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RenderTests))
    if not outcome.wasSuccessful():
        raise SystemExit(1)
    return {"成功": True, "テスト件数": outcome.testsRun, "実入力読取": False, "fit": 0, "市場再生": False}


if __name__ == "__main__":
    spec = importlib.util.spec_from_file_location("条件発動67の人工用表示器", HERE / "レポート.py")
    renderer = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = renderer
    spec.loader.exec_module(renderer)
    print(json.dumps(run(renderer), ensure_ascii=False))
