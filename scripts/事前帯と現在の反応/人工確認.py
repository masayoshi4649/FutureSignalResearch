"""市場を読まず、帯・状態機械・独立監査・描画の人工確認を統合する。"""

import argparse
import ast
from copy import deepcopy
import json
from pathlib import Path

import importlib.util
import sys


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00075_事前帯の外保持と内回帰を判別"


def load(path: Path, name: str):
    """人工対象を固有名で読み、CLI処理を起動しない。

    引数: path(Path)はコード、name(str)は読込名。
    返り値: ModuleTypeは読込結果。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# ----------------------------------------
# 新しい接続に固有の人工を実行する。

def integration(main) -> dict:
    """当場の未来全帯を候補へ渡さない接続と、空集計のnullを検査する。

    引数: main(ModuleType)は75の主。市場関数は呼び出さない。
    返り値: dictは人工成功と照合数。
    """
    checks = 0

    def equal(actual: object, expected: object) -> None:
        """手で定めた接続契約と実値を比較する。

        引数: actual/expected(object)は比較値。
        返り値: None。不一致は停止する。
        """
        nonlocal checks
        checks += 1
        assert actual == expected, (actual, expected)

    previous, current = "2026-10-01_Night", "2026-10-02_Day"
    bank = {"previous": {current: {"ready": True, "prior_session": previous, "gap_seconds": 123.}},
        "opening": {current: {"high": 200., "low": 100., "ready": True}},
        "full": {previous: {"high": 150., "low": 50., "ready": True}, current: {"未来": "当場全高安は候補へ渡さない"}}}
    original = deepcopy(bank)
    prior = main.reference_for("P0", current, bank)
    equal((prior["session"], prior["high"], prior["low"], prior["reference_available"]), (previous, 150., 50., True))
    equal("未来" in prior, False)
    other = main.reference_for("P1", current, bank)
    equal(prior, other)
    opening = main.reference_for("O0", current, bank)
    equal((opening["session"], opening["high"], opening["reference_type"]), (current, 200., "OR30"))
    prior["high"] = -999.
    equal(bank, original)
    tests = 3
    bank["previous"][current].update(ready=False, reason="前収録なし")
    absent = main.reference_for("P0", current, bank)
    equal((absent["ready"], absent["published"], absent["reference_available"]), (False, False, False))
    equal([absent[k] for k in ("begin", "end", "publication_key", "open", "high", "low", "close")], [None] * 7)
    equal(absent["reason"], "前収録なし")
    tests += 1
    empty = {p: [] for p in main.ALL_POLICIES}
    summary = main.summarize(deepcopy(empty), deepcopy(empty), deepcopy(empty), {})
    equal(set(summary["候補"]), set(main.ALL_POLICIES))
    for p in main.ALL_POLICIES:
        for period in main.PERIODS:
            item = summary["候補"][p][period]
            equal((item["入口"]["約定"], item["入口"]["率"], item["入口"]["間引き率"]), (0, None, None))
            equal((item["運用"]["完結数"], item["運用"]["主待ち率"], item["運用"]["活動適格"], item["同時適格"]), (0, None, False, False))
    tests += 1
    return {"成功": True, "テスト件数": tests, "照合項目数": checks, "不一致数": 0, "本物入力読取": False}


# ----------------------------------------
# 各純実装の人工結果と現コードの指紋を結ぶ。

def run(check_only: bool = False) -> None:
    """純人工群を実行し、対象コード指紋と小型証明を保存又は照合する。

    引数: check_only(bool)は既存証明と同じコード/人工結果かの照合。
    返り値: None。本物価格・先着・回収・場内再生は起動しない。
    """
    main = load(HERE / "検証.py", "事前帯75人工の主接続")
    modules = {name: load(HERE / (name + ".py"), "事前帯75人工" + name)
        for name in ("参照帯", "入力", "入力監査", "レポート", "保存検証")}
    results = {name: module.self_test() for name, module in modules.items()}
    results["主接続"] = integration(main)
    for name, value in results.items():
        if not value["成功"] or value.get("不一致数", 0):
            raise ValueError("人工失敗:" + name)
    pins, functions = {}, 0
    for path in HERE.glob("*.py"):
        pins[path.relative_to(ROOT).as_posix()] = main.C.sha(path)
        parsed = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(parsed):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions += 1
                comment = ast.get_docstring(node)
                if not comment or "引数" not in comment or "返り値" not in comment or "\n" not in comment or "戻り値" in comment:
                    raise ValueError("関数コメントの不足:" + path.name + ":" + node.name)
    value = {"試行": 75, "成功": True, "不一致数": 0, "群": results, "関数コメント確認": functions,
        "テスト件数": sum(r["テスト件数"] for r in results.values()),
        "照合項目数": sum(r["照合項目数"] for r in results.values()), "コードSHA256": pins,
        "本物入力読取": False, "市場再生": False, "新fit": 0, "新測定": 0}
    destination = STUDY / "人工確認.json"
    if check_only:
        if main.C.read_json(destination) != value:
            raise ValueError("人工証明と現コード/結果の差")
    else:
        if destination.exists():
            raise FileExistsError("75人工正本は保存済み")
        main.C.write_json(destination, value)
    print(json.dumps({"人工確認": True, "テスト件数": value["テスト件数"], "照合項目数": value["照合項目数"], "関数": functions}, ensure_ascii=False), flush=True)


def main() -> None:
    """人工証明の作成又は既存証明の確認を行う。

    引数: CLIの--check(bool)は既存証明の確認。
    返り値: None。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    run(parser.parse_args().check)


if __name__ == "__main__":
    main()
