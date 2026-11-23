"""00019のVWAP12入口・36運用・固定X0運用を、気配先着と独立会計から監査する。"""

from __future__ import annotations

import argparse
from datetime import datetime
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
from typing import Any
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00019_VWAP復帰の入口と通常出口"
WORK = ROOT / "work/VWAP復帰/00019"


def load(path: Path, name: str) -> Any:
    """独立監査または表示の補助だけを読み込む。

    引数: path (Path) はコード、name (str) は識別名。
    返り値: Any はモジュール。入口/検証/運用の数値エンジンは再実行しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


H = load(ROOT / "scripts/テクニカル循環/独立監査.py", "VWAP復帰の共通独立監査")
A, U, PERIODS = H.A, H.U, H.PERIODS


def operation_metrics(rows: list[dict]) -> dict:
    """基礎会計へ固定出口の場内DDとMFE到達後損失を集計する。

    引数: rows (list[dict]) は同じ候補と期間の独立場別会計。
    返り値: dict は保存期間集計に対応する値。場を接合した累積DDではない。
    """
    result, trades = U.aggregate(rows), [t for r in rows for t in r["取引"]]
    result.update(期間内最大場内DD円=max((r["観測含み込み最大DD円"] for r in rows), default=0),
                  最悪場内時価円=min((r["観測最悪時価円"] for r in rows), default=0),
                  基準赤字取引数=sum(t["基準純損益円"] < 0 for t in trades),
                  利確要求返済数=sum(t["返済理由"] == "利確" for t in trades),
                  初期125保護返済数=sum(t["返済理由"] == "保護" for t in trades),
                  活動場赤字率=result["赤字場数"] / result["活動場数"] if result["活動場数"] else None)
    result.update(通常VWAP返済数=sum(t["返済理由"] in ("VWAP通常逆抜け", "VWAP通常到達") for t in trades),
                  VWAP起算失効返済数=sum(t["返済理由"] == "VWAP起算失効" for t in trades),
                  通常線更新回数=sum(r["通常線更新回数"] for r in rows))
    for limit in (20, 50, 100):
        reached = [t for t in trades if t["観測最大順行pt"] >= limit]
        result[f"{limit}pt到達取引"] = len(reached)
        result[f"{limit}pt後純赤字"] = sum(t["基準純損益円"] < 0 for t in reached)
    return result


def content_stats(path: Path) -> tuple[str, int]:
    """大きい足参照等を展開せず、gzip本文の指紋と行数だけ計算する。

    引数: path (Path) は作業gzip。
    返り値: tuple[str,int] は展開SHA256と非空JSONL行数。
    """
    digest, count = hashlib.sha256(), 0
    with gzip.open(path, "rb") as stream:
        for line in stream:
            digest.update(line)
            count += bool(line.strip())
    return digest.hexdigest(), count


# ----------------------------------------
# 表示代表は実行前固定の3分二役割。表示用の場選択を戦略採用へ使わない。

def trade_path(detail: dict, q: dict, audit: Any) -> None:
    """全運用の保有MFE/MAEと、固定X0の最初要求を直接気配で検算する。

    引数: detail(dict)は運用明細、q(dict)は正常気配、audit(Any)は照合先。
    返り値: None。通常出口の最初要求は別の全件監査へ接続する。
    """
    for trade in detail["取引"]:
        name = detail["候補ID"] + trade["建玉ID"]
        first, last = q["at"][trade["新規原板行"]], q["at"][trade["返済原板行"]]
        side = 1 if trade["方向"] == "買い" else -1
        marks = q["bid"] if side == 1 else q["ask"]
        differences = side * (marks[first:last + 1] - trade["新規価格"])
        audit.check(name + ":直接MFE", trade["観測最大順行pt"], max(0, float(np.max(differences))))
        audit.check(name + ":直接MAE", trade["観測最大逆行pt"], max(0, float(-np.min(differences))))
        audit.check(name + ":全出口hardTP250維持", trade["固定利確使用"], True)
        if detail["候補ID"].endswith("_X0"):
            force = q["bounds"][3]
            hits = np.flatnonzero((q["now"][first:last + 1] < force) & ((differences <= -125) | (differences >= 250)))
            if len(hits):
                at = first + int(hits[0])
                expected = (float(q["now"][at]), int(q["line"][at]), "保護" if side * (marks[at] - trade["新規価格"]) <= -125 else "利確")
            else:
                expected = (force, 0, "期限")
            audit.check(name + ":X0最初の要求", (trade["返済要求時計秒"], trade["返済要求原板行"], trade["返済理由"]), expected)


# ----------------------------------------
# 両役割の表示固定3分で、同じ入口の出口三種をそれぞれ確認する。

def viewer(rows: list[dict], api: str, audit: Any) -> dict:
    """順行/反転の代表各場についてX0/X1/X2をAPI照合する。

    引数: rows(list[dict])は独立会計、api(str)は接続先、audit(Any)は照合先。
    返り値: dict は六資源の表示・会計。PNGは増やさない。
    """
    helper = load(ROOT / "scripts/複合検証/Viewer照合.py", "VWAP復帰の表示確認")
    resources = {(r["method_id"], r["session"]): r for r in H.read(STUDY / "一覧.resources.json")["resources"]}
    body, _ = helper.fetch(api + "/api/resources?" + helper.urlencode({"catalog_path": (STUDY / "一覧.resources.json").relative_to(ROOT).as_posix()}))
    audit.check("Viewer資源集合", {r["id"] for r in json.loads(body)["resources"]}, {r["id"] for r in resources.values()})
    checks = []
    for family in ("Q1", "Q2"):
        eligible = [r for r in rows if r["候補ID"].startswith("3分_" + family + "_") and (r["候補ID"], r["場"]) in resources]
        selected = sorted(eligible, key=lambda r: (-abs(r["観測現金増減円"]), r["候補ID"], r["場"]))[0]
        source = selected["候補ID"].rsplit("_", 1)[0]
        for policy in ("X0", "X1", "X2"):
            cid = source + "_" + policy
            row = next(r for r in rows if r["候補ID"] == cid and r["場"] == selected["場"])
            adapted = {"銘柄": "NK225", "場": row["場"], "手法": cid, "純損益円": float(row["観測現金増減円"]), "取引数": row["完結取引数"]}
            checked = helper.check_one(api, STUDY, adapted, resources[(cid, row["場"])], "順行/反転の同入口三出口", False)
            checked.update(観測経路注意=row["観測経路注意"], 確定対象純損益円=row["確定対象純損益円"])
            checks.append(checked)
    with urlopen(api + "/api/info", timeout=10) as stream:
        info = json.load(stream)
    return {"確認日時": datetime.now(U.HELPER.JST).isoformat(), "接続先": api, "API情報": info,
            "設定": "work/viewer/conf/viewer.toml", "WindowStyle": "Hidden", "照合": checks, "追加PNG数": 0,
            "Viewer実行コピーSHA256": U.sha(ROOT / "work/viewer/session-trade-viewer.exe"),
            "指定配布版SHA256": U.sha(ROOT.parent / "SessionTradeViewer/dist/windows-amd64/SessionTradeViewer/session-trade-viewer.exe"),
            "代表規則": "事前表示固定3分Q1/Q2について各最大絶対観測額（同値候補ID/場順）の同入口三出口を表示。事後表示で採用選択ではない。"}


def run(api: str | None) -> dict:
    """完成した19出力を検算し、状態独立確認後だけ正式な総合監査を保存する。

    引数: api (str|None) はViewer接続先。
    返り値: dict は明示合否・件数・範囲。原板と固定coreは変更しない。
    """
    audit = U.Audit()
    config, result, locked = H.read(STUDY / "条件.json"), H.read(STUDY / "結果.json"), H.read(STUDY / "固定.json")
    for path, expected in locked["ファイルSHA256"].items():
        audit.check("実行前固定後SHA:" + path, U.sha(ROOT / path), expected)
    pointer = H.read(STUDY / "入力台帳.json")
    manifest = (STUDY / pointer["参照"]).resolve()
    audit.check("参照台帳SHA", U.sha(manifest), pointer["SHA256"])
    entries = {e["session"]: e for e in H.read(manifest)["entries"]}
    raw, detailed_sha = H.rows(WORK / "全運用詳細.jsonl.gz")
    cases, case_sha = H.rows(WORK / "入口事例.jsonl.gz")
    foot_sha, foot_count = content_stats(WORK / "全足参照.jsonl.gz")
    price_sha, price_count = content_stats(WORK / "発動候補.jsonl.gz")
    normal_records, normal_sha = H.rows(WORK / "通常線更新.jsonl.gz")
    normal_count = len(normal_records)
    normal_updates = {}
    for record in normal_records:
        key = record["候補ID"], record["場"]
        normal_updates[key] = normal_updates.get(key, 0) + (record["動作"] == "通常線更新")
    contents = {str(WORK / "全運用詳細.jsonl.gz"): detailed_sha, str(WORK / "入口事例.jsonl.gz"): case_sha,
                str(WORK / "全足参照.jsonl.gz"): foot_sha, str(WORK / "発動候補.jsonl.gz"): price_sha, str(WORK / "通常線更新.jsonl.gz"): normal_sha}
    auxiliary = H.read(STUDY / "補助入力台帳.json")
    auxiliary_source = (STUDY / auxiliary["参照"]).resolve()
    audit.check("補助参照台帳SHA", U.sha(auxiliary_source), auxiliary["SHA256"])
    for item in H.read(STUDY / "作業成果物.json")["ファイル"]:
        audit.check("作業展開SHA:" + item["パス"], contents[str(ROOT / item["パス"])], item["展開内容SHA256"])
    entrance = H.entry_audit(cases, result, entries, config, audit)
    entrance["限界"] = "全保存入口の先着を正常気配から直接再判定。別の状態独立確認で原価格/補助cacheから全価格足/指標/固定18参照/Q1Q2の12発動集合を独立再構成する。全仮約定の先着は実運用の一建玉参加集合とは分ける。"
    details, cached, rows = {}, {}, []
    source_cases = {(r["入口ID"], r["場"], r["イベントID"]): r for r in cases}
    for d in raw:
        cid, session = d["候補ID"], d["場"]
        if (cid, session) in details:
            raise ValueError("候補・場が重複")
        details[(cid, session)] = d
        source = cid.rsplit("_", 1)[0]
        if session not in cached:
            cached[session] = U.quotes(entries[session], True)
        q = cached[session]
        row = U.audit_session(d, q, audit)
        row.update(A.drawdown(d, q, audit))
        trade_path(d, q, audit)
        row["通常線更新回数"] = normal_updates.get((cid, session), 0)
        audit.check(cid + session + ":通常線更新回数", d["品質"].get("通常線更新回数", 0), row["通常線更新回数"])
        audit.check(cid + session + ":終了建玉0", row["終了建玉"], 0)
        audit.check(cid + session + ":返済待機0", row["終了返済待機"], 0)
        audit.check(cid + session + ":純入口と取扱の集合",
                    {s["イベントID"] for s in d["入口取扱"]},
                    {r["イベントID"] for r in cases if r["入口ID"] == source and r["場"] == session})
        for s in d["入口取扱"]:
            r = source_cases[(source, session, s["イベントID"])]
            for field in ("要求時計秒", "要求原板行", "side", "確認遅延秒"):
                audit.check(cid + s["イベントID"] + ":入口受渡:" + field, s[field], r[field])
        rows.append(row)
    audit.check("36候補×65場", len(details), 2340)
    saved = U.table(STUDY / "全候補_場別.csv")
    indexed = {(r["手法"], r["場"]): r for r in saved}
    audit.check("場別CSV一意", len(indexed), len(saved))
    audit.check("場別CSV集合", set(indexed), set(details))
    for key, d in details.items():
        for field, value in d["品質"].items():
            audit.check(str(key) + ":場別CSV:" + field, indexed[key][field], value)
    aggregates, qualified_count = [], 0
    for candidate in result["結果"]:
        cid, source = candidate["候補ID"], candidate["入口"]["入口ID"]
        supported, target = entrance["支持"][source]
        audit.check(cid + ":入口支持コピー", candidate["入口支持"], supported)
        audit.check(cid + ":入口目標コピー", candidate["70目標"], target)
        periods = {}
        for period in PERIODS:
            own = [r for r in rows if r["候補ID"] == cid and r["期間"] == period]
            audit.check(cid + period + ":実行場数", len(own), {"学習": 40, "条件選択": 24, "後続検査": 1}[period])
            values = operation_metrics(own)
            for field, value in values.items():
                audit.check(cid + period + ":運用集計:" + field, candidate[period]["運用"][field], value)
            shared = next(e for e in result["入口評価"] if e["入口ID"] == source)
            for field, value in shared[period].items():
                audit.check(cid + period + ":入口結果コピー:" + field, candidate[period]["入口"][field], value)
            periods[period] = values
            aggregates.append({"候補ID": cid, "期間": period, **values})
        qualified = all(all(periods[p][field] >= minimum for field, minimum in limits.items())
                        and periods[p]["品質注意場数"] == 0 and periods[p]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        audit.check(cid + ":費用資格", candidate["費用資格"], qualified)
        qualified_count += qualified
    audit.check("費用資格数", result["費用資格数"], qualified_count)
    expected_ids = [f"{size}分_{family}_{extra}_{policy['出口ID']}" for size in (3,) for family in config["入口系統"] for extra in config["補助"] for policy in config["出口"]]
    audit.check("事前固定3分12表示で再順位なし", result["表示固定ID"], expected_ids)
    files = U.artifacts(STUDY, details, result["表示固定ID"], entries, audit)
    views = viewer(rows, api, audit) if api else None
    if views:
        H.write(STUDY / "Viewer照合.json", views)
    state_path = WORK / "状態独立確認.json"
    state_check = H.read(state_path) if state_path.exists() else None
    if state_check:
        audit.check("原価格からの状態独立再構成", state_check["全件一致"], True)
        for field, expected in (("コードSHA256", U.sha(ROOT/"scripts/VWAP復帰/状態独立確認.py")),
                                ("入力台帳SHA256", U.sha(manifest)),
                                ("補助入力台帳SHA256", U.sha(auxiliary_source)),
                                ("全足参照展開SHA256", foot_sha), ("発動候補展開SHA256", price_sha),
                                ("入口事例展開SHA256", case_sha),
                                ("保存参照足数", foot_count), ("保存発動候補数", price_count), ("保存入口数", len(cases))):
            audit.check("状態独立確認の対象と版:" + field, state_check[field], expected)
        H.write(STUDY / "状態独立確認.json", state_check)
    normal_path = WORK / "通常出口独立確認.json"
    normal_check = H.read(normal_path) if normal_path.exists() else None
    if normal_check:
        audit.check("通常出口の最初要求全件検算", normal_check["全件一致"], True)
        for field, expected in (("コードSHA256", U.sha(ROOT / "scripts/VWAP復帰/通常出口独立確認.py")),
                                ("結果SHA256", U.sha(STUDY / "結果.json")),
                                ("全運用詳細展開SHA256", detailed_sha), ("通常線更新展開SHA256", normal_sha),
                                ("入口事例展開SHA256", case_sha), ("全足参照展開SHA256", foot_sha),
                                ("保存通常線行数", normal_count),
                                ("対象完結取引数", sum(len(d["取引"]) for d in raw if not d["候補ID"].endswith("_X0")))):
            audit.check("通常出口監査の対象と版:" + field, normal_check[field], expected)
        H.write(STUDY / "通常出口独立確認.json", normal_check)
    complete = state_check is not None and normal_check is not None
    output = {"全件一致": not audit.errors, "照合項目数": audit.count, "不一致数": len(audit.errors), "不一致": audit.errors,
              "状態確認未完": state_check is None, "通常出口確認未完": normal_check is None, "確認日時": datetime.now(U.HELPER.JST).isoformat(),
              "コードSHA256": U.sha(Path(__file__)), "結果SHA256": U.sha(STUDY / "結果.json"), "全65場既使用": True,
              "固定後SHA変化件数": sum(e["項目"].startswith("実行前固定後SHA:") for e in audit.errors),
              "入口": entrance, "運用期間別": aggregates, "正式資源": files,
              "状態独立確認": {"参照": "状態独立確認.json", "照合項目数": state_check["照合項目数"],
                             "全件一致": state_check["全件一致"], "SHA256": U.sha(state_path),
                             "検証範囲": state_check["検証範囲"], "限界": state_check["限界"],
                             "コードSHA256": U.sha(ROOT / "scripts/VWAP復帰/状態独立確認.py")} if state_check else None,
              "通常出口独立確認": normal_check,
              "Viewer記録": "Viewer照合.json" if views else None,
              "独立補助SHA256": {p: U.sha(ROOT / p) for p in ("scripts/テクニカル循環/独立監査.py", "scripts/利益回収/運用独立監査.py",
                                   "scripts/外部探索/運用独立監査.py", "scripts/広域研究/運用独立監査.py", "scripts/入口分析/独立照合.py")},
              "会計範囲": "全12入口先着を気配直接再判定。36×65のDecimal会計/注文・約定・帰属/待機/単一建玉/保存MFE・MAE/全X0要求初着/DD/正式片・CSV/期間集計・支持を検算。",
              "状態範囲": "別コードで原価格/補助cacheから1/3/5/15分OHLC・独立ATR/上位EMA・固定18と同じ補助参照・Q1/Q2の12発動集合を再構築。子の照合件数は主件数へ加算せず別掲。通常出口は別処理で全X1/X2の最初返済要求と線更新/抑止を検査する。詳細な範囲と限界は状態独立確認を参照。",
              "DD": "各場0開始・約定後の正常BBO時価・返済手数料込み。期間は最大一場DDで累積DDではない。"}
    target = STUDY / "独立監査.json" if complete else WORK / "会計監査_途中.json"
    H.write(target, output)
    print(json.dumps({"全件一致": not audit.errors, "照合項目数": audit.count, "不一致数": len(audit.errors),
                      "不一致": audit.errors[:10], "状態確認未完": state_check is None, "通常出口確認未完": normal_check is None, "先着件数": len(cases)}, ensure_ascii=False, default=float))
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="00019原気配・会計・状態独立監査")
    parser.add_argument("--api-base")
    args = parser.parse_args()
    output = run(args.api_base.rstrip("/") if args.api_base else None)
    if not output["全件一致"]:
        raise SystemExit(1)
