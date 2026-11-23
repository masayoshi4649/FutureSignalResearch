"""固定61表示器を保持し、同じ46特徴を再接続した旨の表示だけを訂正する。"""

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00061_現在有効な経路を先に分ける"
RENDERER = HERE / "レポート.py"
RENDERER_SHA256 = "4ecdd6b24f5d32641889d59287dcc91b85935372bf393e2f0d4c431a337ed111"
PHRASES = (
    ("同じ教師集合へ当時の価格経路列を追加", "同じ教師集合へ同じ46特徴を再接続"),
    ("新価格列", "価格経路列"),
    ("IDなしの新4列", "IDなしの各経路4列"),
)
EXPECTED_COUNTS = {PHRASES[0][0]: 1, PHRASES[1][0]: 2, PHRASES[2][0]: 1}
DOCUMENT_NAMES = {"README.md", "設定と結果.md"}
OLD_COMMAND = "C:/Python314/python.exe -X utf8 scripts/現行経路の状態分岐/レポート.py"
NEW_COMMAND = "C:/Python314/python.exe -X utf8 scripts/現行経路の状態分岐/表示訂正.py"
MARKER = "再表示はfit・予測walk・独立測定・回収集計・市場運用を再実行しない。\n\n"
NOTICE = (
    "表示訂正：61は旧60と同じ46特徴の固定根を変更した比較であり、列の追加を示す継承文言3種類だけを訂正した。"
    "固定Rコード・固定JSON・本物結果・数値・式・設定IDは不変。"
    "固定[レポート.py](../../scripts/現行経路の状態分岐/レポート.py)単独は当初版を生成し、"
    "現行の再表示は[表示訂正.py](../../scripts/現行経路の状態分岐/表示訂正.py)を使う。"
    "理由と旧新SHAは[表示訂正.json](表示訂正.json)へ記録した。\n\n"
)


def content_sha(content: bytes) -> str:
    """本文又は保存ファイルの内容指紋を求める。

    引数: content(bytes)は本文又はファイル内容。
    返り値: strはSHA256の小文字16進表記。
    """
    return hashlib.sha256(content).hexdigest()


def phrase_correction(text: str) -> tuple[str, list[dict]]:
    """3限定表現だけを置換し、位置付き逆変換で原文を復元する。

    引数: text(str)は補正前本文又は表の説明セル。
    返り値: tuple[str,list[dict]]は補正本文と位置付き変更。既存の正しい語へ逆置換しない。
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
        raise ValueError("限定語以外が原文へ復元しない")
    return corrected, edits


def corrected_documents(original: dict[str, str]) -> dict[str, str]:
    """限定語とREADME再表示案内だけを訂正し、全表セルの限定性を確認する。

    引数: original(dict[str,str])は固定Rがメモリへ生成した当初二本文。
    返り値: dict[str,str]は補正二本文。数値・式・設定IDと説明以外のセルは不変。
    """
    if set(original) != DOCUMENT_NAMES:
        raise ValueError("固定Rの二文書構成が不一致")
    counts = {old: sum(text.count(old) for text in original.values()) for old, _ in PHRASES}
    if counts != EXPECTED_COUNTS:
        raise ValueError("当初版の3限定表現と置換数が不一致")
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
    if output["README.md"].count(MARKER) != 1:
        raise ValueError("READMEの案内挿入位置が不一致")
    output["README.md"] = output["README.md"].replace(MARKER, NOTICE + MARKER, 1)
    return output


def permitted_content(actual: bytes, original: bytes, corrected: bytes) -> bool:
    """元版又は同じ補正版だけを上書き可能とする。

    引数: actual/original/corrected(bytes)は保存本文・元版・補正版。
    返り値: boolは保存本文が許可された二版のいずれかと完全一致するか。
    """
    return actual in (original, corrected)


# ----------------------------------------
# 固定出典の読取と、許可された表示成果物への書込を分ける。


def render(check: bool = False) -> dict:
    """固定Rを再現元として二本文だけを補正し、訂正台帳と同byteを確認する。

    引数: check(bool)は書込を行わず補正本文と訂正台帳を検査する指定。
    返り値: dictは旧新SHA・全46・55×9・リンク・固定物非変更の検査結果。
    """
    if content_sha(RENDERER.read_bytes()) != RENDERER_SHA256:
        raise ValueError("固定Rコードが当初版から変化")
    spec = importlib.util.spec_from_file_location("現行経路61の固定表示訂正元", RENDERER)
    renderer = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = renderer
    spec.loader.exec_module(renderer)
    context = renderer.context_for()
    original = renderer.documents(context)
    old_bytes = {name: text.encode("utf-8") for name, text in original.items()}
    old_sha = {name: content_sha(content) for name, content in old_bytes.items()}
    output = corrected_documents(original)
    new_bytes = {name: text.encode("utf-8") for name, text in output.items()}
    record_path = STUDY / "表示訂正.json"
    generated = {(STUDY / name).resolve() for name in output} | {record_path.resolve()}
    links = renderer.validate_documents(output, generated)
    protected_paths = list(dict.fromkeys([*context["sources"], RENDERER, Path(__file__), STUDY / "結果.json", STUDY / "固定.json"]))
    protected = {path: content_sha(path.read_bytes()) for path in protected_paths}
    reports = {name: {"旧SHA256": old_sha[name], "新SHA256": content_sha(content), "bytes": len(content)} for name, content in new_bytes.items()}
    record = {
        "試行": 61, "種別": "表示文言だけの訂正", "確認日": "2026-11-06",
        "理由": "同じ46特徴の再接続を列追加と呼ぶ継承文言3種類だけを訂正し、数値・式・設定IDは変更しない",
        "限定置換": [{"訂正前": old, "訂正後": new} for old, new in PHRASES],
        "置換数": {name: {old: original[name].count(old) for old, _ in PHRASES} for name in original},
        "元本文生成": "固定R SHA確認後のdocuments(context_for())。既存元版又は同補正版だけ許可",
        "逆変換で原文一致": True, "表説明以外のセル不変": True,
        "固定R": {"パス": RENDERER.relative_to(ROOT).as_posix(), "SHA256": RENDERER_SHA256},
        "表示ラッパ": {"パス": Path(__file__).relative_to(ROOT).as_posix(), "SHA256": content_sha(Path(__file__).read_bytes())},
        "文書": reports,
        "参照SHA256": {name: content_sha((STUDY / name).read_bytes()) for name in ("結果.json", "固定.json", "保存物確認.json")},
        "READMEのCLI訂正行数": 2, "数値表不変": True, "全特徴数": 46,
        "汎用表": {"版": 5, "手法": 55, "尺度": 9}, "内部リンク検査": links,
        "固定コード変更": False, "固定JSON変更": False, "本物結果変更": False,
        "fit": False, "再計測": False, "市場再生": False,
    }
    record_bytes = (json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    for name, content in new_bytes.items():
        actual = (STUDY / name).read_bytes()
        if not permitted_content(actual, old_bytes[name], content):
            raise ValueError("元版・同補正版以外の保存MDは上書き不可: " + name)
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
# 人工本文だけで限定補正と第三版の拒否を確認する。


class CorrectionTests(unittest.TestCase):
    """正式結果を開かず、限定語・表のセル・元版/補正版だけを検査する。"""

    def test_exact_correction(self) -> None:
        """3限定表現と再表示案内だけを直し、既知の正しい語と数値を保持する。

        引数: なし。
        返り値: None。人工辞書だけを用い、正式入力やMDを読み書きしない。
        """
        source = {"README.md": "新価格列\n" + MARKER + OLD_COMMAND + "\n" + OLD_COMMAND + " --check\n",
                  "設定と結果.md": "新価格列/IDなしの新4列\n| B01 | F20 | 0.5 | 同じ教師集合へ当時の価格経路列を追加。 |\n価格経路列は既存語\n"}
        saved = deepcopy(source)
        result = corrected_documents(source)
        self.assertEqual(source, saved)
        self.assertIn("| B01 | F20 | 0.5 | 同じ教師集合へ同じ46特徴を再接続。 |", result["設定と結果.md"])
        self.assertIn("価格経路列は既存語", result["設定と結果.md"])
        self.assertIn("IDなしの各経路4列", result["設定と結果.md"])
        self.assertIn(NEW_COMMAND + "\n" + NEW_COMMAND + " --check\n", result["README.md"])
        self.assertEqual(result["README.md"].count(NOTICE), 1)
        with self.assertRaises(ValueError):
            corrected_documents({**source, "設定と結果.md": source["設定と結果.md"].replace("IDなしの新4列", "別記")})
        with self.assertRaises(ValueError):
            corrected_documents({**source, "設定と結果.md": source["設定と結果.md"].replace("| B01 |", "| 新価格列 |")})

    def test_known_versions(self) -> None:
        """元版か同補正版だけを許可し、第三版・空本文を拒否する。

        引数: なし。
        返り値: None。実ファイルへの書込は行わない。
        """
        self.assertTrue(permitted_content(b"before", b"before", b"after"))
        self.assertTrue(permitted_content(b"after", b"before", b"after"))
        self.assertFalse(permitted_content(b"third", b"before", b"after"))
        self.assertFalse(permitted_content(b"", b"before", b"after"))


def main() -> None:
    """表示訂正・同byte確認・人工検査を排他的に実行する。

    引数: なし。CLIの--check又は--self-testを解釈する。
    返り値: None。人工時は正式結果・モデル・教師を開かない。
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
