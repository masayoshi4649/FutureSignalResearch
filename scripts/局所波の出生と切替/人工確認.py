"""不変の入力人工を継承し、76の運用接続・監査・描画を追加確認する。"""

import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00076_局所波の押戻しと起点喪失を分ける"


def sha(path: Path) -> str:
    """現実装又は既存人工証拠の内容指紋を得る。

    引数: path(Path)は保存ファイル。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path, name: str):
    """新しい追加人工の対象を固有名で読む。

    引数: path(Path)はPython、name(str)は読込名。
    返り値: ModuleTypeは結果。CLIを起動しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


# ----------------------------------------
# 同じ入力人工は再実行せず、成功証明と全コードSHAへ結ぶ。

def run(check_only: bool = False) -> dict:
    """運用前の追加人工と継承入力証拠を新規保存又は照合する。

    引数: check_only(bool)は保存済み人工との一致確認。
    返り値: dictは成功・範囲・件数・コード指紋。市場や本物ラベルを読まない。
    """
    path = STUDY / "入力人工確認.json"
    original = json.loads(path.read_text(encoding="utf-8"))
    if not original["成功"] or original["不一致数"]:
        raise ValueError("76の入力人工が未成功")
    for relative, digest in original["コードSHA256"].items():
        if sha(ROOT / relative) != digest:
            raise ValueError("76の入力人工後にコード変更:" + relative)
    groups = {}
    for name in ("検証", "保存検証", "レポート"):
        target = HERE / (name + ".py")
        before = sha(target)
        value = load(target, "局所波76の追加人工" + name).self_test()
        if not value["成功"] or value["不一致数"] or sha(target) != before:
            raise ValueError("76追加人工の未成功又は実行中変更:" + name)
        groups[name] = value
    pins, functions = {}, 0
    for target in HERE.glob("*.py"):
        pins[target.relative_to(ROOT).as_posix()] = sha(target)
        for node in ast.walk(ast.parse(target.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions += 1
                text = ast.get_docstring(node)
                if not text or any(word not in text for word in ("引数", "返り値", "\n")) or "戻り値" in text:
                    raise ValueError("76の関数コメント不足:" + target.name + ":" + node.name)
    value = {"試行": 76, "成功": True, "不一致数": 0,
        "継承入力人工": {"SHA256": sha(path), "テスト件数": original["テスト件数"], "照合項目数": original["照合項目数"], "本巡再実行": False},
        "追加人工": groups, "テスト件数": original["テスト件数"] + sum(g["テスト件数"] for g in groups.values()),
        "照合項目数": original["照合項目数"] + sum(g["照合項目数"] for g in groups.values()),
        "関数コメント確認": functions, "コードSHA256": pins, "新fit": 0, "新本物運用": 0}
    destination = STUDY / "人工確認.json"
    if check_only:
        if json.loads(destination.read_text(encoding="utf-8")) != value:
            raise ValueError("76人工正本と現在実装の差")
    else:
        with destination.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    return value


def main() -> None:
    """追加人工の初回保存又は既存証明の確認を行う。

    引数: CLIの--check(bool)は保存済み証明との一致確認。
    返り値: None。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    value = run(parser.parse_args().check)
    print(json.dumps({key: value[key] for key in ("成功", "テスト件数", "照合項目数", "不一致数", "関数コメント確認")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
