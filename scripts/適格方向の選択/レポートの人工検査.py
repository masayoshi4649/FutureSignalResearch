"""66の参照表示と適格集合の説明を、本物入力なしで人工検査する。"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
R = None


def artificial_context(renderer) -> dict:
    """旧65人工文脈だけを、旧U参照・新E選択の契約へ写す。

    引数: renderer(ModuleType)は66表示器。
    返り値: dictは人工文脈。正式入力・教師・モデルを読まない。
    """
    spec = importlib.util.spec_from_file_location("適格選択66が参照する固定65人工", renderer.BASE.HERE / "レポートの人工検査.py")
    old_test = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = old_test
    spec.loader.exec_module(old_test)
    c = old_test.artificial_context(renderer.BASE)
    result = c["result"]
    mapping = {"Q0": "U0", "Q1": "U1", "U0": "E0", "U1": "E1"}
    for field in ("候補", "役割別入口", "判断理由"):
        result[field] = {mapping[p]: v for p, v in result[field].items()}
    result.update(試行=66, 新回帰器fit=0, 新保存木数=0, 参照モデル数=3,
        学習参照=deepcopy(renderer.REFERENCE), 対照参照={"候補": ["U0", "U1"], "元試行": 65, "同じ評価46場": True, "市場再生": False})
    result["旧証明検査"] = deepcopy(result["検査"])
    result["検査"] = {"旧65特徴保存一致": 3404, "旧65純判断一致": 3404, "同一新規完結一致": 0}
    result["選択比較"] = {}
    for policy, control in zip(renderer.NEW, ("U0", "U1")):
        result["選択比較"][policy] = {t: {"全予定枠": result["準備比較"][t]["全予定枠"], "特徴準備枠": 0,
            "旧純採用": 0, "新純採用": 0, "共通同方向": 0, "追加純候補": 0, "除外純候補": 0, "反対変更": 0,
            "追加時旧理由": {}, "予測救済": 0, "DI同値で拒否": 0} for t in renderer.PERIODS}
    result["新候補方向差"] = {t: {"全予定枠": result["準備比較"][t]["全予定枠"],
        "両採用同方向": 0, "両採用逆方向": 0, "E0のみ採用": 0, "E1のみ採用": 0} for t in renderer.PERIODS}
    # ----------------------------------------
    # 新木ではなく旧モデルの人工pathを維持し、表示リンクだけ旧65へ置く。
    for phase, item in c["models"].items():
        item["base_path"] = renderer.OLD / "models" / ("U0_" + phase + ".json")
        item["path"] = renderer.OLD / "models" / ("回収_U0_" + phase + ".json")
    c["sources"] = [Path(renderer.__file__).resolve(), Path(__file__).resolve()]
    return c


def virtual_outputs(context: dict) -> set[Path]:
    """正式二MDを書かず、人工だけの参照先を明示する。

    引数: context(dict)は人工文脈。
    返り値: set[Path]は新二MD・正本と旧参照モデル/calの仮想先。
    """
    paths = {R.STUDY / n for n in ("README.md", "設定と結果.md", "結果.json", "保存物確認.json", "検証計画.md", "条件.json", "一覧.resources.json")}
    for item in context["models"].values():
        paths.update((item["base_path"], item["path"]))
    return {p.resolve() for p in paths}


def add_opposite_pair(context: dict) -> None:
    """E0/E1が逆方向を選ぶ人工件数だけを保存表示へ加える。

    引数: context(dict)は変更可能な人工文脈。
    返り値: None。実予測は呼ばず、候補・比較の分母だけを揃える。
    """
    result = context["result"]
    for policy in ("E0", "E1"):
        e = result["候補"][policy]["条件選択"]["入口"]
        e.update(候補=1, 約定=1, 結果別={"125": 1}, 率=0.0, 間引き約定=1, 間引き率=0.0, 日数=1, 場数=1)
        result["役割別入口"][policy]["条件選択"]["順行"] = deepcopy(e)
        result["選択比較"][policy]["条件選択"].update(特徴準備枠=1, 新純採用=1, 追加純候補=1,
            追加時旧理由={"過去回収支持不足WAIT": 1}, 予測救済=1)
    result["新候補方向差"]["条件選択"]["両採用逆方向"] = 1


class RenderTests(unittest.TestCase):
    """新fit0・参照木・方向非包含・欠測表示を人工で確認する。"""

    def test_documents(self) -> None:
        """同60/55×9・全参照node・リンク・同byteと非変更を検査する。

        引数: なし。
        返り値: None。正式出力は作らない。
        """
        c = artificial_context(R)
        R.validate_result(c["result"])
        before = deepcopy(c)
        a, b = R.documents(c), R.documents(c)
        self.assertEqual(a, b)
        self.assertEqual(c, before)
        self.assertGreater(R.validate_documents(a, virtual_outputs(c)), 50)
        for phrase in ("新fit0", "新木0", "参照する旧65三木", "片側未知", "E1はE0と逆側", "184資源"):
            self.assertIn(phrase, a["README.md"] + a["設定と結果.md"])
        self.assertNotIn("回帰fitは最大12", a["設定と結果.md"])
        self.assertNotIn("E0_W20.json", a["設定と結果.md"])
        self.assertNotIn("次点で救済しない", R.reference_tables(c, R.STUDY / "設定と結果.md"))
        self.assertNotIn("最高障壁score側を先に選び、支持/技法/回収で不適格でも次点へ救済しない", a["設定と結果.md"])

    def test_opposite_not_subset(self) -> None:
        """E1のE0反対選択を正常な表示として受け入れ、分母を検査する。

        引数: なし。
        返り値: None。
        """
        c = artificial_context(R)
        add_opposite_pair(c)
        R.validate_result(c["result"])
        self.assertIn("両逆方向", R.selection_table(c["result"]))
        c["result"]["新候補方向差"]["条件選択"]["両採用逆方向"] = 0
        with self.assertRaises(ValueError):
            R.validate_selection(c["result"])

    def test_no_new_fit_or_tree(self) -> None:
        """新fit・新保存木・参照数の変造を拒否する。

        引数: なし。
        返り値: None。
        """
        for key, value in (("新回帰器fit", 1), ("新保存木数", 3), ("参照モデル数", 0)):
            c = artificial_context(R)
            c["result"][key] = value
            with self.assertRaises(ValueError):
                R.validate_result(c["result"])

    def test_reference_and_old_proof(self) -> None:
        """再学習・教師再生成を許さず旧証明を新実施と分ける。

        引数: なし。
        返り値: None。
        """
        c = artificial_context(R)
        self.assertEqual(len(c["result"]["検査"]), 3)
        c["result"]["学習参照"]["教師再生成"] = True
        with self.assertRaises(ValueError):
            R.validate_result(c["result"])

    def test_null_and_cost_quality(self) -> None:
        """無取引先着nullと品質注意の全体確定nullを維持する。

        引数: なし。
        返り値: None。
        """
        c = artificial_context(R)
        self.assertIn("対象なし（分母0）", R.documents(c)["README.md"])
        c["result"]["候補"]["U0"]["学習"]["運用"]["全体確定額円"]["5"] = 0
        with self.assertRaises(ValueError):
            R.validate_result(c["result"])

    def test_selection_counts_and_old_reason(self) -> None:
        """救済と純追加を同一視せず、追加時の旧理由の欠落を拒否する。

        引数: なし。
        返り値: None。
        """
        c = artificial_context(R)
        add_opposite_pair(c)
        c["result"]["選択比較"]["E0"]["条件選択"]["予測救済"] = 2
        c["result"]["選択比較"]["E0"]["条件選択"]["DI同値で拒否"] = 1
        R.validate_selection(c["result"])
        c["result"]["選択比較"]["E0"]["条件選択"]["追加時旧理由"] = {}
        with self.assertRaises(ValueError):
            R.validate_selection(c["result"])


def run(renderer) -> dict:
    """表示器を注入し、人工の件数と成功を返す。

    引数: renderer(ModuleType)は66表示器。
    返り値: dictは人工記録。実入力・fit・市場再生0、失敗時終了1。
    """
    global R
    R = renderer
    outcome = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RenderTests))
    if not outcome.wasSuccessful():
        raise SystemExit(1)
    return {"成功": True, "テスト件数": outcome.testsRun, "実入力読取": False, "fit": 0, "市場再生": False}


if __name__ == "__main__":
    spec = importlib.util.spec_from_file_location("適格選択66人工用表示器", HERE / "レポート.py")
    renderer = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = renderer
    spec.loader.exec_module(renderer)
    print(json.dumps(run(renderer), ensure_ascii=False))
