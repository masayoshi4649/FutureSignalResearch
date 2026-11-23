"""00034の二XFを、固定33の独立費用起動/全線と固定指値出典へ照合する。"""

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
STUDY = ROOT / "study/00034_CCI突破の水準指値"
WORK = ROOT / "work/突破指値/00034"
STATE_CODE = Path(__file__).with_name("状態独立確認.py")
EXIT_HELPER = ROOT / "scripts/終値位置/追尾独立確認.py"


def helper(path: Path, name: str) -> Any:
    """独立状態と固定33の独立費用追尾だけを読み込む。

    引数: path (Path) は独立コード、name (str) はモジュール識別。
    返り値: Any は補助。34/33の主運用をimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


Y = helper(STATE_CODE, "突破指値の独立状態")
X = helper(EXIT_HELPER, "突破指値の固定33独立費用追尾")
V, S, B = X.V, X.S, X.B


def replay(detail: dict, quotes: list[dict], signals: dict[str, dict], audit: Any,
           bounds: tuple | None = None, config: dict | None = None) -> tuple[list[dict], dict]:
    """実保有からの固定XFを別走査し、E1の指値登録出典も全件比較する。

    引数: detail (dict) は一場詳細、quotes (list[dict]) は原正常気配、signals (dict) は純当時情報、
    audit (Any) は比較先、bounds (tuple|None) は人工時計、config (dict|None) は運用数値。
    返り値: tuple[list[dict],dict] は全独立追尾ログ/件数。新規受付・最初指値約定は別会計検算。
    """
    rows, counts = X.replay_cost(detail, quotes, signals, audit, bounds, config)
    if detail["候補ID"] == "3分_E1_XF":
        orders = {row["注文ID"]: row for row in detail["注文"]}
        for row in rows:
            position = row["建玉"]
            if position is not None:
                source = signals[position["event_id"]]
            elif row["動作"] == "注文要求" and row.get("区分") == "新規":
                source = signals[orders[row["注文ID"]]["入口イベントID"]]
            else:
                continue
            row.update(新規指値価格=source["新規指値価格"], 指値根拠=deepcopy(source["指値根拠"]))
        for trade in detail["取引"]:
            source = signals[trade["入口イベントID"]]
            for field in ("新規指値価格", "指値根拠"):
                audit.check(detail["場"] + trade["建玉ID"] + ":" + field, trade[field], source[field])
    elif detail["候補ID"] != "3分_E0_XF":
        raise ValueError("固定二XF候補だけを検算します")
    return rows, counts


# ----------------------------------------
# 新規受付/最初指値約定の財務監査と、約定後の全保有追尾を分離する。

def run(study: Path, work: Path) -> dict:
    """正式状態成功後に全二XFの最初返済要求・全線・指値出典を検算する。

    引数: study/work (Path) は34保存先。
    返り値: dict は追尾proof。新規の指値成立走査は状態/財務の別証明に接続する。
    """
    if not (study / "結果.json").exists() or not (work / "状態独立確認.json").exists():
        raise ValueError("正式結果と成功状態proofが必要です")
    initial, audit = V.sha(Path(__file__)), V.Audit()
    manifest, resolved = Y.G.resolved_manifest(study)
    state, result, master = (V.read(path) for path in (work / "状態独立確認.json", study / "結果.json", work / "準備点検.json"))
    expected = {"全件一致": True, "不一致数": 0, "不一致": [], "コードSHA256": V.sha(STATE_CODE),
        "追尾コードSHA256": initial, "主準備SHA256": V.sha(work / "準備点検.json"),
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "参照入力台帳SHA256": V.sha(resolved), "入口参照SHA256": V.sha(study / "入口参照.json"),
        "対照参照SHA256": V.sha(study / "対照参照.json"), "結果SHA256": V.sha(study / "結果.json"),
        "依存コードSHA256": Y.dependency_pins()}
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
        audit.check(block["場"] + ":主生pureSHA", block["純信号内容SHA256"], Y.canonical_sha(block["純信号"]))
        for row in block["純信号"]:
            audit.check(row["イベントID"] + ":一意", row["イベントID"] not in signals, True)
            signals[row["イベントID"]] = row
    audit.check("純全2登録数", len(signals), state["原C0登録数"] * 2)
    audit.check("case全登録ID集合", {row["イベントID"] for row in cases}, set(signals))
    for case in cases:
        policy = case["入口ID"].removeprefix("3分_")
        audit.check(case["イベントID"] + ":当時whitelist", Y.pure_signal(case, policy), signals[case["イベントID"]])
    grouped, saved = defaultdict(list), {}
    for row in details:
        grouped[row["場"]].append(row)
    for row in logs:
        key = row["場"], row["候補ID"], row["順序"]
        if key in saved:
            raise ValueError("追尾logの候補/場/順序が重複")
        saved[key] = row
    audit.check("正式二候補順", [row["候補ID"] for row in result["結果"]], list(Y.OPERATIONS))
    pairs = [(row["場"], row["候補ID"]) for row in details]
    audit.check("場候補一意", len(pairs), len(set(pairs)))
    S.compare_keys(audit, "全2x66", set(pairs), {(entry["session"], cid) for entry in manifest["entries"] for cid in Y.OPERATIONS})
    if audit.mismatches:
        raise ValueError("状態/入力/純信号/保存物が異なるためcache前停止")
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
        print(json.dumps({"場": entry["session"], "独立追尾": "全二XF/費用起動/全線/指値出典", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    S.compare_keys(audit, "全追尾原順集合", set(saved), set(independent))
    for key in sorted(saved.keys() & independent.keys()):
        audit.check("追尾:" + str(key), saved[key], independent[key])
    count = sum(len(row["取引"]) for row in details)
    audit.check("正式全完結数", count, sum(row[period]["運用"]["完結取引数"] for row in result["結果"]
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
        "解決入力台帳SHA256": V.sha(resolved), "入口参照SHA256": V.sha(study / "入口参照.json"),
        "対照参照SHA256": V.sha(study / "対照参照.json"), "主準備SHA256": V.sha(work / "準備点検.json"),
        "全運用詳細展開SHA256": detail_sha, "追尾展開SHA256": log_sha, "通常線更新展開SHA256": log_sha,
        "入口事例展開SHA256": case_sha, "共有入口事例展開SHA256": state["共有入口事例展開SHA256"],
        "状態独立確認SHA256": V.sha(work / "状態独立確認.json"),
        "検証範囲": "固定33の独立費用起動replay_costをread再用し、全二運用の実新規から実返済/場末までの現在費用後strict正・起動出典・名目同値/MFE-D非緩和・hard125/TP250/期限の最初要求と全線を検算。E1の新規request/保有/終了の全top指値出典と全trade追加出典も除外せず厳密照合。",
        "限界": "保存実新規/返済区間は入力。純1602先着は状態の直接列走査、新規受付/単一pending/最初指値約定/代理約定会計は別財務。未解消時は完結属性/確定額を作らずEOF要求までの保有線と保存未解消数を区別する。"}
    (work / "追尾独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "対象完結取引数", "保存追尾行数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """root正式完了後の明示追尾監査だけを起動する。

    引数: なし。--study/--work/--実行許可を読む。
    返り値: None。無許可と不一致は非0終了。
    """
    parser = argparse.ArgumentParser(description="00034固定費用後起動と指値出典の独立追尾")
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
