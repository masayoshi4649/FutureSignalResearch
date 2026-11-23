"""00030のP0/P1の全二運用を、既検証の独立追尾計算で原気配へ再照合する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00030_価格突破とBB幅と方向頻度"
WORK = ROOT / "work/PSY突破/00030"
INPUT = STUDY / "入力台帳.json"
STATE_CODE = Path(__file__).with_name("状態独立確認.py")
EXIT_HELPER = ROOT / "scripts/異種発動/追尾独立確認.py"


def helper(path: Path, name: str) -> Any:
    """元運用classではなく既検証の独立気配計算だけを読む。

    引数: path (Path) は独立補助、name (str) はモジュール識別名。
    返り値: Any は補助。21/30主運用をimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


X = helper(EXIT_HELPER, "PSY突破の固定独立追尾")
V, S, B = X.V, X.S, X.B


def run(study: Path, work: Path) -> dict:
    """正式完了後だけ全二候補の最初要求・MFE・役割・全追尾ログを検算する。

    引数: study/work (Path) は30正式先/作業先。
    返り値: dict は明示合否・対象数・指紋・範囲。新規受入/約定会計は主監査へ分ける。
    """
    if not (study / "結果.json").exists() or not (work / "状態独立確認.json").exists():
        raise ValueError("正式結果と状態独立確認の完了が必要")
    manifest_path = study / "入力台帳.json"
    reference = V.read(manifest_path)
    resolved_path = (study / reference["参照"]).resolve()
    expected_path = ROOT / "study/00028_基準線復帰と上位一目の方向/入力台帳.json"
    if resolved_path != expected_path or V.sha(resolved_path) != reference["SHA256"]:
        raise ValueError("固定28の既使用66場だけを参照します")
    audit, manifest, formal = V.Audit(), V.read(resolved_path), V.read(study / "結果.json")
    state = V.read(work / "状態独立確認.json")
    audit.check("状態独立確認成功", state["全件一致"], True)
    audit.check("状態独立コード", state["コードSHA256"], V.sha(STATE_CODE))
    audit.check("状態入力台帳", state["入力台帳SHA256"], V.sha(manifest_path))
    audit.check("状態解決入力台帳", state["解決入力台帳SHA256"], V.sha(resolved_path))
    audit.check("状態結果", state["結果SHA256"], V.sha(study / "結果.json"))
    details, detail_sha = S.compressed_rows(work / "全運用詳細.jsonl.gz")
    logs, log_sha = S.compressed_rows(work / "追尾.jsonl.gz")
    cases, case_sha = S.compressed_rows(work / "入口事例.jsonl.gz")
    audit.check("入口事例SHA", case_sha, state["入口事例展開SHA256"])
    audit.check("全運用詳細SHA", detail_sha, state["全運用詳細展開SHA256"])
    audit.check("追尾SHA", log_sha, state["追尾展開SHA256"])
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
    audit.check("全二候補", candidates, ["3分_" + policy + "_X0" for policy in ("P0", "P1")])
    audit.check("既使用入力66場", len(manifest["entries"]), 66)
    pairs = [(d["場"], d["候補ID"]) for d in details]
    audit.check("場候補一意", len(pairs), len(set(pairs)))
    S.compare_keys(audit, "全2×66", set(pairs), {(e["session"], cid) for e in manifest["entries"] for cid in candidates})
    if audit.mismatches:
        raise ValueError("状態/入力/保存物の参照が異なるためcacheを開く前に停止")
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
        print(json.dumps({"場": entry["session"], "独立確認": "全2最初要求・追尾・固定役割",
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
        "コードSHA256": V.sha(Path(__file__)), "結果SHA256": V.sha(study / "結果.json"), "入力台帳SHA256": V.sha(manifest_path),
        "解決入力台帳SHA256": V.sha(resolved_path),
        "参照入力台帳SHA256": V.sha(resolved_path),
        "独立追尾補助SHA256": V.sha(EXIT_HELPER), "全運用詳細展開SHA256": detail_sha,
        "追尾展開SHA256": log_sha, "通常線更新展開SHA256": log_sha, "入口事例展開SHA256": case_sha,
        "状態独立確認SHA256": V.sha(work / "状態独立確認.json"),
        "検証範囲": "全二X0の実保有区間を固定し、原cacheの全正常BBOと期限からhard125/TP250/A5追尾/期限の最初要求を再計算。独立済み21追尾helperを読み取り再用し、入口ATR距離/呼値丸め/非緩和/最低同値/実起動key・pending中MFEのみ更新・役割fill固定・起動後純赤字と全追尾snapshot/順序を照合する。",
        "限界": "21/30主運用classをimportして自己再生する監査ではない。保存実新規/実返済区間は入力であり、新規受入/一秒後BBO約定/会計/先着は主監査へ分離。最低同値の設定は実同値約定や費用後非赤字を保証しない。原板全本文の再抽出はしない。"}
    (work / "追尾独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: proof[k] for k in ("全件一致", "照合項目数", "不一致数", "対象完結取引数", "保存追尾行数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """正式完了通知後だけ全量監査を開始する。

    引数: なし。--study/--work/--実行許可を読む。
    返り値: None。不一致時は非0終了。
    """
    parser = argparse.ArgumentParser(description="00030固定A5追尾の原気配独立確認")
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
