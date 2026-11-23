"""77の新コードだけを人工確認し、価格実行前の証拠へ結ぶ。"""

import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00077_押戻し再開の確認を早める"


def sha(path: Path) -> str:
    """コードや保存証拠の内容指紋を求める。

    引数: path(Path)は既存ファイル。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect_functions(paths: list[Path]) -> int:
    """構文と全関数の日本語複数行コメントを確認する。

    引数: paths(list[Path])は新Pythonコード。
    返り値: intは確認した関数数。
    """
    count = 0
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            doc = ast.get_docstring(node)
            if not doc or "\n" not in doc or "引数:" not in doc or "返り値:" not in doc:
                raise ValueError("関数コメント不足:" + path.name + ":" + node.name)
            count += 1
    return count


def execute(name: str) -> dict:
    """本物入力を開かないself_testだけを新固有名で実行する。

    引数: name(str)はコードbasename。
    返り値: dictは成功人工結果。
    """
    spec = importlib.util.spec_from_file_location("確認幅77人工" + name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    value = module.self_test()
    if value["成功"] is not True or value["不一致数"] != 0:
        raise ValueError("人工確認の不成功:" + name)
    return value


def save(input_only: bool) -> dict:
    """新入力か運用接続の人工証明を排他的に保存する。

    引数: input_only(bool)は入力2本だけの段階か。
    返り値: dictは保存証明。入力人工は本段階で再実行せず継承する。
    """
    destination = STUDY / ("入力人工確認.json" if input_only else "人工確認.json")
    if destination.exists():
        raise FileExistsError("77人工証明は保存済み")
    inherited = None
    if input_only:
        groups = {name: execute(name) for name in ("入力", "入力監査")}
        paths = [HERE / (name + ".py") for name in ("入力", "入力監査", "人工確認")]
    else:
        path = STUDY / "入力人工確認.json"
        inherited = json.loads(path.read_text(encoding="utf-8"))
        if inherited["成功"] is not True or inherited["不一致数"] != 0:
            raise ValueError("入力人工未成功")
        for relative, digest in inherited["コードSHA256"].items():
            if sha(ROOT / relative) != digest:
                raise ValueError("入力人工後のコード差:" + relative)
        groups = {name: execute(name) for name in ("検証", "保存検証", "レポート")}
        paths = list(HERE.glob("*.py"))
    count = inspect_functions(paths)
    value = {"試行": 77, "成功": True, "不一致数": 0, "群": groups,
        "テスト件数": sum(g["テスト件数"] for g in groups.values()),
        "照合項目数": sum(g["照合項目数"] for g in groups.values()), "関数コメント確認": count,
        "コードSHA256": {p.relative_to(ROOT).as_posix(): sha(p) for p in paths},
        "本物入力読取": False, "市場戦略再生": False, "新fit": 0, "新独立測定": 0}
    if inherited is not None:
        value["継承入力人工"] = {"SHA256": sha(STUDY / "入力人工確認.json"),
            "テスト件数": inherited["テスト件数"], "照合項目数": inherited["照合項目数"], "本巡再実行": False}
        value["テスト件数"] += inherited["テスト件数"]
        value["照合項目数"] += inherited["照合項目数"]
    with destination.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    return value


def main() -> None:
    """人工確認の保存か既存証明の指紋確認を選ぶ。

    引数: CLIの--input(bool)は入力段階、--check(bool)は全段階証明の確認。
    返り値: None。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--input", action="store_true")
    group.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        value = json.loads((STUDY / "人工確認.json").read_text(encoding="utf-8"))
        for relative, digest in value["コードSHA256"].items():
            if sha(ROOT / relative) != digest:
                raise ValueError("全人工後のコード差:" + relative)
    else:
        value = save(args.input)
    print(json.dumps({k: value[k] for k in ("成功", "テスト件数", "照合項目数", "不一致数", "関数コメント確認")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
