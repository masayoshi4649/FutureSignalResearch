"""固定60表示器を保持し、登録足を含む区間名だけを補正する。"""

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
import re
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00060_先行進行と再試験の区間分離"
RENDERER = HERE / "レポート.py"
RENDERER_SHA256 = "5a7a24d9f05dd7f58d5c53054db73063a1fb78fb0892df5422cb88e54e38f286"
ORIGINAL_SHA256 = {
    "README.md": "63464d632ad879e1150370604b18f9ba18cc6d48d9dcc215e47173f370c035de",
    "設定と結果.md": "000b03a061792c598bc5e575de1f4ce4bbe5926c10d81f991ad57e5cef0c9bd1",
}
PHRASES = (("登録前十差分", "登録へ至る十差分"), ("登録前区間", "登録へ至る区間"),
           ("登録前10差分", "登録へ至る10差分"), ("登録前の固定10差分", "登録へ至る固定10差分"))
OLD_COMMAND = "C:/Python314/python.exe -X utf8 scripts/波の区間分離/レポート.py"
NEW_COMMAND = "C:/Python314/python.exe -X utf8 scripts/波の区間分離/表示訂正.py"
NOTICE = (
    "表示訂正：b−10..bは登録足bを含むため、区間の名称を登録へ至る区間として訂正した。式と対象足は当初から不変。"
    "固定Rコード・固定JSON・本物結果・数値・式・設定IDは不変。表は説明セルの限定語だけを訂正した。"
    "固定[レポート.py](../../scripts/波の区間分離/レポート.py)単独は当初版を生成する。"
    "現行の再表示は[表示訂正.py](../../scripts/波の区間分離/表示訂正.py)を使う。"
    "理由と旧新SHAは[表示訂正.json](表示訂正.json)へ記録した。\n\n"
)


def content_sha(content: bytes) -> str:
    """書込前の本文又は保存ファイルの内容指紋を求める。

    引数: content(bytes)はUTF-8本文又はファイル内容。
    返り値: strはSHA256の小文字16進表記。
    """
    return hashlib.sha256(content).hexdigest()


def phrase_correction(text: str) -> tuple[str, list[dict]]:
    """4限定表現を一度だけ置換し、位置付き逆変換で原文を検査する。

    引数: text(str)は補正前本文又は一つの表セル。
    返り値: tuple[str,list[dict]]は補正本文と位置付き変更。既存の正しい名称を逆置換しない。
    """
    mapping = dict(PHRASES)
    pattern = re.compile("|".join(re.escape(old) for old, _ in PHRASES))
    pieces, edits, previous, delta = [], [], 0, 0
    for match in pattern.finditer(text):
        old, new = match.group(), mapping[match.group()]
        pieces.extend((text[previous:match.start()], new))
        edits.append({"position": match.start() + delta, "old": old, "new": new})
        delta += len(new) - len(old)
        previous = match.end()
    pieces.append(text[previous:])
    corrected = "".join(pieces)
    reverse = corrected
    for edit in reversed(edits):
        start, old, new = edit["position"], edit["old"], edit["new"]
        if reverse[start:start + len(new)] != new:
            raise ValueError("位置付き逆変換の対象が不一致")
        reverse = reverse[:start] + old + reverse[start + len(new):]
    if reverse != text:
        raise ValueError("名称以外が逆変換で原文へ復元しない")
    return corrected, edits


def corrected_documents(original: dict[str, str]) -> dict[str, str]:
    """4区間名とREADME再表示案内だけを補正し、全セルの限定性を確認する。

    引数: original(dict[str,str])は固定Rの当初二本文。
    返り値: dict[str,str]は補正本文。数値・式・設定IDと説明以外の表セルは不変。
    """
    if set(original) != set(ORIGINAL_SHA256):
        raise ValueError("固定Rの二文書構成が不一致")
    if any(sum(text.count(old) for text in original.values()) == 0 for old, _ in PHRASES):
        raise ValueError("当初版に4限定表現が揃わない")
    output = {name: phrase_correction(text)[0] for name, text in original.items()}
    for name in original:
        before = [line.split("|") for line in original[name].splitlines() if line.startswith("|")]
        after = [line.split("|") for line in output[name].splitlines() if line.startswith("|")]
        if len(before) != len(after):
            raise ValueError("表行数が変化")
        for old_cells, new_cells in zip(before, after):
            if len(old_cells) != len(new_cells):
                raise ValueError("表のセル数が変化")
            for index, (old, new) in enumerate(zip(old_cells, new_cells)):
                if old != new and (index != len(old_cells) - 2 or phrase_correction(old)[0] != new):
                    raise ValueError("表の説明セル以外又は限定語以外が変化")
    lines = output["README.md"].splitlines(keepends=True)
    for suffix in ("", " --check"):
        old, new = OLD_COMMAND + suffix, NEW_COMMAND + suffix
        if sum(line.rstrip("\r\n") == old for line in lines) != 1:
            raise ValueError("READMEの当初CLIは各1行が必要")
        lines = [new + line[len(old):] if line.rstrip("\r\n") == old else line for line in lines]
    output["README.md"] = "".join(lines)
    marker = "再表示はfit・予測walk・独立測定・回収集計・市場運用を再実行しない。\n\n"
    if output["README.md"].count(marker) != 1:
        raise ValueError("READMEの案内挿入位置が不一致")
    output["README.md"] = output["README.md"].replace(marker, NOTICE + marker, 1)
    return output



def permitted_content(actual: bytes, original: bytes, corrected: bytes) -> bool:
    """当初版又は同じ補正済み本文だけを上書き対象として認める。

    引数: actual/original/corrected(bytes)は保存本文・当初版・補正後。
    返り値: boolは内容が二つの許可版のいずれかと完全一致するか。
    """
    return actual in (original, corrected)


# ----------------------------------------
# 固定表示器の読取と、許可された表示成果物への書込を分ける。


def render(check: bool = False) -> dict:
    """固定Rの二本文へ表示補正を加え、保存又は同byteだけを検査する。

    引数: check(bool)は書込を伴わない補正本文・訂正台帳の検査。
    返り値: dictは旧新SHA・表・全46・55×9・リンクの確認結果。
    """
    if content_sha(RENDERER.read_bytes()) != RENDERER_SHA256:
        raise ValueError("固定Rコードが当初版から変化")
    spec = importlib.util.spec_from_file_location("区間分離の固定60表示訂正元", RENDERER)
    renderer = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = renderer
    spec.loader.exec_module(renderer)
    context = renderer.context_for()
    original = renderer.documents(context)
    old_bytes = {name: value.encode("utf-8") for name, value in original.items()}
    if {name: content_sha(value) for name, value in old_bytes.items()} != ORIGINAL_SHA256:
        raise ValueError("固定Rから再現した当初版2SHAが不一致")
    output = corrected_documents(original)
    new_bytes = {name: value.encode("utf-8") for name, value in output.items()}
    record_path = STUDY / "表示訂正.json"
    generated = {(STUDY / name).resolve() for name in output} | {record_path.resolve()}
    links = renderer.validate_documents(output, generated)
    protected_paths = list(dict.fromkeys([*context["sources"], RENDERER, STUDY / "結果.json", STUDY / "固定.json"]))
    protected = {path: content_sha(path.read_bytes()) for path in protected_paths}
    reports = {name: {"旧SHA256": ORIGINAL_SHA256[name], "新SHA256": content_sha(content),
                      "bytes": len(content)} for name, content in new_bytes.items()}
    record = {
        "試行": 60, "種別": "表示文言だけの訂正", "確認日": "2026-11-06",
        "理由": "b−10..bが登録足bを含むことを区間名でも明確にし、式・対象足・数値を変えず4限定表現を訂正",
        "限定置換": [{"訂正前": old, "訂正後": new} for old, new in PHRASES],
        "置換数": {name: {old: original[name].count(old) for old, _ in PHRASES} for name in original},
        "逆変換で原文一致": True, "表説明以外のセル不変": True,
        "固定R": {"パス": RENDERER.relative_to(ROOT).as_posix(), "SHA256": RENDERER_SHA256},
        "表示ラッパ": {"パス": Path(__file__).relative_to(ROOT).as_posix(),
                       "SHA256": content_sha(Path(__file__).read_bytes())},
        "文書": reports,
        "参照SHA256": {name: content_sha((STUDY / name).read_bytes())
                       for name in ("結果.json", "固定.json", "保存物確認.json")},
        "READMEのCLI訂正行数": 2, "数値表不変": True, "全特徴数": 46,
        "汎用表": {"版": 5, "手法": 55, "尺度": 9}, "内部リンク検査": links,
        "固定コード変更": False, "固定JSON変更": False, "本物結果変更": False,
        "fit": False, "再計測": False, "市場再生": False,
    }
    record_bytes = (json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    for name, content in new_bytes.items():
        actual = (STUDY / name).read_bytes()
        if not permitted_content(actual, old_bytes[name], content):
            raise ValueError("補正前・補正済み以外の保存MDは上書き不可: " + name)
        if check and actual != content:
            raise ValueError("保存MDが補正本文と同byteではない: " + name)
    if record_path.exists() and record_path.read_bytes() != record_bytes:
        raise ValueError("既存の表示訂正台帳が不一致")
    if check:
        if not record_path.is_file() or record_path.read_bytes() != record_bytes:
            raise ValueError("表示訂正台帳が未保存又は同byteではない")
    else:
        for name, content in new_bytes.items():
            (STUDY / name).write_bytes(content)
        record_path.write_bytes(record_bytes)
    if any(content_sha(path.read_bytes()) != expected for path, expected in protected.items()):
        raise ValueError("表示補正中に固定出典又は本物結果が変化")
    return {"文書": reports, "表示訂正SHA256": content_sha(record_path.read_bytes()),
            "表示ラッパSHA256": record["表示ラッパ"]["SHA256"], "数値表不変": True,
            "内部リンク検査": links, "欠落": 0, "全特徴数": 46,
            "版": 5, "手法": 55, "尺度": 9, "同byte確認": check,
            "固定コード_固定JSON_本物結果変更": False, "fit_再計測_市場再生": False}


# ----------------------------------------
# 人工本文だけで限定補正と上書き拒否を検査する。


class CorrectionTests(unittest.TestCase):
    """正式結果を開かず、限定置換・表不変・未知版拒否を確認する。"""

    def test_exact_correction(self) -> None:
        """4限定語・二CLI・案内以外と表の数値/式/IDが不変か検査する。

        引数: なし。
        返り値: None。人工辞書だけを使い実保存物は作成しない。
        """
        marker = "再表示はfit・予測walk・独立測定・回収集計・市場運用を再実行しない。\n\n"
        source = {"README.md": "登録前十差分\n" + marker + OLD_COMMAND + "\n" + OLD_COMMAND + " --check\n",
                  "設定と結果.md": "登録前区間/登録前10差分/登録前の固定10差分\n| S39 | Cb−C[b−10] | 登録前十差分 |\n登録へ至る十差分は既存の正しい名称\n"}
        saved = deepcopy(source)
        result = corrected_documents(source)
        self.assertEqual(source, saved)
        self.assertIn("| S39 | Cb−C[b−10] | 登録へ至る十差分 |", result["設定と結果.md"])
        self.assertIn("登録へ至る十差分は既存の正しい名称", result["設定と結果.md"])
        self.assertIn(NEW_COMMAND + "\n" + NEW_COMMAND + " --check\n", result["README.md"])
        self.assertEqual(result["README.md"].count(NOTICE), 1)
        with self.assertRaises(ValueError):
            corrected_documents({**source, "設定と結果.md": "限定語なし"})

    def test_known_versions(self) -> None:
        """二つの許可版だけを認め、第三版や欠測を許可しない。

        引数: なし。
        返り値: None。実ファイルは読み書きしない。
        """
        self.assertTrue(permitted_content(b"before", b"before", b"after"))
        self.assertTrue(permitted_content(b"after", b"before", b"after"))
        self.assertFalse(permitted_content(b"third", b"before", b"after"))
        self.assertFalse(permitted_content(b"", b"before", b"after"))


def main() -> None:
    """通常表示訂正・同byte検査・人工検査をCLIで選択する。

    引数: なし。--checkと--self-testは排他的に解釈する。
    返り値: None。人工では正式入力又はMDを開かない。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true")
    group.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        tests = unittest.defaultTestLoader.loadTestsFromTestCase(CorrectionTests)
        if not unittest.TextTestRunner(verbosity=2).run(tests).wasSuccessful():
            raise SystemExit(1)
    else:
        print(json.dumps(render(args.check), ensure_ascii=False))


if __name__ == "__main__":
    main()
