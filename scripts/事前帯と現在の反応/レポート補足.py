"""固定75レポートの純本文を変えず、監査再現の補足だけを末尾へ加える。"""

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00075_事前帯の外保持と内回帰を判別"
ORIGINAL_PATH = HERE / "レポート.py"
ORIGINAL_SHA = "5c678b9f6a3f9be2b6fa5a052844d1f6fa99e8647c2effded0652b554c266907"
AUDIT_PATH = HERE / "保存検証.py"
AUDIT_SHA = "69e4320e3fc0a5b9ceaa2cc41b3ebac23fdaf814c632273aea80c8e92ba37058"
SUPPLEMENT = HERE / "監査補足.py"
REPRODUCTION = STUDY / "再現補足.md"
INITIAL_PROOF = STUDY / "保存物確認_初回.json"
INITIAL_SHA = "a5e239eacb3b35cb545b7195d95d2ac37da6b4cb8ef50d75a1dd1a84c4185ae9"
PYTHON = "work/venvs/technical-tree/Scripts/python.exe -B -X utf8 "
COMMAND = PYTHON + "scripts/事前帯と現在の反応/監査補足.py --run --viewer-url http://127.0.0.1:8092"


def sha(path: Path) -> str:
    """固定実装又は小型表示入力の指紋を求める。

    引数: path(Path)はコード・JSON・Markdown。
    返り値: strはSHA256。価格配列を読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixed() -> None:
    """元Rと初回Aが停止版のままであることを確認する。

    引数: なし。
    返り値: None。不一致なら表示前に停止する。
    """
    if sha(ORIGINAL_PATH) != ORIGINAL_SHA or sha(AUDIT_PATH) != AUDIT_SHA:
        raise ValueError("75の固定R又は初回Aが変更されています")


fixed()
SPEC = importlib.util.spec_from_file_location("事前帯75の固定本文に監査補足", ORIGINAL_PATH)
ORIGINAL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ORIGINAL
SPEC.loader.exec_module(ORIGINAL)


def require_success(context: dict) -> None:
    """成功証明と結果SHAの結合がある文脈だけを許可する。

    引数: context(dict)は表示文脈。人工では架空SHAを明示的に与える。
    返り値: None。不一致や初回失敗証明なら例外。
    """
    proof = context.get("proof")
    digest = context.get("result_sha256")
    if (not isinstance(proof, dict) or proof.get("全件一致") is not True
            or type(proof.get("不一致数")) is not int or proof["不一致数"] != 0
            or proof.get("不一致") != [] or not isinstance(digest, str)
            or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)
            or proof.get("結果SHA256") != digest):
        raise ValueError("75の成功正本proofと結果SHAの結合が必要です")
    supplement = proof.get("監査補足")
    expected = {"初回証明パス": INITIAL_PROOF.relative_to(ROOT).as_posix(), "初回証明SHA256": INITIAL_SHA,
                "原監査コードSHA256": AUDIT_SHA, "置換数": [1, 1], "初回不一致数": 89,
                "原監査再照合全件一致": True}
    if not isinstance(supplement, dict) or any(supplement.get(k) != v for k, v in expected.items()):
        raise ValueError("75の限定監査補足と初回保全証拠が必要です")
    if (supplement["原監査再照合全件一致"] is not True
            or type(supplement["初回不一致数"]) is not int
            or type(supplement["置換数"]) is not list
            or any(type(count) is not int for count in supplement["置換数"])):
        raise ValueError("75監査補足の成否又は件数の型が不正です")
    for field in ("補足コードSHA256", "置換後ソースSHA256"):
        value = supplement.get(field)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("75監査補足のコード指紋が不正です")


def addition(output: Path) -> str:
    """元の本文や再現CLIを消さず、現行の補足監査経路を末尾で案内する。

    引数: output(Path)はREADME又は設定と結果の保存先。
    返り値: strは監査補足段落と新CLI。数値表は追加しない。
    """
    return ("\n## 監査の補足\n\n固定Rの上段本文・数値表・条件は当初版のまま保持した。上段の保存検証.pyコマンドは初回監査の実行経路の記録であり、再実行しない。"
        "初回146,093照合の89差は監査側の期待母集団と未準備quote比較の過指定で、初回証拠を別名保全した。売買条件・主結果・固定A/Rは変更せず、売買runは1回のまま。"
        "現行の監査は別版の補足を使い、成功正本と結果SHAへの結合を確認して表示する。\n\n"
        + ORIGINAL.link(REPRODUCTION, output, "初回差・不変範囲・現行の再現補足") + " / "
        + ORIGINAL.link(SUPPLEMENT, output, "別版の監査補足コード") + " / "
        + ORIGINAL.link(Path(__file__), output, "現行のレポート補足コード")
        + "\n\n実使用環境はtechnical-tree venvのPython 3.14.3・scikit-learn 1.9.1。上段の元Rに残したグローバルPython表記は当初本文として保持し、現行は以下のvenv経路を使う。\n\n```powershell\n" + COMMAND
        + "\n" + PYTHON + "scripts/事前帯と現在の反応/レポート補足.py"
        + "\n" + PYTHON + "scripts/事前帯と現在の反応/レポート補足.py --check\n```\n\n"
        "これは初回の工程順を示す。既存の保存物確認.jsonや正式文書がある場合は補足監査を再起動せず、保存された終了証拠を確認する。"
        "固定レポート.py単独は当初本文の純生成経路、現行の二文書の再表示/同byte検査はレポート補足.pyを使う。"
        "元197人工群・4,298照合と主run1回は維持し、別版補足を新しい売買条件・再fit・追加運用として数えない。\n\n")


def augment(base: dict, context: dict) -> dict:
    """二本文への末尾追記以外に変更がないことを検査する。

    引数: base(dict[str,str])は固定Rの純本文、context(dict)は成功証明付き文脈。
    返り値: dict[str,str]は補足済み二本文。元の数値/表/文言を保持する。
    """
    require_success(context)
    if set(base) != {"README.md", "設定と結果.md"}:
        raise ValueError("固定Rの二文書以外は補足しません")
    result = {}
    for name, body in base.items():
        tail = addition(STUDY / name)
        revised = body + tail
        if revised[:-len(tail)] != body:
            raise AssertionError("75元本文が変更されました")
        before = [line for line in body.splitlines() if line.startswith("| ")]
        after = [line for line in revised.splitlines() if line.startswith("| ")]
        if before != after:
            raise AssertionError("75の数値表又は表説明セルが変更されました")
        result[name] = revised
    return result


def documents(context: dict) -> dict:
    """固定Rの純描画結果へ補足だけを加える。

    引数: context(dict)は正式又は人工の成功文脈。
    返り値: dict[str,str]は二Markdown。ファイルへ書かない。
    """
    require_success(context)
    return augment(ORIGINAL.documents(context), context)


def context_for() -> dict:
    """成功正本が存在する場合だけ元Rの保存表示文脈を使う。

    引数: なし。
    返り値: dictは成功証明・結果SHAと表示入力。主や監査を再実行しない。
    """
    fixed()
    if not SUPPLEMENT.is_file() or not REPRODUCTION.is_file() or not INITIAL_PROOF.is_file():
        raise FileNotFoundError("75の監査補足コードと再現補足が必要です")
    proof_path = STUDY / "保存物確認.json"
    proof = ORIGINAL.read(proof_path)
    preliminary = {"proof": proof, "result_sha256": sha(STUDY / "結果.json")}
    require_success(preliminary)
    if sha(INITIAL_PROOF) != INITIAL_SHA or proof["監査補足"]["補足コードSHA256"] != sha(SUPPLEMENT):
        raise ValueError("75初回保全証拠又は補足コードSHAが一致しません")
    context = ORIGINAL.context_for()
    context["result_sha256"] = preliminary["result_sha256"]
    context["supplement_sources"] = [Path(__file__), AUDIT_PATH, SUPPLEMENT, REPRODUCTION, INITIAL_PROOF]
    require_success(context)
    return context


def render(check: bool = False) -> dict:
    """既知の元本文又は同補足済み本文だけを保存/同byte照合する。

    引数: check(bool)は書込みなし照合。
    返り値: dictは元/現文書SHA・サイズ・リンク・不変の証拠。
    """
    context = context_for()
    sources = list(dict.fromkeys([*context["sources"], *context["supplement_sources"]]))
    before = {p.relative_to(ROOT).as_posix(): sha(p) for p in sources}
    base = ORIGINAL.documents(context)
    revised = augment(base, context)
    generated = {(STUDY / name).resolve() for name in revised}
    links = sum(ORIGINAL.check_links(text, STUDY / name, generated) for name, text in revised.items())
    if before != {p.relative_to(ROOT).as_posix(): sha(p) for p in sources}:
        raise ValueError("75表示補足中の正本変更")
    for name, text in revised.items():
        path, data, original = STUDY / name, text.encode("utf-8"), base[name].encode("utf-8")
        if check:
            if not path.is_file() or path.read_bytes() != data:
                raise ValueError("75補足済み文書と再表示に差があります:" + name)
        elif path.exists() and path.read_bytes() not in (original, data):
            raise FileExistsError("75の未知の文書版は上書きしません:" + name)
    if not check:
        for name, text in revised.items():
            (STUDY / name).write_bytes(text.encode("utf-8"))
    fixed()
    if before != {p.relative_to(ROOT).as_posix(): sha(p) for p in sources}:
        raise ValueError("75表示補足の保存完了時に正本変更を検出しました")
    return {"成功": True, "元文書": {name: hashlib.sha256(text.encode("utf-8")).hexdigest() for name, text in base.items()},
        "文書": {name: {"SHA256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "bytes": len(text.encode("utf-8"))} for name, text in revised.items()},
        "内部リンク検査": links, "欠落": 0, "元本文数値表不変": True, "入力前後不変": True,
        "固定R_SHA256": ORIGINAL_SHA, "固定A_SHA256": AUDIT_SHA, "結果SHA256": context["result_sha256"], "版": 5, "手法": 55, "尺度": 9}


def self_test() -> dict:
    """固定fixtureで追記だけ・表不変・成功証明の拒否境界を検査する。

    引数: なし。正式結果・価格・監査は読まず実行しない。
    返り値: dictは人工群数と照合件数。
    """
    checks, tests = 0, 0
    before_r, before_a = sha(ORIGINAL_PATH), sha(AUDIT_PATH)
    for active in (False, True):
        context = ORIGINAL.fixture(active)
        context["result_sha256"] = "a" * 64
        context["proof"] = {"全件一致": True, "不一致数": 0, "不一致": [], "結果SHA256": "a" * 64}
        context["proof"]["監査補足"] = {"初回証明パス": INITIAL_PROOF.relative_to(ROOT).as_posix(),
            "初回証明SHA256": INITIAL_SHA, "原監査コードSHA256": AUDIT_SHA,
            "置換数": [1, 1], "初回不一致数": 89, "原監査再照合全件一致": True,
            "補足コードSHA256": "c" * 64, "置換後ソースSHA256": "d" * 64}
        base = ORIGINAL.documents(context)
        prior_sources = list(context["sources"])
        context["supplement_sources"] = [Path(__file__), REPRODUCTION]
        revised = documents(context)
        assert context["sources"] == prior_sources
        assert ORIGINAL.documents(context) == base
        checks += 2
        generated = {(STUDY / name).resolve() for name in revised} | {SUPPLEMENT.resolve(), REPRODUCTION.resolve()}
        for name, body in revised.items():
            assert body == base[name] + addition(STUDY / name)
            assert [line for line in body.splitlines() if line.startswith("| ")] == [line for line in base[name].splitlines() if line.startswith("| ")]
            assert ORIGINAL.check_links(body, STUDY / name, generated) > 0
            checks += 3
        tests += 1
    for key, value in (("初回証明SHA256", "b" * 64), ("置換数", [1, 2]), ("原監査再照合全件一致", False)):
        bad = deepcopy(context)
        bad["proof"]["監査補足"][key] = value
        try:
            documents(bad)
        except ValueError:
            checks += 1
        else:
            raise AssertionError("75補足表示が不正な補足範囲を受理しました")
        tests += 1
    for change in ({"全件一致": False}, {"不一致数": 89}, {"不一致": ["初回差"]}, {"結果SHA256": "b" * 64}):
        bad = deepcopy(context)
        bad["proof"].update(change)
        try:
            documents(bad)
        except ValueError:
            checks += 1
        else:
            raise AssertionError("75補足表示が失敗proofを受理しました")
        tests += 1
    assert sha(ORIGINAL_PATH) == before_r == ORIGINAL_SHA and sha(AUDIT_PATH) == before_a == AUDIT_SHA
    checks += 2
    assert COMMAND.startswith("work/venvs/technical-tree/Scripts/python.exe -B -X utf8 ")
    assert "C:/Python314" not in addition(STUDY / "README.md")
    checks += 2
    tests += 1
    return {"成功": True, "テスト件数": tests, "照合項目数": checks, "不一致数": 0, "不一致": [],
            "固定R不変": True, "固定A不変": True, "正式結果読取": False, "新fit": 0, "市場再生": False}


def main() -> None:
    """root許可後の表示/照合又は市場を使わない人工を選択する。

    引数: CLIの--check/--self-testは排他的な任意旗。
    返り値: None。通常生成は成功監査後だけ。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true")
    group.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    print(json.dumps(self_test() if args.self_test else render(args.check), ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
