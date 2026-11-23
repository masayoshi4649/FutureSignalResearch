"""22の全先着・九運用会計と、別計算した指標/追尾の証拠を接続する。"""

import argparse
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00022_ADXと上位BB幅の変化による局面切替"
WORK = ROOT / "work/局面変化/00022"


def load(path: Path, name: str) -> Any:
    """固定の独立会計補助だけを読む。

    引数: path(Path)は補助、name(str)は識別名。
    返り値: Anyはモジュール。22の指標/入口/運用は再実行しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


F = load(ROOT / "scripts/局面切替/独立監査.py", "異種発動の既検証会計")
H, U, A, PERIODS = F.H, F.U, F.A, F.PERIODS


def metrics(rows: list[dict]) -> dict:
    """独立会計へ追尾/役割を集計し、今回使わない通常VWAP項目を除く。

    引数: rows(list[dict])は同じ候補/期間の独立会計。
    返り値: dictは22正式集計へ対応する値。
    """
    values = F.operation_metrics(rows)
    for field in ("通常VWAP返済数", "VWAP起算失効返済数", "通常線更新回数"):
        del values[field]
    return values


def viewer(rows: list[dict], api: str, audit: Any) -> dict:
    """事前固定の三分三戦略をViewerの価格/約定/損益と照合する。

    引数: rows(list[dict])は独立会計、api(str)は接続先、audit(Any)は照合先。
    返り値: dictは三資源のAPI検査。画像を追加保存しない。
    """
    helper = load(ROOT / "scripts/複合検証/Viewer照合.py", "異種発動の表示確認")
    resources = {(r["method_id"], r["session"]): r for r in H.read(STUDY / "一覧.resources.json")["resources"]}
    body, _ = helper.fetch(api + "/api/resources?" + helper.urlencode({"catalog_path": (STUDY / "一覧.resources.json").relative_to(ROOT).as_posix()}))
    audit.check("Viewer資源全集合", {r["id"] for r in json.loads(body)["resources"]}, {r["id"] for r in resources.values()})
    checks = []
    for strategy in ("A0", "S1", "S2"):
        cid = "3分_" + strategy + "_X0"
        own = [r for r in rows if r["候補ID"] == cid]
        selected = sorted(own, key=lambda r: (-abs(r["観測現金増減円"]), r["場"]))[0]
        adapted = {"銘柄": "NK225", "場": selected["場"], "手法": cid,
                   "純損益円": float(selected["観測現金増減円"]), "取引数": selected["完結取引数"]}
        checked = helper.check_one(api, STUDY, adapted, resources[cid, selected["場"]], "事前三分三戦略の代表", False)
        checked.update(観測経路注意=selected["観測経路注意"], 確定対象純損益円=selected["確定対象純損益円"])
        checks.append(checked)
    with urlopen(api + "/api/info", timeout=10) as stream:
        info = json.load(stream)
    return {"確認日時": datetime.now(U.HELPER.JST).isoformat(), "接続先": api, "API情報": info,
        "設定": "work/viewer/conf/viewer.toml", "WindowStyle": "Hidden", "照合": checks, "追加PNG数": 0,
        "Viewer実行コピーSHA256": U.sha(ROOT / "work/viewer/session-trade-viewer.exe"),
        "指定配布版SHA256": U.sha(ROOT.parent / "SessionTradeViewer/dist/windows-amd64/SessionTradeViewer/session-trade-viewer.exe"),
        "代表規則": "事前固定三分A0/S1/S2。各候補の最大絶対観測現金増減場、同値は場順。表示用選択を売買採用に使わない。"}


# ----------------------------------------
# 先着は各発動への仮参加、実運用は一建玉の約定会計として別に検算する。

def run(api: str | None) -> dict:
    """全9×65を検算し、別コードの二証明が揃ったとき正式監査を保存する。

    引数: api(str|None)はViewer接続先。
    返り値: dictは明示合否・件数・範囲。主条件/結果は変更しない。
    """
    audit = U.Audit()
    config, result, fixed = H.read(STUDY / "条件.json"), H.read(STUDY / "結果.json"), H.read(STUDY / "固定.json")
    for name, expected in fixed["ファイルSHA256"].items():
        audit.check("実行前固定後SHA:" + name, U.sha(ROOT / name), expected)
    pointer = H.read(STUDY / "入力台帳.json")
    manifest = (STUDY / pointer["参照"]).resolve()
    audit.check("入力台帳指紋", U.sha(manifest), pointer["SHA256"])
    entries = {e["session"]: e for e in H.read(manifest)["entries"]}
    stats = {}
    for item in H.read(STUDY / "作業成果物.json")["ファイル"]:
        path = ROOT / item["パス"]
        digest, count = F.content_stats(path)
        audit.check("作業展開SHA:" + path.name, digest, item["展開内容SHA256"])
        stats[path.name] = digest, count
    raw, detail_sha = H.rows(WORK / "全運用詳細.jsonl.gz")
    cases, case_sha = H.rows(WORK / "入口事例.jsonl.gz")
    shadows, shadow_sha = H.rows(WORK / "全複合shadow.jsonl.gz")
    logs, log_sha = H.rows(WORK / "追尾.jsonl.gz")
    canonical = {r["発動ID"]: r for r in shadows}
    display_differences = {}
    for r in cases:
        correct = canonical[r["発動ID"]]["戦略判定"]
        audit.check(r["イベントID"] + ":自己複合判定", r["複合判定"], correct[r["戦略"]])
        audit.check(r["イベントID"] + ":自己戦略表示", r["戦略判定"][r["戦略"]], correct[r["戦略"]])
        for policy, shown in r["戦略判定"].items():
            if shown != correct[policy]:
                audit.check(r["イベントID"] + ":表示差は他戦略だけ", policy != r["戦略"], True)
                display_differences[r["イベントID"], policy] = {"イベントID": r["イベントID"], "実選択戦略": r["戦略"],
                    "表示戦略": policy, "採用case内表示": shown, "shadow最終採否": correct[policy]}
    audit.check("全caseの全戦略表示がcanonicalと同値", len(display_differences), 0)
    normalized = [{**r, "上位足終了秒": r["局面足終了秒"], "上位確認秒": r["局面公開秒"], "上位確認行": r["局面公開原行"]} for r in cases]
    entrance = H.entry_audit(normalized, result, entries, config, audit)
    quote_labels = {}
    for r in shadows:
        session = r["場"]
        if session not in quote_labels:
            e = entries[session]
            quote_labels[session] = H.L.load_quotes(ROOT / "work/複合検証" / e["cache_path"], e)[0]
        _, _, cutoff, deadline = H.L.session_times(session)
        expected = H.L.label_direct(quote_labels[session], r["要求時計秒"], cutoff, deadline, r["side"], adverse=125, favorable=250)
        for field, value in expected.items():
            audit.check(r["発動ID"] + ":全発動先着:" + field, r[field], value)
    entrance.update(全発動直接先着件数=len(shadows), 限界="原気配から全保存発動/採用入口の先着を直接検算。発動漏れ/数式/公開時点は別の状態独立確認で全再構成。一建玉の実参加と区別する。")
    updates = {}
    for r in logs:
        key = r["候補ID"], r["場"]
        updates[key] = updates.get(key, 0) + (r["動作"] == "追尾線更新")
    event_map = {(r["入口ID"], r["場"], r["イベントID"]): r for r in cases}
    details, quotes, rows = {}, {}, []
    for d in raw:
        cid, session = d["候補ID"], d["場"]
        if (cid, session) in details:
            raise ValueError("候補・場の重複")
        details[cid, session] = d
        source = cid.rsplit("_", 1)[0]
        if session not in quotes:
            quotes[session] = U.quotes(entries[session], True)
        q = quotes[session]
        row = U.audit_session(d, q, audit)
        row.update(A.drawdown(d, q, audit), 通常線更新回数=0, 追尾線更新回数=updates.get((cid, session), 0))
        F.trade_path(d, q, audit)
        audit.check(cid + session + ":追尾更新数", d["品質"]["追尾線更新回数"], row["追尾線更新回数"])
        audit.check(cid + session + ":終了建玉0", row["終了建玉"], 0)
        audit.check(cid + session + ":返済待機0", row["終了返済待機"], 0)
        audit.check(cid + session + ":全入口受渡集合", {s["イベントID"] for s in d["入口取扱"]},
                    {r["イベントID"] for r in cases if r["入口ID"] == source and r["場"] == session})
        for s in d["入口取扱"]:
            r = event_map[source, session, s["イベントID"]]
            for field in ("要求時計秒", "要求原板行", "side", "確認遅延秒"):
                audit.check(cid + s["イベントID"] + ":受渡:" + field, s[field], r[field])
        for t in d["取引"]:
            audit.check(cid + t["建玉ID"] + ":実新規役割固定", t["入口役割"], event_map[source, session, t["入口イベントID"]]["役割"])
            audit.check(cid + t["建玉ID"] + ":通常出口不使用", t["通常出口使用"], False)
        rows.append(row)
    audit.check("9×65全運用", len(details), 585)
    csv = U.table(STUDY / "全候補_場別.csv")
    table = {(r["手法"], r["場"]): r for r in csv}
    audit.check("場別CSV重複なし", len(table), len(csv))
    audit.check("場別CSV全集合", set(table), set(details))
    for key, d in details.items():
        for field, value in d["品質"].items():
            audit.check(str(key) + ":場別CSV:" + field, table[key][field], value)
    aggregates, qualified_count = [], 0
    for candidate in result["結果"]:
        cid, source = candidate["候補ID"], candidate["入口"]["入口ID"]
        support, target = entrance["支持"][source]
        audit.check(cid + ":入口支持コピー", candidate["入口支持"], support)
        audit.check(cid + ":入口目標コピー", candidate["70目標"], target)
        periods = {}
        for period in PERIODS:
            own = [r for r in rows if r["候補ID"] == cid and r["期間"] == period]
            audit.check(cid + period + ":全場数", len(own), {"学習": 40, "条件選択": 24, "後続検査": 1}[period])
            values = metrics(own)
            for field, value in values.items():
                audit.check(cid + period + ":期間会計:" + field, candidate[period]["運用"][field], value)
            shared = next(r for r in result["入口評価"] if r["入口ID"] == source)
            for field, value in shared[period].items():
                audit.check(cid + period + ":入口不変:" + field, candidate[period]["入口"][field], value)
            periods[period] = values
            aggregates.append({"候補ID": cid, "期間": period, **values})
        qualified = all(all(periods[p][field] >= minimum for field, minimum in limits.items())
                        and periods[p]["品質注意場数"] == 0 and periods[p]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        audit.check(cid + ":費用資格", candidate["費用資格"], qualified)
        qualified_count += qualified
    audit.check("費用資格数", result["費用資格数"], qualified_count)
    audit.check("事前三分三表示", result["表示固定ID"], [f"3分_{p}_X0" for p in ("A0", "S1", "S2")])
    files = U.artifacts(STUDY, details, result["表示固定ID"], entries, audit)
    if api:
        H.write(STUDY / "Viewer照合.json", viewer(rows, api, audit))
    proofs = {}
    for name in ("状態独立確認", "追尾独立確認"):
        path = WORK / (name + ".json")
        if not path.exists():
            continue
        proof = H.read(path)
        audit.check(name + ":全件一致", proof["全件一致"], True)
        audit.check(name + ":実装版", proof["コードSHA256"], U.sha(ROOT / "scripts/局面変化" / (name + ".py")))
        audit.check(name + ":入力版", proof["入力台帳SHA256"], U.sha(manifest))
        audit.check(name + ":入口版", proof["入口事例展開SHA256"], case_sha)
        if name == "状態独立確認":
            for filename, hash_key, count_key in (("全複合context.jsonl.gz", "全複合context展開SHA256", "保存context数"),
                ("全局面.jsonl.gz", "全局面展開SHA256", "保存局面数"), ("上位足.jsonl.gz", "上位足展開SHA256", "保存上位足数"),
                ("全複合shadow.jsonl.gz", "全複合shadow展開SHA256", "保存shadow数"), ("入口事例.jsonl.gz", "入口事例展開SHA256", "保存入口数")):
                audit.check(name + ":出典:" + hash_key, proof[hash_key], stats[filename][0])
                audit.check(name + ":全集合:" + count_key, proof[count_key], stats[filename][1])
        else:
            for key, expected in (("全運用詳細展開SHA256", detail_sha), ("追尾展開SHA256", log_sha), ("保存追尾行数", len(logs)),
                                  ("対象完結取引数", sum(len(d["取引"]) for d in raw)), ("結果SHA256", U.sha(STUDY / "結果.json")),
                                  ("状態独立確認SHA256", U.sha(WORK / "状態独立確認.json"))):
                audit.check(name + ":対象版:" + key, proof[key], expected)
        proofs[name] = proof
        H.write(STUDY / (name + ".json"), proof)
    complete = len(proofs) == 2
    output = {"全件一致": not audit.errors, "照合項目数": audit.count, "不一致数": len(audit.errors), "不一致": audit.errors,
        "確認日時": datetime.now(U.HELPER.JST).isoformat(), "全65場既使用": True, "状態確認未完": "状態独立確認" not in proofs,
        "追尾確認未完": "追尾独立確認" not in proofs, "コードSHA256": U.sha(Path(__file__)), "結果SHA256": U.sha(STUDY / "結果.json"),
        "入口": entrance, "運用期間別": aggregates, "正式資源": files, "別計算証明": proofs,
        "表示属性注意": bool(display_differences), "他戦略表示不一致数": len(display_differences),
        "全case全戦略属性一致": not display_differences,
        "一致の範囲": "全先着/会計・数値/全caseの全戦略採否/入口集合/追尾を検算。新15分pair/分類と元発動同値は別の状態独立確認で全再構成。",
        "Viewer記録": "Viewer照合.json" if api else None,
        "独立補助SHA256": {p: U.sha(ROOT / p) for p in ("scripts/局面切替/独立監査.py", "scripts/テクニカル循環/独立監査.py",
            "scripts/利益回収/運用独立監査.py", "scripts/外部探索/運用独立監査.py", "scripts/入口分析/独立照合.py")},
        "会計範囲": "全発動shadow/全9入口先着を正常気配から直接検算。9×65のDecimal注文/約定/帰属/単一建玉/待機/費用/品質、保存MFE・MAE/DD/最低同値追尾設定/CSV/全期間支持を検算。",
        "別証明範囲": "状態は全価格足とBB/MACD/SlowK/ATR/ADX/DI・全発動/採否、追尾は全実保有区間の最初要求・起動/非緩和・役割固定を別計算。件数は主監査へ加算しない。",
        "限界": "全65場は既使用で未来の未見成績ではない。DDは各場0開始/返済費用込み観測時価の最大場内下落で、期間を接合した累積DDではない。価格時計は実受信時計とは異なる。"}
    H.write(STUDY / "独立監査.json" if complete else WORK / "会計監査_途中.json", output)
    print(json.dumps({k: output[k] for k in ("全件一致", "照合項目数", "不一致数", "状態確認未完", "追尾確認未完")}, ensure_ascii=False))
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="00022全発動と一建玉会計の独立監査")
    parser.add_argument("--api-base")
    args = parser.parse_args()
    if not run(args.api_base.rstrip("/") if args.api_base else None)["全件一致"]:
        raise SystemExit(1)
