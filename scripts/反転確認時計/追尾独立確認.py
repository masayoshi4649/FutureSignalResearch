"""00026のN0/N1/N2の全三運用を、既検証の独立追尾計算で原気配へ再照合する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00026_反転のSAR確認時刻と順行持続"
WORK = ROOT / "work/反転確認時計/00026"
INPUT = ROOT / "study/00008_外部研究を共通尺度へ移して探索/入力台帳.json"
STATE_CODE = Path(__file__).with_name("状態独立確認.py")
EXIT_HELPER = ROOT / "scripts/異種発動/追尾独立確認.py"


def helper(path: Path, name: str) -> Any:
    """元運用classではなく既検証の独立気配計算だけを読む。

    引数: path (Path) は独立補助、name (str) はモジュール識別名。
    返り値: Any は補助。21/26主運用をimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


X = helper(EXIT_HELPER, "反転確認時計の固定独立追尾")
V, S, B = X.V, X.S, X.B


def run(study: Path, work: Path) -> dict:
    """正式完了後だけ全三候補の最初要求・MFE・役割・全追尾ログを検算する。

    引数: study/work (Path) は26正式先/作業先。
    返り値: dict は明示合否・対象数・指紋・範囲。新規受入/約定会計は主監査へ分ける。
    """
    if not (study / "結果.json").exists() or not (work / "状態独立確認.json").exists():
        raise ValueError("正式結果と状態独立確認の完了が必要")
    audit, manifest, formal = V.Audit(), V.read(INPUT), V.read(study / "結果.json")
    state = V.read(work / "状態独立確認.json")
    audit.check("状態独立確認成功", state["全件一致"], True)
    audit.check("状態独立コード", state["コードSHA256"], V.sha(STATE_CODE))
    details, detail_sha = S.compressed_rows(work / "全運用詳細.jsonl.gz")
    logs, log_sha = S.compressed_rows(work / "追尾.jsonl.gz")
    cases, case_sha = S.compressed_rows(work / "入口事例.jsonl.gz")
    audit.check("入口事例SHA", case_sha, state["入口事例展開SHA256"])
    signals = {r["イベントID"]: {"atr": r["atr"], "役割": r["役割"]} for r in cases}
    grouped, saved = defaultdict(list), {}
    for d in details:
        grouped[d["場"]].append(d)
    for r in logs:
        key = r["場"], r["候補ID"], r["順序"]
        if key in saved:
            raise ValueError("追尾logキー重複")
        saved[key] = r
    candidates = [r["候補ID"] for r in formal["結果"]]
    audit.check("全三候補", len(candidates), 3)
    pairs = [(d["場"], d["候補ID"]) for d in details]
    audit.check("場候補一意", len(pairs), len(set(pairs)))
    S.compare_keys(audit, "全3×65", set(pairs), {(e["session"], cid) for e in manifest["entries"] for cid in candidates})
    expected, totals, summaries = {}, Counter(), []
    for entry in manifest["entries"]:
        loaded = B.load(entry)
        quotes = loaded[1]
        del loaded
        for detail in grouped[entry["session"]]:
            rows, counts = X.replay(detail, quotes, signals, audit)
            expected.update({(r["場"], r["候補ID"], r["順序"]): r for r in rows})
            totals.update(counts)
            summaries.append({"場": entry["session"], "候補ID": detail["候補ID"],
                "対象完結取引数": len(detail["取引"]), "追尾行数": len(rows)})
        print(json.dumps({"場": entry["session"], "独立確認": "全3最初要求・追尾・固定役割",
            "現時点不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    S.compare_keys(audit, "全追尾log原順集合", set(saved), set(expected))
    for key in saved.keys() & expected.keys():
        audit.check(f"追尾{key}", saved[key], expected[key])
    count = sum(len(d["取引"]) for d in details)
    audit.check("正式全完結数", count, sum(r[p]["運用"]["完結取引数"] for r in formal["結果"] for p in
        ("学習", "条件選択", "後続検査")))
    proof = {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches, "不一致": audit.errors,
        "対象場候補数": len(details), "対象完結取引数": count, "保存追尾行数": len(logs), "独立追尾行数": len(expected),
        "保存通常線行数": len(logs), "独立動作数": dict(totals), "場候補別": summaries,
        "コードSHA256": V.sha(Path(__file__)), "結果SHA256": V.sha(study / "結果.json"), "入力台帳SHA256": V.sha(INPUT),
        "独立追尾補助SHA256": V.sha(EXIT_HELPER), "全運用詳細展開SHA256": detail_sha,
        "追尾展開SHA256": log_sha, "通常線更新展開SHA256": log_sha, "入口事例展開SHA256": case_sha,
        "状態独立確認SHA256": V.sha(work / "状態独立確認.json"),
        "検証範囲": "全三X0の実保有区間を固定し、原cacheの全正常BBOと期限からhard125/TP250/A5追尾/期限の最初要求を再計算。独立済み21追尾helperを読み取り再用し、入口ATR距離/呼値丸め/非緩和/最低同値/実起動key・pending中MFEのみ更新・役割fill固定・起動後純赤字と全追尾snapshot/順序を照合する。",
        "限界": "21/26主運用classをimportして自己再生する監査ではない。保存実新規/実返済区間は入力であり、新規受入/一秒後BBO約定/会計/先着は主監査へ分離。最低同値の設定は実同値約定や費用後非赤字を保証しない。原板全本文の再抽出はしない。"}
    (work / "追尾独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: proof[k] for k in ("全件一致", "照合項目数", "不一致数", "対象完結取引数", "保存追尾行数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """正式完了通知後だけ全量監査を開始する。

    引数: なし。--study/--work/--実行許可を読む。
    返り値: None。不一致時は非0終了。
    """
    parser = argparse.ArgumentParser(description="00026固定A5追尾の原気配独立確認")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--実行許可", action="store_true")
    args = parser.parse_args()
    if not args.実行許可:
        parser.error("正式再生完了通知後に --実行許可 を指定してください")
    if not run(args.study.resolve(), args.work.resolve())["全件一致"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
