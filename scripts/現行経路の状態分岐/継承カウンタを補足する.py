"""凍結A61の旧38継承キー一件漏れだけを、元証明を残して補足する。"""

import argparse
import ast
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00061_現在有効な経路を先に分ける"
OLD = ROOT / "study/00060_先行進行と再試験の区間分離"
PROOF = STUDY / "保存物確認.json"
INITIAL = STUDY / "保存物確認_初回.json"
NEWDETAIL = ROOT / "work/現行経路の状態分岐/00061/定時判断と運用.jsonl.gz"
OLDDETAIL = ROOT / "work/波の区間分離/00060/定時判断と運用.jsonl.gz"
KEY = "旧38特徴保存一致"
ORIGINAL_SHA256 = "ddd40cb37d4d38c8bdaa8d221278215d54db35556173cf52de32b6829ac6e38d"


def sha(path: Path) -> str:
    """保存内容をSHA256へ結ぶ。

    引数: path(Path)は出典。
    返り値: strは内容指紋。固定物を変更しない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """小型JSONをUTF-8で読む。

    引数: path(Path)は保存JSON。
    返り値: dictは保存値。新主や旧監査を起動しない。
    """
    return json.loads(path.read_text(encoding="utf-8"))


def fingerprint(value: object) -> str:
    """JSON表現で全型値を厳密比較する。

    引数: value(object)は有限JSON。
    返り値: strは内容指紋。intとfloatを同一視しない。
    """
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def recover_counter(initial: dict, current: dict, inherited: dict, count46: int, count38: int) -> dict:
    """唯一の元差と実数から、欠けた期待キーだけを復元する。

    引数: initial(dict)は初回失敗証明、current/inherited(dict)は61/60カウンタ、count46/count38(int)は実照合数。
    返り値: dictは正しい六キー期待辞書。他の差や値の違いは拒否する。
    """
    if (initial.get("全件一致"), initial.get("照合項目数"), initial.get("不一致数")) != (False, 119952, 1):
        raise ValueError("初回監査の一件差という前提が不成立")
    differences = initial.get("不一致")
    if not isinstance(differences, list) or len(differences) != 1 or differences[0].get("項目") != "主内保存照合数":
        raise ValueError("元不一致が継承カウンタ以外又は複数")
    actual = ast.literal_eval(differences[0]["実際"])
    expected = ast.literal_eval(differences[0]["期待"])
    if actual != current or set(actual) - set(expected) != {KEY} or set(expected) - set(actual):
        raise ValueError("元差が旧38一キーだけではない")
    if any(expected[key] != actual[key] for key in expected):
        raise ValueError("既存五値にも不一致がある")
    if inherited.get(KEY) != 3404 or current.get(KEY) != 3404 or count46 != 3404 or count38 != 3404:
        raise ValueError("旧60又は実辞書数から継承値を復元できない")
    if current.get("旧46特徴保存一致") != count46:
        raise ValueError("新46全辞書カウンタと実数が違う")
    repaired = {**expected, KEY: inherited[KEY]}
    if repaired != current:
        raise ValueError("期待キー復元後も差が残る")
    return repaired


def saved_features(path: Path, mapping: dict[str, str]) -> dict:
    """保存された全枠特徴を場・対応政策・枠で一意に抽出する。

    引数: path(Path)は保存gzip、mapping(dict[str,str])は旧から新への政策名だけ。
    返り値: dictは全3404の保存特徴。特徴再計算・予測walkをしない。
    """
    output, blocks = {}, set()
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            block = json.loads(line)
            if block["policy"] not in mapping:
                raise ValueError("対象外政策の保存block")
            policy = mapping[block["policy"]]
            group = block["session"], policy
            if group in blocks:
                raise ValueError("保存block重複")
            blocks.add(group)
            for slot in block["slots"]:
                key = block["session"], policy, slot["slot_id"]
                if key in output or slot["session"] != block["session"]:
                    raise ValueError("保存枠の重複又は場差")
                output[key] = slot["feature"]
    if len(blocks) != 92 or len(output) != 3404:
        raise ValueError("保存92block/3404枠の実数不成立")
    return output


def projection38(feature: dict) -> dict:
    """同46全辞書を旧59の38辞書へ機械的に射影する。

    引数: feature(dict)は60又は61の同じ46辞書。
    返り値: dictは旧38項目。新値を計算しない。
    """
    names = ("ready", "reason", "base", "control_vectors", "vectors", "atr", "D", "background_direction", "paths", "history", "control_vectors30", "geometry")
    result = {name: deepcopy(feature[name]) for name in names}
    result["vectors"] = deepcopy(feature["control_vectors38"])
    return result


def supplement(initial: dict) -> dict:
    """旧成功proofと保存全辞書から限定補足を作り、他の元保証を不変で結ぶ。

    引数: initial(dict)はバイト保全した初回監査。
    返り値: dictは経緯/旧新指紋/追加照合数付きの正本。原監査を再実行しない。
    """
    if sha(INITIAL) != ORIGINAL_SHA256:
        raise ValueError("初回証明のバイト保全不成立")
    checks = 1
    old_result, old_proof = read(OLD / "結果.json"), read(OLD / "保存物確認.json")
    result, fixed = read(STUDY / "結果.json"), read(STUDY / "固定.json")
    if not old_proof["全件一致"] or old_proof["不一致数"] != 0 or old_proof["結果SHA256"] != sha(OLD / "結果.json"):
        raise ValueError("旧60成功証明と旧結果の結合不成立")
    if result["固定SHA256"] != sha(STUDY / "固定.json") or initial["結果SHA256"] != sha(STUDY / "結果.json"):
        raise ValueError("初回と結果/固定の結合差")
    checks += 2
    # ----------------------------------------
    # 主61が主60の検証済みchecksを継承し、旧38を上書きしていない構造も確認する。
    main61 = ROOT / "scripts/現行経路の状態分岐/検証.py"
    main60 = ROOT / "scripts/波の区間分離/検証.py"
    for path in (main61, main60, OLD / "結果.json", OLD / "保存物確認.json"):
        if sha(path) != fixed["ファイルSHA256"][path.relative_to(ROOT).as_posix()]:
            raise ValueError("主60/61又は旧成功証明が固定と違う")
        checks += 1
    source = main61.read_text(encoding="utf-8")
    tree = ast.parse(source)
    body = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "verified_saved_inputs")
    calls = [node for node in ast.walk(body) if isinstance(node, ast.Call)]
    if not any(isinstance(c.func, ast.Attribute) and c.func.attr == "verified_saved_inputs" and isinstance(c.func.value, ast.Name) and c.func.value.id == "PREVIOUS" for c in calls):
        raise ValueError("主60の検査継承呼出しがない")
    if "scripts/波の区間分離/検証.py" not in source:
        raise ValueError("PREVIOUSの旧主60出典がない")
    for node in ast.walk(body):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, (ast.AnnAssign, ast.AugAssign)) else []
        if any(isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and t.value.id == "checks" and isinstance(t.slice, ast.Constant) and t.slice.value == KEY for t in targets):
            raise ValueError("主61が旧38継承キーを上書きしている")
    checks += 2
    groups = ("参照SHA256", "モデルSHA256", "キャッシュSHA256", "新Viewer約定SHA256")
    protected = {}
    for group in groups:
        for name, digest in initial[group].items():
            if sha(ROOT / name) != digest:
                raise ValueError("初回監査後の参照変更: " + name)
            protected[name] = digest
            checks += 1
    old, new = saved_features(OLDDETAIL, {"S0": "A0", "S1": "A1"}), saved_features(NEWDETAIL, {"A0": "A0", "A1": "A1"})
    if old.keys() != new.keys():
        raise ValueError("旧60と61の全保存枠集合が違う")
    checks += 1
    count46 = count38 = 0
    for key in old:
        if fingerprint(old[key]) != fingerprint(new[key]):
            raise ValueError("同46保存全辞書差: " + str(key))
        count46 += 1
        if fingerprint(projection38(old[key])) != fingerprint(projection38(new[key])):
            raise ValueError("38射影差: " + str(key))
        count38 += 1
        checks += 2
    expected = recover_counter(initial, result["検査"], old_result["検査"], count46, count38)
    checks += 1
    for name, digest in protected.items():
        if sha(ROOT / name) != digest:
            raise ValueError("補足中の参照変更: " + name)
        checks += 1
    corrected = deepcopy(initial)
    corrected.update(全件一致=True, 不一致数=0, 不一致=[], 照合項目数=initial["照合項目数"] + checks)
    corrected["初回監査"] = {"パス": INITIAL.relative_to(ROOT).as_posix(), "SHA256": ORIGINAL_SHA256,
        "全件一致": False, "照合項目数": 119952, "不一致数": 1, "他の初回成功項目数": 119951}
    corrected["限定補足"] = {"原因": "固定監査の主内保存照合数期待辞書で、旧60から保持する旧38特徴保存一致一キーを漏らした。主/resultの値は正しかった",
        "補足コード": {"パス": Path(__file__).relative_to(ROOT).as_posix(), "SHA256": sha(Path(__file__))},
        "解消した項目": "主内保存照合数", "元不一致唯一": True, "元不一致数": 1, "補足解消数": 1, "残不一致数": 0,
        "旧60旧38保存カウンタ": old_result["検査"][KEY], "同46保存全辞書実数": count46, "同38射影実数": count38,
        "復元期待辞書": expected, "追加照合項目数": checks, "初回参照SHA不変": True,
        "固定A変更": False, "主結果変更": False, "原監査再実行": False, "市場再生": False, "fit": False,
        "意味": "元119951成功を維持し、元1差は同じ保存物からキーを復元して解消。経済的判断を救済したものではない"}
    corrected["参照SHA256"].update({INITIAL.relative_to(ROOT).as_posix(): ORIGINAL_SHA256, Path(__file__).relative_to(ROOT).as_posix(): sha(Path(__file__))})
    return corrected


def self_test() -> dict:
    """紙上の唯一差だけを復元し、別差/誤値/複数差を拒否する。

    引数: なし。
    返り値: dictは人工成功/照合数。正式入力又は証明を開かない。
    """
    expected = {"測定特徴方向一致": 4884, "旧評価特徴完全一致": 3404, "旧18特徴完全一致": 2442, "旧46特徴保存一致": 3404, "同一新規完結一致": 240}
    current = {**expected, KEY: 3404}
    initial = {"全件一致": False, "照合項目数": 119952, "不一致数": 1,
        "不一致": [{"項目": "主内保存照合数", "実際": repr(current), "期待": repr(expected)}]}
    assert recover_counter(initial, current, {KEY: 3404}, 3404, 3404) == current
    checks = 1
    for mode in ("別項目", "複数差", "既存値差", "実数不足"):
        proof, actual, count = deepcopy(initial), deepcopy(current), 3404
        if mode == "別項目":
            proof["不一致"][0]["項目"] = "先着差"
        elif mode == "複数差":
            proof["不一致数"] = 2
        elif mode == "既存値差":
            actual["同一新規完結一致"] = 239
        else:
            count = 3403
        denied = False
        try:
            recover_counter(proof, actual, {KEY: 3404}, count, 3404)
        except ValueError:
            denied = True
        assert denied, mode
        checks += 1
    return {"人工成功": True, "照合項目数": checks, "本物入力読取": False}


def main() -> None:
    """人工後に初回をバイト保全し、限定補足した正本だけを保存する。

    引数: CLI --self-test又は--run。
    返り値: None。初回が既存なら再実行を拒否し、原監査の再実行はしない。
    """
    parser = argparse.ArgumentParser()
    flags = parser.add_mutually_exclusive_group(required=True)
    flags.add_argument("--self-test", action="store_true")
    flags.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False))
        return
    if INITIAL.exists() or sha(PROOF) != ORIGINAL_SHA256:
        raise ValueError("初回が既に保全済み又は元証明のSHAが違う")
    raw = PROOF.read_bytes()
    initial = json.loads(raw)
    INITIAL.write_bytes(raw)
    if INITIAL.read_bytes() != raw:
        raise ValueError("初回証明の同byte保全不成立")
    result = supplement(initial)
    if PROOF.read_bytes() != raw or sha(INITIAL) != ORIGINAL_SHA256:
        raise ValueError("補足中に元証明が変化")
    PROOF.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"全件一致": result["全件一致"], "照合項目数": result["照合項目数"], "不一致数": result["不一致数"],
        "初回監査": result["初回監査"], "限定補足": result["限定補足"], "正本SHA256": sha(PROOF)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
