"""00027の既知65場助走と、開封承認後の新1場だけを別実装で検算する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00027_試行00026の新Night固定後確認"
WORK = ROOT / "work/固定後確認/00027"
OLD_STUDY = ROOT / "study/00026_反転のSAR確認時刻と順行持続"
OLD_WORK = ROOT / "work/反転確認時計/00026"
INPUT = ROOT / "study/00008_外部研究を共通尺度へ移して探索/入力台帳.json"
PRICE_HELPER = ROOT / "scripts/反転確認時計/状態独立確認.py"
SESSION = "2026-11-04_Night"
PERIOD = "固定後確認"
POLICIES = ("N0", "N1", "N2")


def helper(path: Path, name: str) -> Any:
    """固定26の独立価格/SAR/反転確認だけを読み取る。

    引数: path (Path) は独立補助、name (str) は識別子。
    返り値: Any は補助。27主runner/入口/運用をimportせず、新入力も開かない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


B = helper(PRICE_HELPER, "固定後確認の固定26独立OHLCと反転時計")
V, S = B.V, B.S


# ----------------------------------------
# 新Nightを含めるmanifestは正式完了通知後だけ作る。助走は常に固定旧65場だけ。

def references(study: Path, audit: Any) -> tuple[dict, dict]:
    """予約済み三案と固定26/旧65入力の参照指紋を確認する。

    引数: study (Path) は27正式先、audit (Any) は照合先。
    返り値: tuple[dict,dict] は固定26条件と旧65manifest。新原板/cache/CSVは開かない。
    """
    reference = V.read(study / "条件参照.json")
    config = V.read(OLD_STUDY / "条件.json")
    audit.check("固定26条件参照", reference["条件SHA256"], V.sha(OLD_STUDY / "条件.json"))
    audit.check("固定26版参照", reference["固定SHA256"], V.sha(OLD_STUDY / "固定.json"))
    audit.check("事前三候補", reference["確認候補"], ["3分_" + policy + "_X0" for policy in POLICIES])
    audit.check("予約1場", reference["新規確認場"], SESSION)
    manifest = V.read(INPUT)
    audit.check("旧65場固定", len(manifest["entries"]), 65)
    audit.check("旧最終場", manifest["entries"][-1]["session"], "2026-11-04_Day")
    audit.check("旧manifestに新Nightなし", any(entry["session"] == SESSION for entry in manifest["entries"]), False)
    old_proof = V.read(OLD_WORK / "状態独立確認.json")
    audit.check("固定26状態成功", old_proof["全件一致"], True)
    audit.check("固定26独立code現在", old_proof["コードSHA256"], V.sha(PRICE_HELPER))
    audit.check("固定26入力参照", old_proof["入力台帳SHA256"], V.sha(INPUT))
    if audit.mismatches:
        raise ValueError("固定26/旧65参照が不一致のためcacheを開く前に停止")
    return config, manifest


def technical_block(block: dict, period: str | None = None) -> dict:
    """独立技術集合を旧助走又は新1場の保存形式へ投影する。

    引数: block (dict) は固定26独立再構成、period (str|None) は正式新期間の指定。
    返り値: dict はラベル/P&Lなしの九技術stream。新1場の区分名だけを差し替える。
    """
    session, phase = block["場"], period or block["期間"]
    return {"全複合context": [{"期間": phase, **row} for row in block["全context"].values()],
        "全局面": [{"期間": phase, **row} for row in block["局面"]],
        "上位足": [{"場": session, "期間": phase, **row} for size in (15, 30) for row in block["価格足"][size]],
        "全複合shadow": [{"期間": phase, **row} for row in block["全raw"].values()],
        "入口事例": [{"期間": phase, **row} for row in block["全採用"].values()],
        "30分窓": [{"期間": phase, **row} for row in block["30窓"]],
        "SAR": [{"期間": phase, **row} for row in block["SAR"]],
        "監視": ([{"種別": "足監視", "期間": phase, **row} for row in block["監視"]] +
            [{"種別": "監視終了診断", "場": session, "期間": phase, **row} for row in block["監視終了診断"]]),
        "反転監視": ([{"種別": "反転足監視", "期間": phase, **row} for row in block["反転監視"]] +
            [{"種別": "反転終了診断", "場": session, "期間": phase, **row} for row in block["反転監視診断"]])}

# ----------------------------------------
# 助走は新Nightを含めず、主の七系列出典bindと独立数式/時点の比較を分ける。

def input_quality(entry: dict, block: dict, phase: str) -> dict:
    """固定cacheの時刻/正常板だけから入力品質を別集計する。

    引数: entry/block (dict) は固定台帳/独立足、phase (str) は期間表示。
    返り値: dict は正常板数/公開足数/完全幅尾部欠枠。原板は開かずcacheだけを読む。
    """
    import numpy as np
    path = ROOT / "work/複合検証" / entry["cache_path"]
    with np.load(path, allow_pickle=False) as archive:
        times, valid = archive["now"], archive["valid"]
    start, finish, _, _ = B.B.B.S.S.G.times(entry["session"])
    positions = np.flatnonzero(np.isfinite(times) & (times >= start) & (times <= finish))
    local = times[positions]
    if len(local):
        positions = positions[np.r_[True, local[1:] >= np.maximum.accumulate(local[:-1])]]
    frames = block["価格足"]
    return {"場": entry["session"], "正常板数": int(valid[positions].sum()),
        "確定足数": {str(size): sum(frame["publish"] for frame in rows) for size, rows in frames.items()},
        "尾部欠枠": {str(size): max(0, int((finish - start) // (size * 60)) - 1 - (rows[-1]["index"] if rows else -1))
            for size, rows in frames.items()}, "期間": phase}


def stage(block: dict, period: str | None = None) -> dict:
    """大きなATR数値照合列を外し、助走/新1場の小型品質を作る。

    引数: block (dict) は独立技術集合、period (str|None) は表示区分の上書き。
    返り値: dict は全N段階/重要列指紋。ATR実値は保存context等で別照合する。
    """
    return {**{key: value for key, value in block["段階件数"].items() if key not in ("ATR検算列", "ATR全足検算列")},
        "期間": period or block["期間"]}


def warm_source(study: Path, work: Path, audit: Any) -> dict:
    """新入力を読まない主助走の版/範囲/七系列指紋を確認する。

    引数: study/work (Path) は27正式先/作業先、audit (Any) は比較先。
    返り値: dict は主助走証拠。SHA同値と独立数式の保証範囲を分ける。
    """
    source = V.read(work / "助走点検.json")
    audit.check("主助走成功", source["全件一致"], True)
    for key in ("新規原板閲覧", "新規cache閲覧", "先着計算", "損益計算"):
        audit.check("主助走新入力/評価なし:" + key, source[key], False)
    audit.check("主助走65場", source["旧助走場数"], 65)
    audit.check("主助走旧manifest", source["旧入力台帳SHA256"], V.sha(INPUT))
    audit.check("主助走条件参照", source["条件参照SHA256"], V.sha(study / "条件参照.json"))
    audit.check("主助走固定26", source["参照26固定SHA256"], V.sha(OLD_STUDY / "固定.json"))
    allowed_codes = {"scripts/固定後確認/確認.py", "scripts/固定後確認/抽出.py"}
    S.compare_keys(audit, "主助走コードは事前二ファイルだけ", set(source["コードSHA256"]), allowed_codes)
    if set(source["コードSHA256"]) != allowed_codes:
        raise ValueError("新入力をコード指紋へ混ぜず事前二コードだけを照合します")
    for path, digest in source["コードSHA256"].items():
        audit.check("主助走code現在:" + path, digest, V.sha(ROOT / path))
    old_proof = V.read(OLD_WORK / "状態独立確認.json")
    expected = {name + ".jsonl.gz": old_proof[name + "展開SHA256"] for name in
        ("全複合context", "全局面", "上位足", "30分窓", "SAR", "監視", "反転監視")}
    actual = {row["系列"]: row for row in source["技術系列"]}
    S.compare_keys(audit, "主助走七系列", set(actual), set(expected))
    for name in actual.keys() & expected.keys():
        audit.check("主助走固定26七全文SHA:" + name, actual[name]["展開SHA256"], expected[name])
        audit.check("主助走同値明示:" + name, actual[name]["固定26同値"], True)
    if audit.mismatches:
        raise ValueError("主助走の参照版が不一致のためcacheを開く前に停止")
    return source


def check_warm_block(block: dict, entry: dict, actual: dict, audit: Any) -> None:
    """一場の助走品質と重要列/反転投影を独立再構成へ比較する。

    引数: block/entry/actual (dict) は独立場/固定台帳/主助走場、audit (Any) は記録。
    返り値: None。原発動・反転監視指紋はATR整数投影、他の数量は既定数値許容で照合。
    """
    session, phase = block["場"], block["期間"]
    audit.check(session + ":助走場", actual["場"], session)
    audit.check(session + ":助走期間", actual["期間"], phase)
    audit.check(session + ":cache指紋", actual["cacheSHA256"], entry["sha256_cache"])
    audit.check(session + ":全N段階品質", actual["入口品質"], stage(block))
    for key, expected in (("SAR品質", {"期間": phase, **block["SAR品質"]}),
            ("30窓品質", {"場": session, "期間": phase, **block["30窓品質"]}),
            ("局面品質", {"場": session, "期間": phase, **block["局面品質"]}),
            ("入力品質", input_quality(entry, block, phase))):
        audit.check(session + ":独立" + key, actual[key], expected)


def warmup(study: Path, work: Path) -> dict:
    """旧65場だけを原OHLCから再構成し、27主助走と固定26技術へ照合する。

    引数: study/work (Path) は27正式先/作業先。
    返り値: dict は新入力未閲覧/評価なしの明示合否と版。新1場の成績証明ではない。
    """
    audit = V.Audit()
    config, manifest = references(study, audit)
    source = warm_source(study, work, audit)
    sessions = {row["場"]: row for row in source["場別"]}
    S.compare_keys(audit, "助走65場集合", set(sessions), {entry["session"] for entry in manifest["entries"]})
    # 固定26の七技術streamだけを読み、先着/約定/損益保存物は開かない。
    names = ("全複合context", "全局面", "上位足", "30分窓", "SAR", "監視", "反転監視")
    stored, expected_counts = {}, Counter()
    proof26 = V.read(OLD_WORK / "状態独立確認.json")
    for name in names:
        rows, digest = S.compressed_rows(OLD_WORK / (name + ".jsonl.gz"))
        audit.check("固定26技術全文SHA:" + name, digest, proof26[name + "展開SHA256"])
        grouped = defaultdict(list)
        for row in rows:
            grouped[row["場"]].append(row)
        stored[name] = grouped
    totals, rows = Counter(), []
    for entry, block in zip(manifest["entries"], B.reconstruct(manifest, config, audit), strict=True):
        session = block["場"]
        audit.check("助走原順序:" + session, session, entry["session"])
        check_warm_block(block, entry, sessions[session], audit)
        expected = technical_block(block)
        for name in names:
            actual, local = stored[name][session], expected[name]
            audit.check(session + ":技術行数:" + name, len(actual), len(local))
            for index, row in enumerate(local):
                if index < len(actual):
                    B.compare_row(audit, session + ":独立助走:" + name + ":" + str(index), actual[index], row)
            expected_counts[name] += len(local)
        for size, frames in block["価格足"].items():
            totals[str(size)] += len(frames)
        rows.append({"場": session, "期間": block["期間"], "入口品質": stage(block),
            "SAR品質": block["SAR品質"], "30窓品質": block["30窓品質"], "局面品質": block["局面品質"]})
        print(json.dumps({"場": session, "独立助走": "旧65原OHLC/SAR/親とh/全N重要列のみ", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    for row in source["技術系列"]:
        audit.check("主七系列全行数:" + row["系列"], row["件数"], expected_counts[row["系列"].removesuffix(".jsonl.gz")])
    proof = {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches,
        "不一致": audit.errors, "旧助走場数": len(rows), "新規原板閲覧": False, "新規cache閲覧": False,
        "先着計算": False, "損益計算": False, "独立足数": dict(totals), "技術系列行数": dict(expected_counts), "場別": rows,
        "コードSHA256": V.sha(Path(__file__)), "独立26補助SHA256": V.sha(PRICE_HELPER),
        "主助走SHA256": V.sha(work / "助走点検.json"), "旧入力台帳SHA256": V.sha(INPUT),
        "条件参照SHA256": V.sha(study / "条件参照.json"), "参照26固定SHA256": V.sha(OLD_STUDY / "固定.json"),
        "一致の範囲": "旧65原cacheから固定26独立OHLC/指標/公開時点/窓/SAR/反転区間を再構成し、主27live助走の全場品質/重要列canonicalを比較。固定26技術七streamは主助走の全文SHAと行数が同値、独立側は当該保存物の全再計算列を数値許容/離散判断で別照合。上位/原Wの未使用パターン列は独立数式対象外。主27指標/入口/運用をimportしない。",
        "限界": "ATRは26同様abs1e-10/rel0とε/D整数厳密投影、他の七保存物のbyte同値は主出典bindであり独立浮動全列のbyte同値を意味しない。新Nightの原/cache/CSV・新先着/注文/損益を読まず計算しない。助走一致を新1場の収益性へ代用しない。"}
    work.mkdir(parents=True, exist_ok=True)
    (work / "助走独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "旧助走場数", "新規原板閲覧", "先着計算", "損益計算")}, ensure_ascii=False))
    return proof

# ----------------------------------------
# ここから先はrootの開封承認・主正式完了通知後だけ実行する。

def run(study: Path, work: Path) -> dict:
    """旧65の数値助走を保ち、新1場の全状態/採否/対象外時点だけを検算する。

    引数: study/work (Path) は27正式先/作業先。
    返り値: dict は新1場の状態証明。通常先着数値と会計はrootの別監査へ分ける。
    """
    if not (study / "結果.json").exists() or not (study / "固定.json").exists() or not (work / "初回開封記録.json").exists():
        raise ValueError("開封承認後に正式結果が完了してから実行します")
    audit = V.Audit()
    config, old_manifest = references(study, audit)
    main_warm = warm_source(study, work, audit)
    independent_warm = V.read(work / "助走独立確認.json")
    audit.check("独立助走成功", independent_warm["全件一致"], True)
    audit.check("独立助走code現在", independent_warm["コードSHA256"], V.sha(Path(__file__)))
    audit.check("独立助走主証拠現在", independent_warm["主助走SHA256"], V.sha(work / "助走点検.json"))
    for name, digest in V.read(study / "固定.json")["ファイルSHA256"].items():
        audit.check("27開封前固定現在:" + name, V.sha(ROOT / name), digest)
    fresh = V.read(study / "入力台帳.json")
    audit.check("新入力は1場", len(fresh["entries"]), 1)
    entry = fresh["entries"][0]
    audit.check("予約Night", entry["session"], SESSION)
    audit.check("新原板root不変", fresh["source_root"], old_manifest["source_root"])
    cache = (ROOT / "work/複合検証" / entry["cache_path"]).resolve()
    audit.check("新cache解決先", str(cache), str((work / "キャッシュ/NK225" / (SESSION + ".npz")).resolve()))
    audit.check("新cacheは作業先内", cache.is_relative_to(work.resolve()), True)
    combined = V.read(work / "結合入力台帳.json")
    audit.check("全66入力", len(combined["entries"]), 66)
    audit.check("旧65の順序/指紋不変", combined["entries"][:-1], old_manifest["entries"])
    audit.check("最後だけ新入力", combined["entries"][-1], entry)
    audit.check("結合原板root不変", combined["source_root"], old_manifest["source_root"])
    if audit.mismatches:
        raise ValueError("新1場の固定/入力参照が不一致のためcacheを開く前に停止")
    names = ("全複合context", "全局面", "上位足", "全複合shadow", "入口事例", "30分窓", "SAR", "監視", "反転監視", "全運用詳細", "追尾")
    rows, hashes = {}, {}
    for name in names:
        rows[name], hashes[name] = S.compressed_rows(work / (name + ".jsonl.gz"))
        audit.check("保存は新1場のみ:" + name, all(row["場"] == SESSION for row in rows[name]), True)
        if name == "全運用詳細":
            audit.check("運用品質期間は固定後確認", all(row["品質"]["期間"] == PERIOD for row in rows[name]), True)
            audit.check("全取引期間は固定後確認", all(trade["期間"] == PERIOD for row in rows[name] for trade in row["取引"]), True)
        else:
            audit.check("保存期間は固定後確認:" + name, all(row["期間"] == PERIOD for row in rows[name]), True)
    artifacts = V.read(study / "作業成果物.json")
    for item in artifacts["ファイル"]:
        name = Path(item["パス"]).name.removesuffix(".jsonl.gz")
        if name in hashes:
            audit.check("新11技術/運用内容bind:" + name, item["展開内容SHA256"], hashes[name])
    quality_files = {name: V.read(study / (name + ".json")) for name in
        ("入口品質", "局面品質", "30窓品質", "SAR品質", "数量診断品質", "入力品質")}
    source_quality = {}
    for name, values in quality_files.items():
        audit.check(name + ":新1場だけ", len(values), 1)
        audit.check(name + ":予約場", values[0]["場"], SESSION)
        source_quality[name] = values[0]
    warm_rows = {row["場"]: row for row in main_warm["場別"]}
    target, old_count = None, 0
    for row_entry, block in zip(combined["entries"], B.reconstruct(combined, config, audit), strict=True):
        audit.check("全66原順序:" + row_entry["session"], block["場"], row_entry["session"])
        if block["場"] != SESSION:
            check_warm_block(block, row_entry, warm_rows[block["場"]], audit)
            old_count += 1
        else:
            if target is not None:
                raise ValueError("新場の重複")
            target = block
    audit.check("独立助走65", old_count, 65)
    audit.check("新1場再構成あり", target is not None, True)
    if target is None:
        raise ValueError("新1場が再構成されない")
    expected = technical_block(target, PERIOD)
    key_functions = {"全複合context": lambda row: (row["場"], row["index"]),
        "全局面": lambda row: (row["場"], row["index"]),
        "上位足": lambda row: (row["場"], row["minutes"], row["index"]),
        "30分窓": lambda row: (row["場"], row["種別"]), "SAR": lambda row: (row["場"], row["index"]),
        "全複合shadow": lambda row: row["発動ID"], "入口事例": lambda row: row["イベントID"],
        "監視": lambda row: (row["種別"], row["index"] if row["種別"] == "足監視" else row["エピソードID"]),
        "反転監視": lambda row: (row["種別"], row["index"] if row["種別"] == "反転足監視" else row["f発動ID"])}
    label_numbers = ("新規価格", "新規時計秒", "新規原板行", "判定時計秒", "判定原板行", "判定気配", "最大順行pt", "最大逆行pt", "所要分")
    for name, local in expected.items():
        key_of = key_functions[name]
        actual_by_key = {key_of(row): row for row in rows[name]}
        expected_by_key = {key_of(row): row for row in local}
        audit.check("新保存キー重複なし:" + name, len(actual_by_key), len(rows[name]))
        S.compare_keys(audit, "新状態全集合:" + name, set(actual_by_key), set(expected_by_key))
        for key in actual_by_key.keys() & expected_by_key.keys():
            actual, wanted = actual_by_key[key], expected_by_key[key]
            B.compare_row(audit, name + ":" + str(key), actual, wanted)
            if name in ("全複合shadow", "入口事例"):
                time_ok = wanted["要求時計秒"] < target["新規停止"] and target["期限"] - wanted["要求時計秒"] >= 3600
                delay_ok = 0 <= wanted["確認遅延秒"] <= 30
                eligible = time_ok and delay_ok
                audit.check(str(key) + ":先着time/delay", actual["先着評価対象"], eligible)
                if name == "入口事例":
                    audit.check(str(key) + ":全採用先着対象", actual["先着評価対象"], True)
                if not eligible:
                    audit.check(str(key) + ":対象外label", actual["ラベル"], "対象外")
                    audit.check(str(key) + ":対象外優先理由", actual["理由"], "要求時間条件外" if not time_ok else "足確定確認遅延30秒超")
                    for field in label_numbers:
                        audit.check(str(key) + ":対象外9None:" + field, actual[field], None)
    expected_quality = {"入口品質": stage(target, PERIOD),
        "局面品質": {"場": SESSION, "期間": PERIOD, **target["局面品質"]},
        "30窓品質": {"場": SESSION, "期間": PERIOD, **target["30窓品質"]},
        "SAR品質": {"期間": PERIOD, **target["SAR品質"]},
        "数量診断品質": {"場": SESSION, "期間": PERIOD, **target["数量診断品質"]},
        "入力品質": input_quality(entry, target, PERIOD)}
    for name, value in expected_quality.items():
        if name == "数量診断品質":
            for key in source_quality[name].keys() | value.keys():
                audit.check(name + ":" + key, source_quality[name].get(key, 0), value.get(key, 0))
        else:
            audit.check(name + ":全数値", source_quality[name], value)
    canonical = {row["発動ID"]: row for row in rows["全複合shadow"]}
    verdict_errors = []
    for case in rows["入口事例"]:
        origin = canonical.get(case["発動ID"])
        if origin is None:
            verdict_errors.append(case["イベントID"])
            audit.check(case["イベントID"] + ":canonicalあり", False, True)
        else:
            audit.check(case["イベントID"] + ":全N採否canonical", case["戦略判定"], origin["戦略判定"])
            audit.check(case["イベントID"] + ":自己N判定", case["複合判定"], origin["戦略判定"][case["戦略"]])
            if case["戦略判定"] != origin["戦略判定"]:
                verdict_errors.append(case["イベントID"])
    proof = {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches, "不一致": audit.errors,
        "旧助走場数": old_count, "入力場数": 1, "新規確認場数": 1, "期間場数": {PERIOD: 1},
        "表示属性注意": bool(verdict_errors), "case内canonical判定不一致数": len(verdict_errors),
        "保存context数": len(rows["全複合context"]), "保存局面数": len(rows["全局面"]), "保存上位足数": len(rows["上位足"]),
        "保存発動候補数": len(rows["全複合shadow"]), "保存shadow数": len(rows["全複合shadow"]), "保存入口数": len(rows["入口事例"]),
        "保存SAR数": len(rows["SAR"]), "保存30分窓数": len(rows["30分窓"]), "保存監視数": len(rows["監視"]),
        "保存反転監視数": len(rows["反転監視"]), "保存運用詳細数": len(rows["全運用詳細"]), "保存追尾数": len(rows["追尾"]),
        "戦略別入口数": dict(Counter(row["入口ID"] for row in rows["入口事例"])),
        "入口系統別raw数": dict(Counter(row["入口系統"] for row in rows["全複合shadow"])),
        "監視段階": [stage(target, PERIOD)], "コードSHA256": V.sha(Path(__file__)),
        "入力台帳SHA256": V.sha(study / "入力台帳.json"), "旧入力台帳SHA256": V.sha(INPUT),
        "結合入力台帳SHA256": V.sha(work / "結合入力台帳.json"), "条件参照SHA256": V.sha(study / "条件参照.json"),
        "条件SHA256": V.sha(OLD_STUDY / "条件.json"), "結果SHA256": V.sha(study / "結果.json"),
        "独立価格発動補助SHA256": V.sha(PRICE_HELPER), "独立助走SHA256": V.sha(work / "助走独立確認.json"),
        "主助走SHA256": V.sha(work / "助走点検.json"), "27固定SHA256": V.sha(study / "固定.json"),
        **{name + "展開SHA256": digest for name, digest in hashes.items()},
        "発動候補展開SHA256": hashes["全複合shadow"],
        "検証範囲": "固定26の独立原OHLC/SAR/親価格/h区間を旧65+新1の全66場で数値carry再構成し、旧65snapshotは主助走証拠へ、新1だけ全保存context/上位/窓/SAR/局面/親h監視/原fgh/全N純集合へ比較。全case全N属性・先着対象time/delayと対象外理由/9Noneを検査。主27指標/入口/運用をimportせず、旧26条件と入力参照/11展開SHAへbindする。",
        "限界": "新1場の通常先着数値/新規受入/会計/一建玉/追尾は別監査。原板本文を別readerで再抽出せず、版固定の原cacheを共通入力とする。ATRはabs1e-10/rel0とε/D整数厳密投影、旧W未使用パターン列は独立数式対象外。旧65助走の損益を合算せず、新1場の率/黒字を支持や将来安定性へ代用しない。"}
    (work / "状態独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "新規確認場数", "保存shadow数", "保存入口数", "保存SAR数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """未閲覧段階の旧助走か、承認後の正式状態だけを明示実行する。

    引数: なし。--study/--work/--warmup/--実行許可を読む。
    返り値: None。不一致なら非0終了。無指定では新原板/cache/CSVを開かない。
    """
    parser = argparse.ArgumentParser(description="00027固定後確認の独立助走/新1場状態")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--warmup", action="store_true")
    parser.add_argument("--実行許可", action="store_true")
    args = parser.parse_args()
    if args.warmup:
        proof = warmup(args.study.resolve(), args.work.resolve())
    elif args.実行許可:
        proof = run(args.study.resolve(), args.work.resolve())
    else:
        parser.error("新入力なしの --warmup 又はroot正式完了通知後の --実行許可 が必要です")
    if not proof["全件一致"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
