"""00020の複合15入口・必須追尾45運用を、気配先着と独立会計から監査する。"""

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
STUDY = ROOT / "study/00020_テクニカル局面による順行反転の切替"
WORK = ROOT / "work/局面切替/00020"


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
    result.update(必須追尾返済数=sum(t["返済理由"] == "必須利益追尾" for t in trades),
                  追尾起動取引数=sum(t["追尾起動"] for t in trades),
                  起動後純赤字取引数=sum(t["起動後純赤字"] for t in trades),
                  追尾線更新回数=sum(r["追尾線更新回数"] for r in rows),
                  買い取引数=sum(t["方向"] == "買い" for t in trades),
                  売り取引数=sum(t["方向"] == "売り" for t in trades),
                  役割別完結数={role: sum(t["入口役割"] == role for t in trades) for role in ("順行", "反転")})
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
    """全運用の保有MFE/MAEと、同値以上の追尾設定を直接気配で検算する。

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
        audit.check(name + ":全出口必須追尾", trade["必須追尾使用"], True)
        audit.check(name + ":追尾一呼値起動", trade["追尾起動幅pt"], 5)
        audit.check(name + ":入口ATR追尾幅", trade["追尾距離pt"], max(5, np.ceil(trade["入口ATR"]/5)*5))
        audit.check(name + ":起動後赤字分類", trade["起動後純赤字"], bool(trade["追尾起動"] and trade["基準純損益円"] < 0))
        if trade["追尾起動"]:
            audit.check(name + ":最低同値設定", side*(trade["最終追尾価格"]-trade["新規価格"]) >= 0, True)
            audit.check(name + ":追尾起動時刻存在", trade["追尾起動時計秒"] is not None and trade["追尾起動原板行"] is not None, True)
            audit.check(name + ":実返済不足符号", trade["最終追尾から実返済方向差pt"], side*(trade["返済価格"]-trade["最終追尾価格"]))
        else:
            audit.check(name + ":未起動線なし", trade["最終追尾価格"], None)



# ----------------------------------------
# 両役割の表示固定3分で、同じ入口の出口三種をそれぞれ確認する。

def viewer(rows: list[dict], api: str, audit: Any) -> dict:
    """事前固定の三分五戦略について同じ場のX0/X2を照合する。

    引数: rows(list[dict])は独立会計、api(str)は接続先、audit(Any)は照合先。
    返り値: dictは十資源のAPI検査。表示の事後場選択を戦略採用に使わない。
    """
    helper = load(ROOT / "scripts/複合検証/Viewer照合.py", "局面切替の表示確認")
    resources = {(r["method_id"], r["session"]): r for r in H.read(STUDY / "一覧.resources.json")["resources"]}
    body, _ = helper.fetch(api + "/api/resources?" + helper.urlencode({"catalog_path": (STUDY / "一覧.resources.json").relative_to(ROOT).as_posix()}))
    audit.check("Viewer資源集合", {r["id"] for r in json.loads(body)["resources"]}, {r["id"] for r in resources.values()})
    checks = []
    for strategy in ("B1", "B2", "S0", "S1", "S2"):
        prefix = "3分_" + strategy + "_"
        eligible = [r for r in rows if r["候補ID"].startswith(prefix) and (r["候補ID"], r["場"]) in resources]
        selected = sorted(eligible, key=lambda r: (-abs(r["観測現金増減円"]), r["候補ID"], r["場"]))[0]
        for policy in ("X0", "X2"):
            cid = "3分_" + strategy + "_" + policy
            row = next(r for r in rows if r["候補ID"] == cid and r["場"] == selected["場"])
            adapted = {"銘柄": "NK225", "場": row["場"], "手法": cid, "純損益円": float(row["観測現金増減円"]), "取引数": row["完結取引数"]}
            checked = helper.check_one(api, STUDY, adapted, resources[(cid, row["場"])], "三分五戦略の同場二出口", False)
            checked.update(観測経路注意=row["観測経路注意"], 確定対象純損益円=row["確定対象純損益円"])
            checks.append(checked)
    with urlopen(api + "/api/info", timeout=10) as stream:
        info = json.load(stream)
    return {"確認日時": datetime.now(U.HELPER.JST).isoformat(), "接続先": api, "API情報": info,
        "設定": "work/viewer/conf/viewer.toml", "WindowStyle": "Hidden", "照合": checks, "追加PNG数": 0,
        "Viewer実行コピーSHA256": U.sha(ROOT / "work/viewer/session-trade-viewer.exe"),
        "指定配布版SHA256": U.sha(ROOT.parent / "SessionTradeViewer/dist/windows-amd64/SessionTradeViewer/session-trade-viewer.exe"),
        "代表規則": "事前表示三分五戦略×X0/X2の十資源。各戦略の最大絶対観測額と同場二出口を表示。採用選択ではない。"}



def run(api: str | None) -> dict:
    """完成した20出力を検算し、状態独立確認後だけ正式な総合監査を保存する。

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
    shadow, price_sha = H.rows(WORK / "全複合shadow.jsonl.gz")
    price_count = len(shadow)
    normal_records, normal_sha = H.rows(WORK / "通常線と追尾.jsonl.gz")
    normal_count = len(normal_records)
    normal_updates, trail_updates = {}, {}
    for record in normal_records:
        key = record["候補ID"], record["場"]
        normal_updates[key] = normal_updates.get(key, 0) + (record["動作"] == "通常線更新")
        trail_updates[key] = trail_updates.get(key, 0) + (record["動作"] == "追尾線更新")
    contents = {str(ROOT / item["パス"]): content_stats(ROOT / item["パス"])[0] for item in H.read(STUDY / "作業成果物.json")["ファイル"]}
    auxiliary = H.read(STUDY / "補助入力台帳.json")
    auxiliary_source = (STUDY / auxiliary["参照"]).resolve()
    audit.check("補助参照台帳SHA", U.sha(auxiliary_source), auxiliary["SHA256"])
    for item in H.read(STUDY / "作業成果物.json")["ファイル"]:
        audit.check("作業展開SHA:" + item["パス"], contents[str(ROOT / item["パス"])], item["展開内容SHA256"])
    entrance = H.entry_audit(cases, result, entries, config, audit)
    label_quotes = {}
    for source in shadow:
        session = source["場"]
        if session not in label_quotes:
            entry = entries[session]
            label_quotes[session] = H.L.load_quotes(ROOT / "work/複合検証" / entry["cache_path"], entry)[0]
        _, _, cutoff, deadline = H.L.session_times(session)
        direct = H.L.label_direct(label_quotes[session], source["要求時計秒"], cutoff, deadline, source["side"], adverse=125, favorable=250)
        for key, value in direct.items():
            audit.check(source["QイベントID"] + ":全shadow直接先着:" + key, source[key], value)
    entrance["全shadow直接先着件数"] = len(shadow)
    entrance["限界"] = "全保存入口の先着を正常気配から直接再判定。別の状態独立確認で原価格/補助cacheから全価格足/指標/固定18参照/Q1Q2の15選択集合を独立再構成する。全仮約定の先着は実運用の一建玉参加集合とは分ける。"
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
        row["追尾線更新回数"] = trail_updates.get((cid, session), 0)
        audit.check(cid + session + ":追尾線更新回数", d["品質"]["追尾線更新回数"], row["追尾線更新回数"])
        for trade in d["取引"]:
            audit.check(cid + trade["建玉ID"] + ":実新規役割固定", trade["入口役割"], source_cases[(source, session, trade["入口イベントID"])]["役割"])
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
    audit.check("45候補×65場", len(details), 2925)
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
        qualified = candidate["入口"]["複合本命"] and all(all(periods[p][field] >= minimum for field, minimum in limits.items())
                        and periods[p]["品質注意場数"] == 0 and periods[p]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        audit.check(cid + ":費用資格", candidate["費用資格"], qualified)
        qualified_count += qualified
    audit.check("費用資格数", result["費用資格数"], qualified_count)
    expected_ids = [f"3分_{strategy}_{policy}" for strategy in config["戦略"] for policy in ("X0", "X2")]
    audit.check("事前固定3分五戦略二出口表示", result["表示固定ID"], expected_ids)
    files = U.artifacts(STUDY, details, result["表示固定ID"], entries, audit)
    views = viewer(rows, api, audit) if api else None
    if views:
        H.write(STUDY / "Viewer照合.json", views)
    state_path = WORK / "状態独立確認.json"
    state_check = H.read(state_path) if state_path.exists() else None
    if state_check:
        audit.check("原価格からの状態独立再構成", state_check["全件一致"], True)
        for field, expected in (("コードSHA256", U.sha(ROOT/"scripts/局面切替/状態独立確認.py")),
                                ("入力台帳SHA256", U.sha(manifest)),
                                ("補助入力台帳SHA256", U.sha(auxiliary_source)),
                                ("全足参照展開SHA256", foot_sha), ("発動候補展開SHA256", price_sha),
                                ("入口事例展開SHA256", case_sha),
                                ("保存参照足数", foot_count), ("保存発動候補数", price_count), ("保存入口数", len(cases))):
            audit.check("状態独立確認の対象と版:" + field, state_check[field], expected)
        for filename, hash_field, count_field in (("全局面.jsonl.gz", "全局面展開SHA256", "保存局面数"),
                                                  ("全複合context.jsonl.gz", "全複合context展開SHA256", "保存context数"),
                                                  ("上位足.jsonl.gz", "上位足展開SHA256", "保存上位足数")):
            digest, count = content_stats(WORK / filename)
            audit.check("状態独立確認の追加出典:" + hash_field, state_check[hash_field], digest)
            audit.check("状態独立確認の追加集合:" + count_field, state_check[count_field], count)
        audit.check("状態独立確認の旧19証明", state_check["旧19独立確認SHA256"], U.sha(ROOT / "work/VWAP復帰/00019/状態独立確認.json"))
        audit.check("状態独立確認の独立Q補助", state_check["独立Q補助SHA256"], U.sha(ROOT / "scripts/VWAP復帰/状態独立確認.py"))
        H.write(STUDY / "状態独立確認.json", state_check)
    normal_path = WORK / "追尾独立確認.json"
    normal_check = H.read(normal_path) if normal_path.exists() else None
    if normal_check:
        audit.check("通常出口の最初要求全件検算", normal_check["全件一致"], True)
        for field, expected in (("コードSHA256", U.sha(ROOT / "scripts/局面切替/追尾独立確認.py")),
                                ("結果SHA256", U.sha(STUDY / "結果.json")),
                                ("全運用詳細展開SHA256", detailed_sha), ("通常線更新展開SHA256", normal_sha),
                                ("入口事例展開SHA256", case_sha), ("全足参照展開SHA256", foot_sha),
                                ("保存通常線行数", normal_count),
                                ("対象完結取引数", sum(len(d["取引"]) for d in raw))):
            audit.check("通常出口監査の対象と版:" + field, normal_check[field], expected)
        audit.check("追尾独立確認の状態証明", normal_check["状態独立確認SHA256"], U.sha(state_path))
        audit.check("追尾独立確認の入力台帳", normal_check["入力台帳SHA256"], U.sha(manifest))
        H.write(STUDY / "追尾独立確認.json", normal_check)
    complete = state_check is not None and normal_check is not None
    output = {"全件一致": not audit.errors, "照合項目数": audit.count, "不一致数": len(audit.errors), "不一致": audit.errors,
              "状態確認未完": state_check is None, "通常出口確認未完": normal_check is None, "確認日時": datetime.now(U.HELPER.JST).isoformat(),
              "コードSHA256": U.sha(Path(__file__)), "結果SHA256": U.sha(STUDY / "結果.json"), "全65場既使用": True,
              "固定後SHA変化件数": sum(e["項目"].startswith("実行前固定後SHA:") for e in audit.errors),
              "入口": entrance, "運用期間別": aggregates, "正式資源": files,
              "状態独立確認": {"参照": "状態独立確認.json", "照合項目数": state_check["照合項目数"],
                             "全件一致": state_check["全件一致"], "SHA256": U.sha(state_path),
                             "検証範囲": state_check["検証範囲"], "限界": state_check["限界"],
                             "コードSHA256": U.sha(ROOT / "scripts/局面切替/状態独立確認.py")} if state_check else None,
              "追尾独立確認": normal_check,
              "Viewer記録": "Viewer照合.json" if views else None,
              "独立補助SHA256": {p: U.sha(ROOT / p) for p in ("scripts/テクニカル循環/独立監査.py", "scripts/利益回収/運用独立監査.py",
                                   "scripts/外部探索/運用独立監査.py", "scripts/広域研究/運用独立監査.py", "scripts/入口分析/独立照合.py")},
              "会計範囲": "全15入口先着を気配直接再判定。45×65のDecimal会計/注文・約定・帰属/待機/単一建玉/保存MFE・MAE/全出口の必須追尾設定/DD/正式片・CSV/期間集計・支持を検算。",
              "状態範囲": "別コードで原価格/補助cacheから1/3/5/15/60分OHLC・独立EMA10/20・RSI/ATR/ADX/DMI・固定18と同じ補助参照・Q1/Q2の15選択集合を再構築。子の照合件数は主件数へ加算せず別掲。通常出口は別処理で全X0/X1/X2の最初返済要求・役割固定・必須追尾と線更新/抑止を検査する。詳細な範囲と限界は状態独立確認を参照。",
              "DD": "各場0開始・約定後の正常BBO時価・返済手数料込み。期間は最大一場DDで累積DDではない。"}
    target = STUDY / "独立監査.json" if complete else WORK / "会計監査_途中.json"
    H.write(target, output)
    print(json.dumps({"全件一致": not audit.errors, "照合項目数": audit.count, "不一致数": len(audit.errors),
                      "不一致": audit.errors[:10], "状態確認未完": state_check is None, "通常出口確認未完": normal_check is None, "先着件数": len(cases)}, ensure_ascii=False, default=float))
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="00020原気配・会計・状態独立監査")
    parser.add_argument("--api-base")
    args = parser.parse_args()
    output = run(args.api_base.rstrip("/") if args.api_base else None)
    if not output["全件一致"]:
        raise SystemExit(1)
