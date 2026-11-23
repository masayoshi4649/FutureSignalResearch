"""00035の全三XFを独立費用起動/全線と元登録・到達回復出典へ照合する。"""

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
STUDY = ROOT / "study/00035_CCI突破の到達後回復"
WORK = ROOT / "work/回復監視/00035"
STATE_CODE = Path(__file__).with_name("状態独立確認.py")
EXIT_HELPER = ROOT / "scripts/終値位置/追尾独立確認.py"


def helper(path: Path, name: str) -> Any:
    """同階層の独立状態と旧独立追尾だけを読む。

    引数: path(Path)は補助、name(str)はモジュール名。
    返り値: Anyはモジュール。35主入口・運用をimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


Y = helper(STATE_CODE, "回復監視の独立状態")
X = helper(EXIT_HELPER, "回復監視の固定33独立費用追尾")
V, S, B = X.V, X.S, X.B
CONTEXT_FIELDS = ("元登録時計秒", "元登録原板行", "絶対失効時計秒", "監視水準価格", "監視登録出典",
    "初回到達出典", "初回回復出典", "新規実効TTL秒")


def context(source: dict, quotes: dict, cutoff: float, force: float) -> dict:
    """元登録と原正常BBOから実回復注文の全出典を別生成する。

    引数: source/quotes(dict)は登録/原列、cutoff/force(float)は停止/強制。
    返り値: dictは元期限と初回復から求める8列。保存監視や保存注文を期待値へコピーしない。
    """
    observed = Y.observation(quotes, source, cutoff, force)
    requested = observed["新規要求時計秒"]
    if requested is None:
        raise ValueError("観測から実新規を要求できない登録です")
    return {"元登録時計秒": source["要求時計秒"], "元登録原板行": source["要求原板行"],
        "絶対失効時計秒": observed["絶対失効時計秒"], "監視水準価格": source["新規指値価格"],
        "監視登録出典": deepcopy(source["指値根拠"]), "初回到達出典": deepcopy(observed["初回到達出典"]),
        "初回回復出典": deepcopy(observed["初回回復出典"]),
        "新規実効TTL秒": observed["絶対失効時計秒"] - requested}


def replay(detail: dict, quotes: list[dict], signals: dict[str, dict], audit: Any,
           bounds: tuple | None = None, config: dict | None = None) -> tuple[list[dict], dict]:
    """実保有から固定XFを別走査し、各方針の全出典も省略せず比較する。

    引数: detail(dict)は一場、quotes(list[dict])は原正常板、signals(dict)は検証済純入口、audit(Any)は比較、bounds(tuple|None)は開始/終了/強制、config(dict|None)は運用。
    返り値: tuple[list[dict],dict]は全独立追尾log/件数。新規受付・監視の機械は状態proofへ分離する。
    """
    if detail["候補ID"] not in Y.OPERATIONS:
        raise ValueError("固定三方針だけです")
    rows, counts = X.replay_cost(detail, quotes, signals, audit, bounds, config)
    orders = {row["注文ID"]: row for row in detail["注文"]}
    events = {row["入口イベントID"] for row in detail["注文"] if row["区分"] == "新規"}
    if detail["候補ID"] == "3分_E3_XF":
        q = {name: [row[name] for row in quotes] for name in ("now", "line", "bid", "ask")}
        _, _, cutoff, force = Y.S.G.times(detail["場"]) if bounds is None else (bounds[0], bounds[1], bounds[1], bounds[2])
        metadata = {event: context(signals[event], q, cutoff, force) for event in events}
    else:
        metadata = {event: {"新規指値価格": signals[event]["新規指値価格"], "指値根拠": deepcopy(signals[event]["指値根拠"])}
            for event in events}
    for row in rows:
        position = row["建玉"]
        if position is not None:
            event = position["event_id"]
        elif row["動作"] == "注文要求" and row.get("区分") == "新規":
            event = orders[row["注文ID"]]["入口イベントID"]
        else:
            continue
        row.update(deepcopy(metadata[event]))
    for trade in detail["取引"]:
        event = trade["入口イベントID"]
        for field, value in metadata[event].items():
            audit.check(detail["場"] + trade["建玉ID"] + ":" + field, trade[field], value)
    return rows, counts


# ----------------------------------------
# 新規/監視/絶対寿命は状態、最初返済要求/全線は追尾、約定/Decimalは財務へ分離する。


def run(study: Path, work: Path) -> dict:
    """正式状態成功後に全三XFの最初返済要求・全線・到達回復出典を検算する。

    引数: study/work (Path) は35保存先。
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
    audit.check("純全3登録数", len(signals), state["原C0登録数"] * 3)
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
    audit.check("正式三候補順", [row["候補ID"] for row in result["結果"]], list(Y.OPERATIONS))
    pairs = [(row["場"], row["候補ID"]) for row in details]
    audit.check("場候補一意", len(pairs), len(set(pairs)))
    S.compare_keys(audit, "全3x66", set(pairs), {(entry["session"], cid) for entry in manifest["entries"] for cid in Y.OPERATIONS})
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
        print(json.dumps({"場": entry["session"], "独立追尾": "全三XF/費用起動/全線/到達回復出典", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
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
        "検証範囲": "固定33の独立費用起動replay_costをread再用し、全三運用の実新規から実返済/場末までの現在費用後strict正・起動出典・名目同値/MFE-D非緩和・hard125/TP250/期限の最初要求と全線を検算。各方針の新規request/保有/終了logとtradeへ追加した固定指値又は元登録/初到達/初回回復/実効TTL出典も除外せず厳密照合。",
        "限界": "保存実新規/返済区間は入力。純2403先着・実新規監視受付/絶対寿命/最初新規は状態の別機械、返済約定とDecimalは別財務。未解消時は完結属性/確定額を作らずEOF要求までの保有線と保存未解消数を区別する。"}
    (work / "追尾独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "対象完結取引数", "保存追尾行数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """root正式完了後の明示追尾監査だけを起動する。

    引数: なし。--study/--work/--実行許可を読む。
    返り値: None。無許可と不一致は非0終了。
    """
    parser = argparse.ArgumentParser(description="00035固定費用後起動と到達回復出典の独立追尾")
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
