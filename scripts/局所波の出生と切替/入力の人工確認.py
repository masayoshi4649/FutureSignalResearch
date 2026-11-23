"""出生ATRと親局所波の純人工を、本物入力の構成前に確認する。"""

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


def module(path: Path, name: str):
    """純人工の対象を固有名で読む。

    引数: path(Path)はファイル、name(str)は読込名。
    返り値: ModuleTypeは結果。CLIは起動しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


def sha(path: Path) -> str:
    """確認する実装のbyte指紋を得る。

    引数: path(Path)は保存コード。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ----------------------------------------
# 本物SOURCEを開かず、人工とソースの関数コメントを確認する。

def check(check_only: bool = False) -> dict:
    """4つの純実装の人工結果とコード指紋を新規保存又は照合する。

    引数: check_only(bool)は既存記録との一致確認。
    返り値: dictは成功、群、照合、指紋。本物価格・ラベル・損益は読まない。
    """
    names = ("出生ATR", "出生ATR監査", "入力", "入力監査")
    groups, pins, count = {}, {}, 0
    for name in names:
        path = HERE / (name + ".py")
        before = sha(path)
        current = module(path, "局所波76入力人工" + name)
        result = current.self_test()
        if not result["成功"] or result["不一致数"] or before != sha(path):
            raise ValueError("76の入力人工未成功又は実行中変更:" + name)
        groups[name] = result
        pins[path.relative_to(ROOT).as_posix()] = before
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                count += 1
                text = ast.get_docstring(node)
                if not text or any(word not in text for word in ("引数", "返り値", "\n")) or "戻り値" in text:
                    raise ValueError("76入力の関数コメント不足:" + name + ":" + node.name)
    pins[Path(__file__).relative_to(ROOT).as_posix()] = sha(Path(__file__))
    result = {"試行": 76, "成功": True, "不一致数": 0, "群": groups,
        "テスト件数": sum(g["テスト件数"] for g in groups.values()),
        "照合項目数": sum(g["照合項目数"] for g in groups.values()),
        "関数コメント確認": count, "コードSHA256": pins,
        "本物入力読取": False, "新数値銀行": 0, "新先着計測": 0, "新場内運用": 0}
    path = STUDY / "入力人工確認.json"
    if check_only:
        if json.loads(path.read_text(encoding="utf-8")) != result:
            raise ValueError("76の入力人工記録と現コードの差")
    else:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    return result


def main() -> None:
    """入力人工の初回保存又は既存照合を実行する。

    引数: CLIの--check(bool)は既存証拠の照合。
    返り値: None。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    value = check(parser.parse_args().check)
    print(json.dumps({key: value[key] for key in ("成功", "テスト件数", "照合項目数", "不一致数", "関数コメント確認")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
