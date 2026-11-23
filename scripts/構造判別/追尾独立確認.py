"""00037の旧参考A5と現行費用後起動XFを、固定独立保有走査へ分けて照合する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00037_高安帰還と外側継続の判別"
WORK = ROOT / "work/構造判別/00037"
STATE_CODE = Path(__file__).with_name("状態独立確認.py")
EXIT_HELPER = ROOT / "scripts/終値位置/追尾独立確認.py"
OLD_EXIT_HELPER = ROOT / "scripts/異種発動/追尾独立確認.py"


def helper(path: Path, name: str) -> Any:
    """新独立状態と固定独立追尾だけを起動なしで読む。

    引数: path(Path)は独立コード、name(str)はモジュール名。
    返り値: Anyは補助。36主入口・運用をimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


Y = helper(STATE_CODE, "構造判別の独立状態")
X0 = helper(OLD_EXIT_HELPER, "構造判別の旧A5独立追尾")
XF = helper(EXIT_HELPER, "構造判別の費用後起動独立追尾")
V, S, B = XF.V, XF.S, XF.B


def replay(detail: dict, quotes: list[dict], signals: dict[str, dict], audit: Any,
           bounds: tuple | None = None, config: dict | None = None) -> tuple[list[dict], dict]:
    """五候補の旧参考A5と現行XFを別の独立核で全保有走査する。

    引数: detail(dict)は一場詳細、quotes(list[dict])は正常BBO、signals(dict)は検証済純入口、audit(Any)は比較、bounds(tuple|None)は開始/終了/force、config(dict|None)は運用。
    返り値: tuple[list[dict],dict]は独立全logと件数。構造から新退出条件を追加せず、混合S1は登録ごとの役割をfillで固定。
    """
    if detail["候補ID"] not in Y.OPERATIONS:
        raise ValueError("事前の五運用だけです")
    if detail["候補ID"] == "3分_B0_X0":
        return X0.replay(detail, quotes, signals, audit, bounds)
    return XF.replay_cost(detail, quotes, signals, audit, bounds, config)


# ----------------------------------------
# 状態の構造四採否、財務の約定/会計、追尾の全線/最初要求を別proofへ接続する。


def run(study: Path, work: Path) -> dict:
    """正式状態成功後に全五X0/XFの最初返済要求・全線・fill固定役割を検算する。

    引数: study/work (Path) は36保存先。
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
    audit.check("純四入口数", len(signals), state["保存入口事例数"])
    audit.check("case全登録ID集合", {row["イベントID"] for row in cases}, set(signals))
    for case in cases:
        policy = case["入口ID"].removeprefix("3分_")
        audit.check(case["イベントID"] + ":当時whitelist", Y.pure_signal(case, policy, case["side"], case["役割"]), signals[case["イベントID"]])
    grouped, saved = defaultdict(list), {}
    for row in details:
        grouped[row["場"]].append(row)
    for row in logs:
        key = row["場"], row["候補ID"], row["順序"]
        if key in saved:
            raise ValueError("追尾logの候補/場/順序が重複")
        saved[key] = row
    audit.check("正式五候補順", [row["候補ID"] for row in result["結果"]], list(Y.OPERATIONS))
    pairs = [(row["場"], row["候補ID"]) for row in details]
    audit.check("場候補一意", len(pairs), len(set(pairs)))
    S.compare_keys(audit, "全5x66", set(pairs), {(entry["session"], cid) for entry in manifest["entries"] for cid in Y.OPERATIONS})
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
        print(json.dumps({"場": entry["session"], "独立追尾": "全五X0/XF/費用起動/全線/fill固定役割", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
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
        "コードSHA256": initial, "依存コードSHA256": Y.dependency_pins(), "独立追尾補助SHA256": V.sha(EXIT_HELPER), "独立旧追尾補助SHA256": V.sha(OLD_EXIT_HELPER),
        "結果SHA256": V.sha(study / "結果.json"), "条件SHA256": V.sha(study / "条件.json"),
        "入力台帳SHA256": V.sha(study / "入力台帳.json"), "参照入力台帳SHA256": V.sha(resolved),
        "解決入力台帳SHA256": V.sha(resolved), "入口参照SHA256": V.sha(study / "入口参照.json"),
        "対照参照SHA256": V.sha(study / "対照参照.json"), "主準備SHA256": V.sha(work / "準備点検.json"),
        "全運用詳細展開SHA256": detail_sha, "追尾展開SHA256": log_sha, "通常線更新展開SHA256": log_sha,
        "入口事例展開SHA256": case_sha, "共有入口事例展開SHA256": state["共有入口事例展開SHA256"],
        "状態独立確認SHA256": V.sha(work / "状態独立確認.json"),
        "検証範囲": "旧21独立A5と固定33独立現在費用後replay_costをread再用し、B0X0参考とB0/R1/T1/S1XFの全実保有BBOで起動/名目同値/MFE-D/非緩和/hard125/TP250/期限の最初返済要求・全snapshot・fill時固定役割を照合。",
        "限界": "保存実新規/返済区間は入力。旧共有反転ラベル/構造四採否/全実side原BBO直接先着は状態、新規受付・最初BBO/Decimalは別財務。未解消時は完結属性/確定額を作らずEOF要求までの保有線と保存未解消数を区別する。"}
    (work / "追尾独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "対象完結取引数", "保存追尾行数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """root正式完了後の明示追尾監査だけを起動する。

    引数: なし。--study/--work/--実行許可を読む。
    返り値: None。無許可と不一致は非0終了。
    """
    parser = argparse.ArgumentParser(description="00037固定費用後起動とfill固定役割の独立追尾")
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
