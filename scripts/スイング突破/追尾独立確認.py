"""00045の三XF候補について、全保有中BBOと最初返済要求を独立検算する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00045_確定スイング突破と方向優勢"
WORK = ROOT / "work/スイング突破/00045"
STATE_CODE = Path(__file__).with_name("状態独立確認.py")
EXIT_HELPER = ROOT / "scripts/終値位置/追尾独立確認.py"


def helper(path: Path, name: str) -> Any:
    """独立状態と固定費用後起動の独立保有走査だけを読む。

    引数: path(Path)は補助、name(str)は読込識別子。
    返り値: Anyはモジュール。45主入口・主運用はimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


Y = helper(STATE_CODE, "スイング突破の独立状態")
XF = helper(EXIT_HELPER, "スイング突破の費用後起動独立追尾")
V, S, B = XF.V, XF.S, XF.B


def replay(detail: dict, quotes: list[dict], signals: dict[str, dict], audit: Any,
           bounds: tuple | None = None, config: dict | None = None) -> tuple[list[dict], dict]:
    """確定スイング突破の実T/Rを保持した同じXFを全保有区間で検算する。

    引数: detail(dict)は一場詳細、quotes(list[dict])は正常BBO、signals(dict)は当時純信号、audit(Any)は比較先、bounds(tuple|None)は場境界、config(dict|None)は費用設定。
    返り値: tuple[list[dict],dict]は独立全ログと件数。入口現ATRの退出距離を維持する。
    """
    if detail["候補ID"] not in Y.OPERATIONS:
        raise ValueError("事前の三XFだけです")
    return XF.replay_cost(detail, quotes, signals, audit, bounds, config)


# ----------------------------------------
# 原足・全スイング突破の状態証明と、独立財務の約定/会計へSHA接続して責任を分ける。


def run(study: Path, work: Path) -> dict:
    """状態成功後だけ、三XFの全線・起動・非緩和・最初返済要求を照合する。

    引数: study/work(Path)は45正式/作業先。
    返り値: dictは追尾proof。実新規/返済区間の受付・約定と会計は別証明へ接続する。
    """
    if not (study / "結果.json").exists() or not (work / "状態独立確認.json").exists():
        raise ValueError("正式結果と成功状態証明が必要です")
    audit, initial = V.Audit(), V.sha(Path(__file__))
    manifest, resolved = Y.G.resolved_manifest(study)
    state, result, master = (V.read(path) for path in (work / "状態独立確認.json", study / "結果.json", work / "準備点検.json"))
    expected = {"全件一致": True, "不一致数": 0, "不一致": [], "コードSHA256": V.sha(STATE_CODE),
        "追尾コードSHA256": initial, "主準備SHA256": V.sha(work / "準備点検.json"),
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "参照入力台帳SHA256": V.sha(resolved), "指標参照SHA256": V.sha(study / "指標参照.json"),
        
        "結果SHA256": V.sha(study / "結果.json"), "依存コードSHA256": Y.dependency_pins(),
        "主コードSHA256": master["コードSHA256"], "DMI数値定義": master["DMI数値定義"]}
    for name, value in expected.items():
        audit.check("状態bind:" + name, state[name], value)
    for name, digest in V.read(study / "固定.json")["ファイルSHA256"].items():
        audit.check("追尾固定現在:" + name, V.sha(ROOT / name), digest)
    details, detail_sha = S.compressed_rows(work / "全運用詳細.jsonl.gz")
    logs, log_sha = S.compressed_rows(work / "追尾.jsonl.gz")
    cases, case_sha = S.compressed_rows(work / "入口事例.jsonl.gz")
    for name, actual in (("全運用詳細展開SHA256", detail_sha), ("追尾展開SHA256", log_sha), ("入口事例展開SHA256", case_sha)):
        audit.check("保存bind:" + name, actual, state[name])
    signals = {}
    for block in master["準備"]:
        audit.check(block["場"] + ":主pure全文SHA", block["純信号内容SHA256"], Y.canonical_sha(block["純信号"]))
        for row in block["純信号"]:
            audit.check(row["イベントID"] + ":一意", row["イベントID"] not in signals, True)
            audit.check(row["イベントID"] + ":実T/R役割固定", row["役割"] in ("順行", "反転"), True)
            signals[row["イベントID"]] = row
    audit.check("純三入口数", len(signals), state["保存入口事例数"])
    audit.check("case登録ID集合", {row["イベントID"] for row in cases}, set(signals))
    for case in cases:
        projected = {key: case[key] for key in Y.SIGNAL_FIELDS}
        audit.check(case["イベントID"] + ":当時純13列", projected, signals[case["イベントID"]])
        audit.check(case["イベントID"] + ":当時純13値厳密", projected == signals[case["イベントID"]], True)
    grouped, saved = defaultdict(list), {}
    for row in details:
        grouped[row["場"]].append(row)
    for row in logs:
        key = row["場"], row["候補ID"], row["順序"]
        if key in saved:
            raise ValueError("追尾ログ順序が重複しています")
        saved[key] = row
    audit.check("正式三候補順", [row["候補ID"] for row in result["結果"]], list(Y.OPERATIONS))
    pairs = [(row["場"], row["候補ID"]) for row in details]
    audit.check("場候補一意", len(pairs), len(set(pairs)))
    S.compare_keys(audit, "全3x66", set(pairs), {(entry["session"], cid) for entry in manifest["entries"] for cid in Y.OPERATIONS})
    if audit.mismatches:
        raise ValueError("状態/入力/純入口/保存物に差がありcache前停止")
    independent, totals, summaries = {}, Counter(), []
    config = V.read(study / "条件.json")["運用"]
    for entry in manifest["entries"]:
        loaded = B.load(entry)
        quotes = loaded[1]
        del loaded
        for detail in grouped[entry["session"]]:
            rows, counts = replay(detail, quotes, signals, audit, config=config)
            independent.update({(row["場"], row["候補ID"], row["順序"]): row for row in rows})
            totals.update(counts)
            summaries.append({"場": entry["session"], "候補ID": detail["候補ID"],
                "対象新規約定建玉数": sum(row["type"].endswith("N") for row in detail["約定"]),
                "対象完結取引数": len(detail["取引"]), "追尾行数": len(rows),
                "保存終了建玉": detail["品質"]["終了建玉"], "保存終了返済待機": detail["品質"]["終了返済待機"]})
        print(json.dumps({"場": entry["session"], "独立追尾": "三XF/費用後起動/名目床/全線/最初要求", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    S.compare_keys(audit, "全追尾原順集合", set(saved), set(independent))
    for key in sorted(saved.keys() & independent.keys()):
        audit.check("追尾:" + str(key), saved[key], independent[key])
    count = sum(len(row["取引"]) for row in details)
    audit.check("全完結数", count, sum(row[period]["運用"]["完結取引数"] for row in result["結果"]
        for period in ("学習", "条件選択", "後続検査")))
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    proof = {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches, "不一致": audit.errors,
        "対象場候補数": len(details), "対象完結取引数": count, "保存追尾行数": len(logs), "独立追尾行数": len(independent),
        "対象新規約定建玉数": sum(row["対象新規約定建玉数"] for row in summaries),
        "保存未解消候補場数": sum(bool(row["保存終了建玉"] or row["保存終了返済待機"]) for row in summaries),
        "保存通常線行数": len(logs), "独立動作数": dict(totals), "場候補別": summaries,
        "コードSHA256": initial, "依存コードSHA256": Y.dependency_pins(), "独立追尾補助SHA256": V.sha(EXIT_HELPER),
        "結果SHA256": V.sha(study / "結果.json"), "条件SHA256": V.sha(study / "条件.json"),
        "入力台帳SHA256": V.sha(study / "入力台帳.json"), "参照入力台帳SHA256": V.sha(resolved),
        "解決入力台帳SHA256": V.sha(resolved), "指標参照SHA256": V.sha(study / "指標参照.json"),
        
        "主準備SHA256": V.sha(work / "準備点検.json"), "全運用詳細展開SHA256": detail_sha, "追尾展開SHA256": log_sha,
        "主コードSHA256": master["コードSHA256"],
        "通常線更新展開SHA256": log_sha, "入口事例展開SHA256": case_sha,
        "状態独立確認SHA256": V.sha(work / "状態独立確認.json"),
        "DMI数値定義": master["DMI数値定義"],
        "検証範囲": "固定33独立現在費用後replay_costをread再用し、三XFの全実保有BBOで現在純含み益strict正起動/名目同値/MFE-D/非緩和/hard125/TP250/期限の最初返済要求・全snapshotを照合。出口は登録現ATRの固定Dを維持する。",
        "限界": "保存実新規/返済区間は入力。原8列OHLC/ATR/DI/Fast/全スイング/全消費/三採否/全NK直接先着は45状態、新規受付/最初BBO/Decimalは別財務。未解消時はEOF要求までの全保有と完結属性・確定額を区別する。"}
    (work / "追尾独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "対象完結取引数", "保存追尾行数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """root正式完了後の追尾監査だけを明示起動する。

    引数: なし。--study/--work/--実行許可を読む。
    返り値: None。無許可・不一致は非0終了する。
    """
    parser = argparse.ArgumentParser(description="00045三XFの独立全保有追尾")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--実行許可", action="store_true")
    args = parser.parse_args()
    if not args.実行許可:
        parser.error("root正式完了後に --実行許可 を指定してください")
    if not run(args.study.resolve(), args.work.resolve())["全件一致"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
