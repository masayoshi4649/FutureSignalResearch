"""固定59表示器を保持し、旧試行リンクの表示名だけを補正する。"""

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00059_保持水準への深さと速度"
RENDERER = HERE / "レポート.py"
RENDERER_SHA256 = "982158f43fff2253dbe969ac30de971caf0354ca91c47b1aab1f9be4e08dd2e5"
ORIGINAL_SHA256 = {
    "README.md": "5611ec53e1ad8c665a655843fd977d8fee75ffa995020c2608724c3f5800b4c4",
    "設定と結果.md": "276c8359706caf7fe134658875ed50dea2d79ca99e87274f5dfac5a60b58e07f",
}
OLD_SENTENCE = "[旧59の全閾値と回収](../00058_同じ水準を追う再試験/設定と結果.md)"
NEW_SENTENCE = "[旧58の全閾値と回収](../00058_同じ水準を追う再試験/設定と結果.md)"
OLD_COMMAND = "C:/Python314/python.exe -X utf8 scripts/価格経路の深さと速度/レポート.py"
NEW_COMMAND = "C:/Python314/python.exe -X utf8 scripts/価格経路の深さと速度/表示訂正.py"
NOTICE = (
    "表示訂正：旧58へのリンク表示にある試行番号の誤記だけを訂正した。参照先は当初から旧58で不変。"
    "固定Rコード・固定JSON・本物結果・数値表は不変。"
    "固定[レポート.py](../../scripts/価格経路の深さと速度/レポート.py)単独は当初版を生成する。"
    "現行の再表示は[表示訂正.py](../../scripts/価格経路の深さと速度/表示訂正.py)を使う。"
    "理由と旧新SHAは[表示訂正.json](表示訂正.json)へ記録した。\n\n"
)


def content_sha(content: bytes) -> str:
    """書込前の本文又は保存ファイルの内容指紋を求める。

    引数: content(bytes)はUTF-8本文又はファイル内容。
    返り値: strはSHA256の小文字16進表記。
    """
    return hashlib.sha256(content).hexdigest()


def corrected_documents(original: dict[str, str]) -> dict[str, str]:
    """旧試行リンクの表示名と再表示案内だけを厳密な位置へ補正する。

    引数: original(dict[str,str])は固定Rから受けた当初版二本文。
    返り値: dict[str,str]は訂正後本文。元辞書と全Markdown表は変更しない。
    """
    if set(original) != set(ORIGINAL_SHA256):
        raise ValueError("固定Rの二文書構成が不一致")
    output = deepcopy(original)
    if output["README.md"].count(OLD_SENTENCE) != 1:
        raise ValueError("訂正文は当初版の厳密1箇所でなければならない")
    output["README.md"] = output["README.md"].replace(OLD_SENTENCE, NEW_SENTENCE, 1)
    lines = output["README.md"].splitlines(keepends=True)
    for suffix in ("", " --check"):
        old, new = OLD_COMMAND + suffix, NEW_COMMAND + suffix
        if sum(line.rstrip("\r\n") == old for line in lines) != 1:
            raise ValueError("READMEの当初再表示CLIは各1行でなければならない")
        lines = [new + line[len(old):] if line.rstrip("\r\n") == old else line for line in lines]
    output["README.md"] = "".join(lines)
    marker = "再表示はfit・予測walk・独立測定・回収集計・市場運用を再実行しない。\n\n"
    if output["README.md"].count(marker) != 1:
        raise ValueError("READMEの訂正案内挿入位置が不一致")
    output["README.md"] = output["README.md"].replace(marker, NOTICE + marker, 1)
    for name in original:
        before = [line for line in original[name].splitlines() if line.startswith("|")]
        after = [line for line in output[name].splitlines() if line.startswith("|")]
        if before != after:
            raise ValueError("表示訂正でMarkdown表が変化した: " + name)
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
    返り値: dictは旧新SHA・表・全30・55×9・リンクの確認結果。
    """
    if content_sha(RENDERER.read_bytes()) != RENDERER_SHA256:
        raise ValueError("固定Rコードが当初版から変化")
    spec = importlib.util.spec_from_file_location("深さ速度の固定59表示訂正元", RENDERER)
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
        "試行": 59, "種別": "表示文言だけの訂正", "確認日": "2026-11-06",
        "理由": "旧58へのリンクの表示名だけが旧59になっていたため、参照先を変えず表示名を旧58へ訂正",
        "訂正前": OLD_SENTENCE, "訂正後": NEW_SENTENCE,
        "固定R": {"パス": RENDERER.relative_to(ROOT).as_posix(), "SHA256": RENDERER_SHA256},
        "表示ラッパ": {"パス": Path(__file__).relative_to(ROOT).as_posix(),
                       "SHA256": content_sha(Path(__file__).read_bytes())},
        "文書": reports,
        "参照SHA256": {name: content_sha((STUDY / name).read_bytes())
                       for name in ("結果.json", "固定.json", "保存物確認.json")},
        "READMEのCLI訂正行数": 2, "数値表不変": True, "全特徴数": 38,
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
            "内部リンク検査": links, "欠落": 0, "全特徴数": 38,
            "版": 5, "手法": 55, "尺度": 9, "同byte確認": check,
            "固定コード_固定JSON_本物結果変更": False, "fit_再計測_市場再生": False}


# ----------------------------------------
# 人工本文だけで限定補正と上書き拒否を検査する。


class CorrectionTests(unittest.TestCase):
    """正式結果を開かず、限定置換・表不変・未知版拒否を確認する。"""

    def test_exact_correction(self) -> None:
        """一文・二CLI・案内以外の本文と全表が不変であることを検査する。

        引数: なし。
        返り値: None。人工辞書だけを使い実保存物は作成しない。
        """
        source = {"README.md": "概要\n" + OLD_SENTENCE + "\n| 数値 | 123 |\n" +
                  "再表示はfit・予測walk・独立測定・回収集計・市場運用を再実行しない。\n\n" +
                  OLD_COMMAND + "\n" + OLD_COMMAND + " --check\n",
                  "設定と結果.md": "| 項目 | 0 | null |\n"}
        saved = deepcopy(source)
        result = corrected_documents(source)
        self.assertEqual(source, saved)
        self.assertEqual(result["設定と結果.md"], source["設定と結果.md"])
        self.assertIn(NEW_SENTENCE, result["README.md"])
        self.assertNotIn(OLD_SENTENCE, result["README.md"])
        self.assertIn(NEW_COMMAND + "\n" + NEW_COMMAND + " --check\n", result["README.md"])
        self.assertEqual(result["README.md"].count(NOTICE), 1)
        for changed in ("なし", OLD_SENTENCE * 2):
            with self.assertRaises(ValueError):
                corrected_documents({**source, "README.md": changed})

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
