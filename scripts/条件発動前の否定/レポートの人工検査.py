"""68の否定・残存仮約定・保守分母を、正式入力なしで表示検査する。"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
R = None


def artificial_context(renderer) -> dict:
    """固定67の人工文脈だけを新しい否定比較へ写す。

    引数: renderer(ModuleType)は68表示器。
    返り値: dictは人工文脈。正式結果・モデル・教師は開かない。
    """
    spec = importlib.util.spec_from_file_location("否定68が参照する固定67人工", renderer.PREVIOUS.HERE / "レポートの人工検査.py")
    old_test = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = old_test
    spec.loader.exec_module(old_test)
    context = old_test.artificial_context(renderer.PREVIOUS)
    result = context["result"]
    for field in ("候補", "役割別入口", "判断理由"):
        old = result[field]
        result[field] = {p: deepcopy(old[c]) for p, c in (("G0", "G0"), ("G1", "G1"), ("N0", "G0"), ("N1", "G1"))}
    result.update(試行=68, 対照参照={"候補": ["G0", "G1"], "元試行": 67, "同じ評価46場": True, "市場再生": False})
    result["旧証明検査"] = deepcopy(result["検査"])
    result["検査"] = {"旧67純判断一致": 3404, "当時最新3分出典一致": 488, "同一条件実仮新規一致": 0}
    result["条件段階"], result["入口取得比較"], result["否定比較"] = {}, {}, {}
    for policy, control, count in (("N0", "G0", 433), ("N1", "G1", 55)):
        for field in ("条件段階", "入口取得比較", "否定比較"):
            result[field][policy] = {}
        for period in renderer.PERIODS:
            n = count if period == "条件選択" else 0
            outcomes = {"未発動": n - 5, "既超過": 1, "観測不足": 1, "発動未約定": 1, "設定否定": 1, "前提否定": 1} if n else {}
            result["候補"][policy][period]["入口"]["結果別"] = outcomes
            result["役割別入口"][policy][period]["順行"] = deepcopy(result["候補"][policy][period]["入口"])
            result["条件段階"][policy][period] = {"全予定枠": result["準備比較"][period]["全予定枠"], "純候補": n,
                "条件結果別": deepcopy(outcomes), "発動": 1 if n else 0, "仮約定": 0, "実条件登録": 0, "実新規": 0, "実登録未約定": 0}
            result["入口取得比較"][policy][period] = {"同じ純候補": n, "両約定": 0, "旧のみ約定": 0, "新のみ約定": 0,
                "結果対": {"未発動→未発動/未発動": n - 5, "未発動→設定否定/設定否定": 1, "未発動→前提否定/前提否定": 1,
                    "既超過→既超過/既超過": 1, "観測不足→観測不足/観測不足": 1, "発動未約定→発動未約定/発動未約定": 1} if n else {},
                "両約定の平均追随pt": None, "両約定の平均取得遅延秒": None}
            result["否定比較"][policy][period] = {"同じ純候補": n, "設定否定": 1 if n else 0, "前提否定": 1 if n else 0,
                "非否定の全属性一致": n - 2 if n else 0, "否定群の旧結果": {"未発動/未発動": 2} if n else {},
                "旧仮約定の除外": 0, "旧250の除外": 0, "旧125の除外": 0, "両約定の時刻価格結果一致": 0, "新のみ仮約定": 0}
    context["sources"] = [Path(renderer.__file__), Path(__file__)]
    return context


def virtual_outputs(context: dict) -> set[Path]:
    """人工の文書参照先だけを仮想出力として与える。

    引数: context(dict)は人工モデル参照を含む文脈。
    返り値: set[Path]は書き込まない正本・二文書・旧モデル参照。
    """
    paths = {R.STUDY / name for name in ("README.md", "設定と結果.md", "結果.json", "保存物確認.json", "検証計画.md", "条件.json", "一覧.resources.json")}
    for value in context["models"].values():
        paths.update((value["base_path"], value["path"]))
    return {p.resolve() for p in paths}


def add_registered_pair(context: dict) -> None:
    """旧二約定から一つを否定し、実登録未約定を旧新へ残す。

    引数: context(dict)は変更可能な人工文脈。
    返り値: None。純仮約定と実運用を別の保存集計として設定する。
    """
    result = context["result"]
    for policy, filled, wins, wait, pnl0 in (("G0", 2, 1, 885, -44), ("N0", 1, 0, 886, -22)):
        e, o = result["候補"][policy]["条件選択"]["入口"], result["候補"][policy]["条件選択"]["運用"]
        outcomes = {"125": 1, "未発動": 428, "既超過": 1, "観測不足": 1, "発動未約定": 1, "250": 1} if policy == "G0" else {
            "125": 1, "未発動": 427, "既超過": 1, "観測不足": 1, "発動未約定": 1, "設定否定": 1, "前提否定": 1}
        e.update(約定=filled, 結果別=outcomes, **{"250": wins}, 率=wins / filled,
            間引き約定=filled, 間引き250=wins, 間引き率=wins / filled, 日数=1, 場数=1)
        amounts = {str(f): pnl0 - 20 * f * filled for f in (0, 5, 10)}
        o.update(判断別={"待ち": wait, "条件登録": filled + 1}, 待ち数=wait, 条件登録数=filled + 1, 条件未約定=1, 完結数=filled,
            主待ち率=wait / 888, 待ち率保守上限=(wait + 1) / 888, 完結観測額円=amounts, 全体確定額円=deepcopy(amounts))
        result["役割別入口"][policy]["条件選択"]["順行"] = deepcopy(e)
        o["役割別完結"]["順行"].update(件数=filled, 観測純額5=amounts["5"])
    result["条件段階"]["N0"]["条件選択"].update(発動=2, 仮約定=1, 実条件登録=2, 実新規=1, 実登録未約定=1,
        条件結果別={"約定": 1, "未発動": 427, "既超過": 1, "観測不足": 1, "発動未約定": 1, "設定否定": 1, "前提否定": 1})
    result["入口取得比較"]["N0"]["条件選択"].update(両約定=1, 旧のみ約定=1,
        結果対={"125→約定/125": 1, "250→前提否定/前提否定": 1, "未発動→設定否定/設定否定": 1,
            "未発動→未発動/未発動": 427, "既超過→既超過/既超過": 1, "観測不足→観測不足/観測不足": 1, "発動未約定→発動未約定/発動未約定": 1},
        両約定の平均追随pt=0.0, 両約定の平均取得遅延秒=0.0)
    result["否定比較"]["N0"]["条件選択"].update(否定群の旧結果={"未発動/未発動": 1, "約定/250": 1},
        旧仮約定の除外=1, 旧250の除外=1, 両約定の時刻価格結果一致=1)


class RenderTests(unittest.TestCase):
    """否定比較・旧新の条件型・活動と品質nullを人工で検査する。"""

    def test_documents(self) -> None:
        """全文表と旧木・十項目・リンク・純表示の不変性を確認する。

        引数: self(RenderTests)は検査器。
        返り値: None。正式文書は書かない。
        """
        context = artificial_context(R)
        R.validate_result(context["result"])
        before = deepcopy(context)
        output = R.documents(context)
        self.assertEqual(output, R.documents(context))
        self.assertEqual(context, before)
        self.assertGreater(R.validate_documents(output, virtual_outputs(context)), 50)
        joined = output["README.md"] + output["設定と結果.md"]
        for value in ("旧67G0/G1", "新N0/N1", "新fit0", "Lastのstrict突破", "T+900", "設定否定", "前提否定", "発動後のentrypending・保有には新否定を適用しない"):
            self.assertIn(value, joined)
        for key in R.DENIAL_KEYS:
            self.assertIn(key, R.denial_table(context["result"]))
        self.assertNotIn("N0_W20.json", joined)
        self.assertNotIn("旧66の即時参加", joined)

    def test_registration_and_control_conservative_rate(self) -> None:
        """旧Gにも未約定を加え、仮約定と実占有を混同しない。

        引数: self(RenderTests)は検査器。
        返り値: None。
        """
        context = artificial_context(R)
        add_registered_pair(context)
        R.validate_result(context["result"])
        self.assertIn("旧250の除外", R.denial_table(context["result"]))
        for policy in ("G0", "N0"):
            bad = deepcopy(context)
            o = bad["result"]["候補"][policy]["条件選択"]["運用"]
            o["待ち率保守上限"] = o["主待ち率"]
            with self.assertRaises(ValueError):
                R.validate_result(bad["result"])

    def test_nonfill_partitions(self) -> None:
        """旧四種・新六種の全非約定を分母へ残す。

        引数: self(RenderTests)は検査器。
        返り値: None。
        """
        context = artificial_context(R)
        for policy, keys in (("G0", R.NONFILL), ("N0", R.NONFILL + ("設定否定", "前提否定"))):
            e = context["result"]["候補"][policy]["条件選択"]["入口"]
            self.assertTrue(all(e["結果別"][k] > 0 for k in keys))
        bad = deepcopy(context)
        old = bad["result"]["候補"]["G0"]["条件選択"]["入口"]["結果別"]
        old["設定否定"] = old.pop("既超過")
        with self.assertRaises(ValueError):
            R.validate_result(bad["result"])

    def test_denial_and_stage_guards(self) -> None:
        """否定十項目の不足・旧250除外・段階の誤結合を拒否する。

        引数: self(RenderTests)は検査器。
        返り値: None。
        """
        for field in R.DENIAL_KEYS:
            context = artificial_context(R)
            del context["result"]["否定比較"]["N0"]["条件選択"][field]
            with self.assertRaises(ValueError):
                R.validate_result(context["result"])
        for field in ("旧250の除外", "非否定の全属性一致", "新のみ仮約定"):
            context = artificial_context(R)
            add_registered_pair(context)
            context["result"]["否定比較"]["N0"]["条件選択"][field] += 1
            with self.assertRaises(ValueError):
                R.validate_result(context["result"])
        context = artificial_context(R)
        context["result"]["条件段階"]["N0"]["条件選択"]["仮約定"] += 1
        with self.assertRaises(ValueError):
            R.validate_result(context["result"])

    def test_no_fit_or_new_teacher(self) -> None:
        """新fit・新木・新独立計測と教師の時刻混同を拒否する。

        引数: self(RenderTests)は検査器。
        返り値: None。
        """
        for field in ("新回帰器fit", "新保存木数", "新独立計測"):
            context = artificial_context(R)
            context["result"][field] = 1
            with self.assertRaises(ValueError):
                R.validate_result(context["result"])
        context = artificial_context(R)
        context["result"]["学習参照"]["新条件入口を学習したか"] = True
        with self.assertRaises(ValueError):
            R.validate_result(context["result"])

    def test_null_rates_and_quality(self) -> None:
        """仮約定ゼロ率と品質注意の全体確定nullを0補完しない。

        引数: self(RenderTests)は検査器。
        返り値: None。
        """
        context = artificial_context(R)
        self.assertIn("対象なし（分母0）", R.documents(context)["README.md"])
        o = context["result"]["候補"]["N0"]["学習"]["運用"]
        o["品質注意場"] = ["架空の観測不足場"]
        o["全体確定額円"] = {"0": None, "5": None, "10": None}
        R.validate_result(context["result"])
        self.assertIn("null（品質注意）", R.main_tables(context["result"])[1])
        o["全体確定額円"]["5"] = 0
        with self.assertRaises(ValueError):
            R.validate_result(context["result"])

    def test_retained_entry_means(self) -> None:
        """残存仮約定の取得差0と対象なしnullを区別する。

        引数: self(RenderTests)は検査器。
        返り値: None。
        """
        for field in ("両約定の平均追随pt", "両約定の平均取得遅延秒"):
            context = artificial_context(R)
            context["result"]["入口取得比較"]["N0"]["条件選択"][field] = 0.0
            with self.assertRaises(ValueError):
                R.validate_result(context["result"])
            context = artificial_context(R)
            add_registered_pair(context)
            context["result"]["入口取得比較"]["N0"]["条件選択"][field] = 1.0
            with self.assertRaises(ValueError):
                R.validate_result(context["result"])


def run(renderer) -> dict:
    """表示器を注入して成功と人工件数を返す。

    引数: renderer(ModuleType)は68表示器。
    返り値: dictは正式人工レコーダー用。実入力・fit・市場0。
    """
    global R
    R = renderer
    outcome = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RenderTests))
    if not outcome.wasSuccessful():
        raise SystemExit(1)
    return {"成功": True, "テスト件数": outcome.testsRun, "実入力読取": False, "fit": 0, "市場再生": False}


if __name__ == "__main__":
    spec = importlib.util.spec_from_file_location("反対端否定68の人工用表示器", HERE / "レポート.py")
    renderer = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = renderer
    spec.loader.exec_module(renderer)
    print(json.dumps(run(renderer), ensure_ascii=False))
